# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Marco Sumari Tellez and IngeTrazo contributors.
"""The plan's own drawn lines — LINE, PLINE, ARC and CIRCLE as DATA.

A plan is not only what the model already says. The office draws the ridge
of a roof nobody modelled, a setback line, an arc for a curved balustrade,
a circle around a detail. Those are DRAWING entities — two dimensions of
information standing at one storey's cut — and they belong where the rest
of the drawing's data lives, beside ``scene.dimensions`` and
``scene.text_labels``.

They are stored as plain geometry in MODEL metres on a named layer, with
the storey they were drawn on, exactly as a dimension is: a curve drawn on
the ground floor must not appear on the roof's plan, and the DXF writer,
the composer and the plan window must all find it by the same rule.

The shapes follow the CAD commands an architect already knows — a
``LINE`` is two points, a ``POLYLINE`` a run of them, a 2-point ``ARC`` is
the half circle on a diameter, a 3-point ``ARC`` the circumcircle through
three, a ``CIRCLE`` a centre and a radius — because a drawing tool that
disagrees with the one the office trained on is a tool that produces
drawings nobody asked for.
"""
from __future__ import annotations

import math

#: What a curve IS. Kept as strings so the file stays readable and a
#: future kind (an ellipse, a spline) does not invalidate older ones.
LINE = "line"
POLYLINE = "polyline"
ARC = "arc"          # 3 points: start, a point ON the arc, end
HALF_ARC = "arc2"    # 2 points: the half circle on their diameter
CIRCLE = "circle"

#: The kinds a file may hold, for validation on load.
KINDS = (LINE, POLYLINE, ARC, HALF_ARC, CIRCLE)


def _vector(row) -> tuple:
    """``(x, y)`` from whatever a caller passed: a pair, a QVector3D, a
    dict — the plan, the file and the tests all speak slightly different
    shapes and none of them is worth a conversion at every call site."""
    if row is None:
        return (0.0, 0.0)
    if isinstance(row, dict):
        return (float(row.get("x", 0.0)), float(row.get("y", 0.0)))
    if hasattr(row, "x") and hasattr(row, "y"):
        return (float(row.x()), float(row.y()))
    seq = list(row)
    return (float(seq[0]), float(seq[1]))


def circumcircle(a, b, c):
    """``(centre, radius)`` through three points, or ``None`` when they are
    collinear.

    Collinear input has NO circle: the arithmetic below divides by zero,
    and a tool that wrote a NaN radius would put an entity in the file that
    no viewer can read. The caller refuses the click instead.
    """
    ax, ay = _vector(a)
    bx, by = _vector(b)
    cx, cy = _vector(c)
    d = 2.0 * (ax * (by - cy) + bx * (cy - ay) + cx * (ay - by))
    if abs(d) < 1e-12:
        return None
    a2 = ax * ax + ay * ay
    b2 = bx * bx + by * by
    c2 = cx * cx + cy * cy
    ux = (a2 * (by - cy) + b2 * (cy - ay) + c2 * (ay - by)) / d
    uy = (a2 * (cx - bx) + b2 * (ax - cx) + c2 * (bx - ax)) / d
    centre = (ux, uy)
    radius = math.hypot(ax - ux, ay - uy)
    if not math.isfinite(radius) or radius <= 1e-9:
        return None
    return (centre, radius)


class PlanCurve:
    """One drawn entity on a plan: its kind, its points, its storey.

    ``points`` are model millimetres as the plan's own transform speaks
    them; ``z`` is the height the drawing sits at (the storey's cut), so
    the issued sheet — which looks for annotations at its own cut — finds
    it. ``layer`` lets the office file it where its own standards say.
    """

    __slots__ = ("kind", "points", "z", "story_id", "layer", "id")

    def __init__(self, kind: str, points, z: float = 0.0,
                 story_id: str = "", layer: str = "", id: str = "") -> None:
        self.kind = str(kind)
        self.points = [(float(p[0]), float(p[1])) for p in points]
        self.z = float(z)
        self.story_id = str(story_id or "")
        self.layer = str(layer or "")
        self.id = str(id or "")

    # ---- the shape it describes ------------------------------------------
    def centre_radius(self):
        """``(centre, radius)`` for the round kinds, else ``None``."""
        if self.kind == CIRCLE:
            if len(self.points) < 2:
                return None
            (cx, cy), (rx, ry) = self.points[0], self.points[1]
            radius = math.hypot(rx - cx, ry - cy)
            return ((cx, cy), radius) if radius > 1e-9 else None
        if self.kind == HALF_ARC:
            if len(self.points) < 2:
                return None
            (x1, y1), (x2, y2) = self.points[0], self.points[1]
            radius = math.hypot(x2 - x1, y2 - y1) / 2.0
            if radius <= 1e-9:
                return None
            return (((x1 + x2) / 2.0, (y1 + y2) / 2.0), radius)
        if self.kind == ARC:
            if len(self.points) < 3:
                return None
            return circumcircle(*self.points[:3])
        return None

    def segments(self, arc_step_deg: float = 5.0) -> list:
        """``[(x1, y1, x2, y2), …]`` — the shape as straight pieces.

        Renders that only know how to draw a line (the DXF fallback, the
        magnifier, a test) go through here rather than each learning about
        arcs; the faceting step is generous enough that a printed arc reads
        as an arc at any plan scale.
        """
        if self.kind == LINE:
            if len(self.points) < 2:
                return []
            (x1, y1), (x2, y2) = self.points[0], self.points[1]
            return [(x1, y1, x2, y2)]
        if self.kind == POLYLINE:
            return [(self.points[i][0], self.points[i][1],
                     self.points[i + 1][0], self.points[i + 1][1])
                    for i in range(len(self.points) - 1)]
        found = self.centre_radius()
        if found is None:
            return []
        (cx, cy), radius = found
        angles = self._arc_angles()
        if angles is None:
            return []
        a0, a1 = angles
        sweep = a1 - a0
        if self.kind == CIRCLE and sweep <= 0.0:
            # A full circle wants a positive turn; a HALF arc's SIGN is
            # its bulge, and normalising it here would flip the arch back
            # under its own springing (_arc_angles already answered the
            # direction the convention asks for).
            sweep += 2.0 * math.pi
        if abs(sweep) < 1e-9:
            return []
        step = math.radians(max(1.0, float(arc_step_deg)))
        count = max(2, int(math.ceil(abs(sweep) / step)))
        out: list = []
        for i in range(count):
            t0 = a0 + sweep * (i / count)
            t1 = a0 + sweep * ((i + 1) / count)
            out.append((cx + radius * math.cos(t0),
                        cy + radius * math.sin(t0),
                        cx + radius * math.cos(t1),
                        cy + radius * math.sin(t1)))
        return out

    def _arc_angles(self):
        """``(start_angle, end_angle)`` going the short way for a 3-point
        arc — the arc through the middle point, not the complement of it.

        ``None`` when the shape has no circle at all (three collinear
        points, a zero radius): there are no angles to answer with.
        """
        found = self.centre_radius()
        if found is None:
            return None
        (cx, cy), _radius = found
        if self.kind == HALF_ARC:
            # The half circle bulges to the LEFT of the direction the
            # draughtsman drew — the convention every CAD's own 2-point arc
            # follows. Start is the first point, so the sweep turns
            # COUNTER-clockwise from it: direction (1,0) puts the bulge at
            # +y, not −y, and a balustrade arc drawn left to right arches
            # UP the way the hand drew it.
            (x1, y1), (x2, y2) = self.points[0], self.points[1]
            direction = math.atan2(y2 - y1, x2 - x1)
            # The start point sits OPPOSITE the drawing direction from the
            # centre, and the sweep runs back the way a right hand turns:
            # −90°, which puts the bulge on the LEFT of the direction
            # drawn. (A counter-clockwise sweep would arch it the other
            # way — a balustrade drawn left to right would dip below its
            # own springing.)
            return (direction + math.pi, direction)
        if self.kind == CIRCLE:
            return (0.0, 2.0 * math.pi)
        (x1, y1), (xm, ym), (x2, y2) = self.points[:3]
        a0 = math.atan2(y1 - cy, x1 - cx)
        am = math.atan2(ym - cy, xm - cx)
        a1 = math.atan2(y2 - cy, x2 - cx)
        # The middle point says which of the two arcs is the one asked for.
        # Take the sweep from start to end that CONTAINS it; if the direct
        # sweep does not, the complement is the answer.
        span = (a1 - a0) % (2.0 * math.pi)
        if (am - a0) % (2.0 * math.pi) > span:
            span -= 2.0 * math.pi
        return (a0, a0 + span)

    def is_degenerate(self) -> bool:
        """True when the shape would put nothing readable on paper."""
        if self.kind == LINE:
            if len(self.points) < 2:
                return True
            (x1, y1), (x2, y2) = self.points[0], self.points[1]
            return math.hypot(x2 - x1, y2 - y1) <= 1e-6
        if self.kind == POLYLINE:
            if len(self.points) < 2:
                return True
            return all(math.hypot(self.points[i + 1][0] - self.points[i][0],
                                  self.points[i + 1][1] - self.points[i][1])
                       <= 1e-6
                       for i in range(len(self.points) - 1))
        return self.centre_radius() is None

    # ---- persistence ------------------------------------------------------
    def to_dict(self) -> dict:
        row = {"kind": self.kind,
               "points": [[x, y] for x, y in self.points],
               "z": self.z}
        if self.story_id:
            row["story_id"] = self.story_id
        if self.layer:
            row["layer"] = self.layer
        if self.id:
            row["id"] = self.id
        return row

    @classmethod
    def from_dict(cls, raw: dict) -> "PlanCurve":
        row = dict(raw or {})
        kind = str(row.get("kind") or LINE)
        points = row.get("points") or []
        return cls(kind if kind in KINDS else LINE, points,
                   z=float(row.get("z", 0.0) or 0.0),
                   story_id=str(row.get("story_id") or ""),
                   layer=str(row.get("layer") or ""),
                   id=str(row.get("id") or ""))

    def __repr__(self) -> str:                      # pragma: no cover
        return f"PlanCurve({self.kind}, {len(self.points)} pts, z={self.z})"


def curves_at(scene, z: float, tolerance: float = 0.002) -> list:
    """The curves drawn at ``z`` (the plan's own cut), as the sheet asks.

    The same rule the dimensions obey: a drawing carries the annotations
    standing at its cut, so a ground-floor line never prints on the roof's
    plan. ``tolerance`` is 2 mm — far below any draughting precision and
    far above floating-point noise.
    """
    out: list = []
    for curve in (getattr(scene, "plan_curves", None) or ()):
        if abs(float(getattr(curve, "z", 0.0)) - float(z)) <= tolerance:
            out.append(curve)
    return out
