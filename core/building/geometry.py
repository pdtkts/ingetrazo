# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Marco Sumari Tellez and IngeTrazo contributors.
"""Solid construction primitives for parametric elements.

Everything here works in an element's **local frame** and returns faces in
world coordinates through a small frame object. The point is that a wall with
a door in it, a beam, a column and a stair body are all assembled from the
same handful of moves — a face with holes, an extrusion, a box — so the
drawing pipeline sees one kind of geometry no matter which element made it.

The wall solid is the demanding one: it has to be **watertight** (the IFC
volume, and the "is this a closed solid" test, both read the same shell), so
its face list covers the two sides, the two ends *as trimmed by the join
solver*, the top, the base split by floor-level openings, and the reveal
faces of every opening — jambs, heads and sills. Openings that do not reach
the floor leave a hole in both faces instead.
"""
from __future__ import annotations

import math

from PySide6.QtGui import QVector3D

#: Openings must stay this far from a mitred end (mm).
MARGIN = 1.0
#: Below this, an opening touches the floor and splits the base.
FLOOR_EPS = 0.5


class Frame:
    """The local frame of an element: a point and three unit directions.

    ``to_abs(u, v, w)`` maps local millimetres to world millimetres. ``u`` runs
    along the element's axis, ``v`` up, ``w`` across the thickness (0 = the
    near face). The scene works in metres, so :meth:`point` divides by 1000 at
    the boundary — the only place the conversion happens.
    """

    __slots__ = ("origin", "dir", "up", "perp", "w0")

    def __init__(self, origin, dir, up=(0.0, 0.0, 1.0), perp=None,
                 w0: float = 0.0) -> None:
        self.origin = (float(origin[0]), float(origin[1]),
                       float(origin[2]) if len(origin) > 2 else 0.0)
        self.dir = _unit3(dir)
        self.up = _unit3(up)
        if perp is None:
            perp = (self.dir[1] * self.up[2] - self.dir[2] * self.up[1],
                    self.dir[2] * self.up[0] - self.dir[0] * self.up[2],
                    self.dir[0] * self.up[1] - self.dir[1] * self.up[0])
        self.perp = _unit3(perp)
        self.w0 = float(w0)

    def local(self, u: float, v: float, w: float = 0.0):
        """World millimetres of a local point."""
        return (self.origin[0] + self.dir[0] * u + self.up[0] * v
                + self.perp[0] * (self.w0 + w),
                self.origin[1] + self.dir[1] * u + self.up[1] * v
                + self.perp[1] * (self.w0 + w),
                self.origin[2] + self.dir[2] * u + self.up[2] * v
                + self.perp[2] * (self.w0 + w))

    def point(self, u: float, v: float, w: float = 0.0) -> QVector3D:
        """The same, in scene units (metres)."""
        x, y, z = self.local(u, v, w)
        return QVector3D(x / 1000.0, y / 1000.0, z / 1000.0)

    def loop(self, points) -> list:
        """A world-space loop (metres) from ``(u, v, w)`` triples."""
        return [self.point(*p) for p in points]


def _unit3(v):
    n = math.sqrt(v[0] * v[0] + v[1] * v[1] + v[2] * v[2])
    return (0.0, 0.0, 1.0) if n < 1e-12 else (v[0] / n, v[1] / n, v[2] / n)


def world_frame(origin, dir, up=(0.0, 0.0, 1.0), w0: float = 0.0) -> Frame:
    """A frame from a world point and a plan direction."""
    d = _unit3((dir[0], dir[1], 0.0))
    return Frame(origin, d, up, w0=w0)


# ---- mesh helpers -----------------------------------------------------------

def add_loop(mesh, points, holes=None):
    """Add one face (with optional hole loops) to ``mesh``; returns the face."""
    if holes:
        return mesh.add_face(points, holes)
    return mesh.add_face(points)


def add_box(mesh, frame: Frame, u0: float, v0: float, w0: float,
            u1: float, v1: float, w1: float):
    """A closed box in the frame's local coordinates (6 faces)."""
    lo_u, hi_u = min(u0, u1), max(u0, u1)
    lo_v, hi_v = min(v0, v1), max(v0, v1)
    lo_w, hi_w = min(w0, w1), max(w0, w1)
    c = [(lo_u, lo_v, lo_w), (hi_u, lo_v, lo_w),
         (hi_u, hi_v, lo_w), (lo_u, hi_v, lo_w),
         (lo_u, lo_v, hi_w), (hi_u, lo_v, hi_w),
         (hi_u, hi_v, hi_w), (lo_u, hi_v, hi_w)]
    faces = (
        (0, 1, 2, 3),          # near (w = lo)
        (7, 6, 5, 4),          # far  (w = hi)
        (0, 4, 5, 1),          # base (v = lo)
        (3, 2, 6, 7),          # top  (v = hi)
        (0, 3, 7, 4),          # start (u = lo)
        (1, 5, 6, 2),          # end   (u = hi)
    )
    out = []
    for f in faces:
        out.append(mesh.add_face([frame.point(*c[i]) for i in f]))
    return out


def wall_solid_faces(ends, height: float, thickness: float,
                     floor_ranges=(), holes=()):
    """The face list of a wall body, in local ``(u, v, w)`` triples.

    ``ends`` is ``{"near": (u0, u1), "far": (u0, u1)}`` — where each face stops
    at each end (usually the same pair for both, different when mitred).
    ``floor_ranges`` are ``(u0, u1, v1)`` openings that reach the floor and
    split the base; ``holes`` are ``(u0, u1, v0, v1)`` openings that do not.

    Returns ``[(outer_loop, [hole_loops]), ...]``. Raises ``ValueError`` when
    the end offsets leave nothing to build or an opening has no room left.
    """
    t = float(thickness)
    h = float(height)
    if h <= 0 or t <= 0:
        raise ValueError("Chiều dày và chiều cao phải dương.")
    n0, n1 = min(ends["near"]), max(ends["near"])
    f0, f1 = min(ends["far"]), max(ends["far"])
    if n1 - n0 < MARGIN or f1 - f0 < MARGIN:
        raise ValueError("Đầu tường bị cắt hết (kiểm tra nối tường).")
    core0, core1 = max(n0, f0), min(n1, f1)

    # An opening that runs into a wall end SHORTENS the wall to its edge — the
    # wall stops where the door starts, exactly as the reference behaviour
    # does. Doing it here (not by clamping) is what keeps the shell watertight:
    # a clamped opening leaves a sliver too thin to have faces.
    raw_floors = []
    for u0, u1, v1 in floor_ranges or ():
        lo, hi = min(u0, u1), max(u0, u1)
        if hi < core0 + MARGIN or lo > core1 - MARGIN or v1 <= 0:
            continue                       # wholly outside: dropped
        lo = max(lo, core0)
        hi = min(hi, core1)
        if hi - lo <= MARGIN:
            continue
        raw_floors.append((lo, hi, min(float(v1), h)))
    for lo, hi, _v1 in raw_floors:
        if lo <= core0 + MARGIN:
            core0 = n0 = f0 = hi
        if hi >= core1 - MARGIN:
            core1 = n1 = f1 = lo
    floors = [(max(lo, core0), min(hi, core1), v1)
              for lo, hi, v1 in raw_floors
              if min(hi, core1) - max(lo, core0) > MARGIN]
    floors.sort()
    if n1 - n0 < MARGIN or f1 - f0 < MARGIN:
        raise ValueError("Lỗ mở chiếm hết chiều dài tường.")

    faces: list = []

    def reveal(p0, p1, p2, p3):
        faces.append(([p0, p1, p2, p3], []))

    # ---- near and far faces: outer loop with a notch per floor opening ----
    # Walk the bottom edge, stepping up and over each opening, then up the far
    # end, back across the top and down the near end — one closed loop.
    for w, (s0, s1) in ((0.0, (n0, n1)), (t, (f0, f1))):
        loop = []
        x = s0
        for lo, hi, v1 in floors:
            if lo > x:
                loop.append((x, 0.0, w))
            loop.append((lo, 0.0, w))
            loop.extend([(lo, v1, w), (hi, v1, w), (hi, 0.0, w)])
            x = hi
        if x < s1:
            loop.append((x, 0.0, w))
        elif not floors:
            loop.append((s0, 0.0, w))
        loop.append((s1, 0.0, w))
        # A floor opening that ends exactly at the wall end already put that
        # corner in: drop consecutive duplicates so the loop stays a loop.
        loop = [p for i, p in enumerate(loop)
                if i == 0 or p != loop[i - 1]]
        if len(loop) > 1 and loop[0] == loop[-1]:
            loop.pop()
        loop.extend([(s1, h, w), (s0, h, w)])
        # Interior holes punch this face (SketchUp-style: the hole is a loop
        # inside the outer one, and the mesh handles the triangulation).
        hole_loops = []
        for u0, u1, v0, v1 in holes or ():
            lo, hi = max(min(u0, u1), core0 + MARGIN), min(max(u0, u1),
                                                          core1 - MARGIN)
            vb, vt = max(float(v0), MARGIN), min(float(v1), h - MARGIN)
            if hi - lo <= 1.0 or vt - vb <= 1.0:
                continue
            hole_loops.append([(lo, vb, w), (hi, vb, w), (hi, vt, w),
                               (lo, vt, w)])
        faces.append((loop, hole_loops))

    # ---- top cap ----
    faces.append(([(n0, h, 0.0), (n1, h, 0.0), (f1, h, t), (f0, h, t)], []))

    # ---- base segments between floor openings ----
    # The base spans the whole footprint, mitred ends included (the end faces
    # close the diagonal part), and is split where a door reaches the floor.
    # The base is the wall's plan footprint — a trapezoid when a mitre swung
    # an end — cut by the full-width rectangles the floor openings take out.
    # Each piece is built as a quad so the mitred ends stay closed.
    left0, leftt = n0, f0
    for lo, hi, _v1 in floors:
        if lo - left0 > MARGIN:
            faces.append(([(left0, 0.0, 0.0), (lo, 0.0, 0.0), (lo, 0.0, t),
                           (leftt, 0.0, t)], []))
        left0, leftt = hi, hi
    if n1 - left0 > MARGIN:
        faces.append(([(left0, 0.0, 0.0), (n1, 0.0, 0.0), (f1, 0.0, t),
                       (leftt, 0.0, t)], []))

    # ---- end faces (skewed when a join trimmed one face further) ----
    if abs(n0 - f0) > 1e-6:
        faces.append(([(n0, 0.0, 0.0), (n0, h, 0.0), (f0, h, t),
                       (f0, 0.0, t)], []))
    else:
        faces.append(([(n0, 0.0, 0.0), (n0, h, 0.0), (f0, h, t),
                       (f0, 0.0, t)], []))
    if abs(n1 - f1) > 1e-6:
        faces.append(([(f1, 0.0, t), (f1, h, t), (n1, h, 0.0),
                       (n1, 0.0, 0.0)], []))
    else:
        faces.append(([(f1, 0.0, t), (f1, h, t), (n1, h, 0.0),
                       (n1, 0.0, 0.0)], []))

    # ---- floor-opening reveals: two jambs and a head ----
    # A jamb that sits exactly on a face end is not drawn: that end's own face
    # already closes the shell there.
    for lo, hi, v1 in floors:
        if lo > max(n0, f0) + MARGIN:
            reveal((lo, 0.0, 0.0), (lo, v1, 0.0), (lo, v1, t), (lo, 0.0, t))
        if hi < min(n1, f1) - MARGIN:
            reveal((hi, 0.0, t), (hi, v1, t), (hi, v1, 0.0), (hi, 0.0, 0.0))
        reveal((lo, v1, 0.0), (hi, v1, 0.0), (hi, v1, t), (lo, v1, t))

    # ---- interior holes: sill, head, two jambs ----
    for u0, u1, v0, v1 in holes or ():
        lo = max(min(u0, u1), core0 + MARGIN)
        hi = min(max(u0, u1), core1 - MARGIN)
        vb = max(float(v0), MARGIN)
        vt = min(float(v1), h - MARGIN)
        if hi - lo <= 1.0 or vt - vb <= 1.0:
            continue
        reveal((lo, vb, 0.0), (hi, vb, 0.0), (hi, vb, t), (lo, vb, t))
        reveal((lo, vt, t), (hi, vt, t), (hi, vt, 0.0), (lo, vt, 0.0))
        reveal((lo, vb, t), (lo, vt, t), (lo, vt, 0.0), (lo, vb, 0.0))
        reveal((hi, vb, 0.0), (hi, vt, 0.0), (hi, vt, t), (hi, vb, t))

    return faces


def manifold_gaps(faces, eps: float = 1e-6):
    """Every edge of the shell that is not shared by exactly two faces.

    The self-check a watertight solid must pass — same test an IFC body needs.
    Distances are in scene units (metres).
    """
    from collections import defaultdict
    counts: dict = defaultdict(int)
    for outer, hole_loops in faces:
        for loop in (outer, *(hole_loops or ())):
            n = len(loop)
            for i in range(n):
                a = loop[i]
                b = loop[(i + 1) % n]
                key = tuple(sorted((_round3(a), _round3(b)), key=str))
                counts[key] += 1
    return [edge for edge, n in counts.items() if n != 2]


def _round3(p) -> tuple:
    if hasattr(p, "x"):
        return (round(p.x(), 6), round(p.y(), 6), round(p.z(), 6))
    return (round(float(p[0]), 6), round(float(p[1]), 6),
            round(float(p[2]), 6))
