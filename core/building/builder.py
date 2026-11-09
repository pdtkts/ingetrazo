# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Marco Sumari Tellez and IngeTrazo contributors.
"""Element geometry builders — parameters in, meshes out.

Each builder takes an element's parameters plus its storey and fills a fresh
:class:`~core.mesh.Mesh` with the element's solid. Nothing here decides *when*
to rebuild; :mod:`core.building.scene_sync` owns that. Nothing here reads the
scene either, apart from the storey list it is handed, which keeps every
builder a pure function on the way in: parameters and storeys, nothing else.

The builders share the wall solid machinery in :mod:`.geometry`, so a wall with
a door in it, a service shaft or a column are all closed shells built from the
same face vocabulary — which is what the IFC volume and the section cuts need.
"""
from __future__ import annotations

import math

from core.building import elements as schemas
from core.building.geometry import (FLOOR_EPS, Frame, add_box,
                                    wall_solid_faces, world_frame)
from core.mesh import Mesh

#: How many segments a round column's circle gets.
ROUND_SEGMENTS = 60


# ---- storey helpers ---------------------------------------------------------

def story_of(building, element) -> dict | None:
    return building.story(str(element.get("story_id") or ""))


def story_above(building, story: dict | None) -> dict | None:
    if story is None:
        return None
    z = float(story.get("z_mm", 0.0))
    ups = [s for s in building.stories if float(s.get("z_mm", 0.0)) > z + 1e-6]
    return min(ups, key=lambda s: float(s.get("z_mm", 0.0))) if ups else None


def effective_height(building, params: dict, story: dict | None) -> float:
    """A linked element's height: up to the storey above, else its own."""
    base_off = float(params.get("base_offset_mm", 0.0) or 0.0)
    if story is not None and params.get("top_link") == "next":
        above = story_above(building, story)
        if above is not None:
            top = float(above.get("z_mm", 0.0)) + float(
                params.get("top_offset_mm", 0.0) or 0.0)
            base = float(story.get("z_mm", 0.0)) + base_off
            h = top - base
            if h > 1.0:
                return h
    return float(params.get("height_mm", 3300.0) or 3300.0)


def base_z(building, params: dict, story: dict | None) -> float:
    z = float((story or {}).get("z_mm", 0.0))
    return z + float(params.get("base_offset_mm", 0.0) or 0.0)


# ---- walls ------------------------------------------------------------------

def build_wall(building, element, joins=None) -> tuple[Mesh, dict]:
    """A wall body: two mitred ends, floor openings cut to the base.

    ``joins`` is the result of :func:`core.building.planar.join_walls` for the
    storey; without it the wall runs its full length. Returns the mesh and the
    derived data the takeoff and the drawings read.
    """
    params = element.get("params") or {}
    story = story_of(building, element)
    if story is None:
        raise ValueError("Tường không thuộc tầng nào.")
    p0 = params.get("baseline_start_mm")
    p1 = params.get("baseline_end_mm")
    if not p0 or not p1:
        raise ValueError("Tường thiếu đường chuẩn.")
    length = math.hypot(float(p1[0]) - float(p0[0]),
                        float(p1[1]) - float(p0[1]))
    if length < 10.0:
        raise ValueError("Đường chuẩn của tường quá ngắn (< 10 mm).")
    thickness = float(params.get("thickness_mm", 200.0) or 0.0)
    height = effective_height(building, params, story)
    if thickness <= 0 or height <= 0:
        raise ValueError("Chiều dày và chiều cao của tường phải dương.")
    lo, hi = schemas_side_offsets(params)

    ends = _wall_ends(joins, element, length, lo, hi)
    floors, holes = _wall_openings(building, element, height)

    # The body is built in LOCal w = [0, t]; the frame's w0 places its near
    # face. The two offsets are signed (a wall referenced to one face has
    # its body on one side of the baseline), so the span is their
    # difference — using the thickness alone would ignore flip_side and a
    # face reference entirely.
    span = abs(hi - lo) or thickness
    faces = wall_solid_faces(ends, height, span, floors, holes)

    frame = world_frame((float(p0[0]), float(p0[1]),
                         base_z(building, params, story)),
                        (float(p1[0]) - float(p0[0]),
                         float(p1[1]) - float(p0[1])), w0=min(lo, hi))
    mesh = Mesh()
    for outer, hole_loops in faces:
        mesh.add_face(frame.loop(outer),
                      [frame.loop(h) for h in hole_loops] if hole_loops
                      else None)
    net = _wall_net_area(length, height, floors, holes)
    derived = {
        "effective_height_mm": round(height, 3),
        "length_mm": round(length, 3),
        "gross_area_m2": round(length * height / 1.0e6, 4),
        "net_area_m2": round(net, 4),
        # Concrete volume of the net wall: area in m² × thickness in m.
        "volume_m3": round(net * thickness / 1000.0, 4),
    }
    return mesh, derived


def schemas_side_offsets(params) -> tuple:
    """``(near, far)`` face offsets, SIGNED and in face order.

    Not sorted: ``flip_side`` and a face-referenced baseline both express
    themselves by which offset is which, and a min/max here throws that
    away — the wall would then be built as if it were centred.
    """
    from core.building.planar import side_offsets
    return side_offsets(params)


def _wall_ends(joins, element, length, lo, hi):
    """``{"near": (u0, u1), "far": (u0, u1)}`` — the join solver's verdict."""
    entry = (joins or {}).get(str(element.get("id"))) or {}
    start = entry.get("start") or (0.0, 0.0)
    end = entry.get("end") or (length, length)
    # The solver works on the *baseline*; the two faces stop where the solver
    # says, and taking both faces through the same pair keeps the solid simple
    # (the join already accounts for which face is which).
    return {"near": (float(start[0]), float(end[0])),
            "far": (float(start[1]), float(end[1]))}


def _wall_openings(building, element, wall_height):
    """``(floor_ranges, holes)`` from the openings that live in this wall."""
    floors, holes = [], []
    for child in building.elements:
        if child.get("type") not in schemas.OPENING_TYPES:
            continue
        cparams = child.get("params") or {}
        if str(cparams.get("host_wall_id") or "") != str(element.get("id")):
            continue
        u = float(cparams.get("offset_along_wall_mm", 0.0) or 0.0)
        w = float(cparams.get("width_mm", 0.0) or 0.0)
        v0 = float(cparams.get("sill_height_mm", 0.0) or 0.0)
        v1 = v0 + float(cparams.get("height_mm", 0.0) or 0.0)
        if w <= 1.0 or v1 - v0 <= 1.0:
            continue
        if v1 > wall_height:
            v1 = wall_height
        if v0 <= FLOOR_EPS:
            floors.append((u - w / 2.0, u + w / 2.0, v1))
        else:
            holes.append((u - w / 2.0, u + w / 2.0, v0, v1))
    return floors, holes


def _wall_net_area(length, height, floors, holes) -> float:
    """Elevation area with the openings taken out (m²)."""
    gross = length * height
    cut = 0.0
    for lo, hi, v1 in floors:
        cut += max(0.0, hi - lo) * max(0.0, v1)
    for lo, hi, v0, v1 in holes:
        cut += max(0.0, hi - lo) * max(0.0, v1 - v0)
    return max(0.0, gross - cut) / 1.0e6


# ---- columns and beams ------------------------------------------------------

def build_column(building, element) -> tuple[Mesh, dict]:
    """A column: a rectangular or round prism from its base up."""
    params = element.get("params") or {}
    story = story_of(building, element)
    if story is None:
        raise ValueError("Cột không thuộc tầng nào.")
    center = params.get("center_mm") or (0.0, 0.0)
    height = effective_height(building, params, story)
    z = base_z(building, params, story)
    angle = math.radians(float(params.get("angle_deg", 0.0) or 0.0))
    mesh = Mesh()
    frame = Frame((float(center[0]), float(center[1]), z), (1.0, 0.0, 0.0),
                  (0.0, 1.0, 0.0))
    if params.get("shape") == "round":
        d = float(params.get("diameter_mm", 300.0) or 0.0)
        if d <= 0:
            raise ValueError("Đường kính cột phải dương.")
        r = d / 2.0
        top = [frame.point(r * math.cos(2 * math.pi * i / ROUND_SEGMENTS),
                           r * math.sin(2 * math.pi * i / ROUND_SEGMENTS),
                           height)
               for i in range(ROUND_SEGMENTS)]
        base = [frame.point(r * math.cos(2 * math.pi * i / ROUND_SEGMENTS),
                            r * math.sin(2 * math.pi * i / ROUND_SEGMENTS),
                            0.0)
                for i in range(ROUND_SEGMENTS)]
        mesh.add_face(base)
        mesh.add_face(list(reversed(top)))
        for i in range(ROUND_SEGMENTS):
            j = (i + 1) % ROUND_SEGMENTS
            mesh.add_face([base[i], base[j], top[j], top[i]])
        area = math.pi * r * r
    else:
        w = float(params.get("width_mm", 220.0) or 0.0)
        d = float(params.get("depth_mm", 220.0) or 0.0)
        if w <= 0 or d <= 0:
            raise ValueError("Kích thước cột phải dương.")
        self_frame = Frame((float(center[0]), float(center[1]), z),
                           (math.cos(angle), math.sin(angle), 0.0),
                           (0.0, 0.0, 1.0))
        add_box(mesh, self_frame, -w / 2.0, 0.0, -d / 2.0,
                w / 2.0, height, d / 2.0)
        area = w * d
    derived = {
        "effective_height_mm": round(height, 3),
        "section_area_m2": round(area / 1.0e6, 5),
        "volume_m3": round(area * height / 1.0e9, 4),
    }
    return mesh, derived


def build_beam(building, element) -> tuple[Mesh, dict]:
    """A beam: a prism hanging under its top level, along its axis."""
    params = element.get("params") or {}
    story = story_of(building, element)
    if story is None:
        raise ValueError("Dầm không thuộc tầng nào.")
    p0 = params.get("start_mm")
    p1 = params.get("end_mm")
    if not p0 or not p1:
        raise ValueError("Dầm thiếu trục.")
    length = math.hypot(float(p1[0]) - float(p0[0]),
                        float(p1[1]) - float(p0[1]))
    if length < 10.0:
        raise ValueError("Dầm quá ngắn (< 10 mm).")
    w = float(params.get("width_mm", 220.0) or 0.0)
    d = float(params.get("depth_mm", 300.0) or 0.0)
    if w <= 0 or d <= 0:
        raise ValueError("Kích thước dầm phải dương.")
    height = effective_height(building, params, story)
    top = base_z(building, params, story) + height
    frame = world_frame((float(p0[0]), float(p0[1]), top - d),
                        (float(p1[0]) - float(p0[0]),
                         float(p1[1]) - float(p0[1])), w0=-w / 2.0)
    mesh = Mesh()
    add_box(mesh, frame, 0.0, 0.0, 0.0, length, d, w)
    return mesh, {
        "effective_top_mm": round(top, 3),
        "length_mm": round(length, 3),
        "volume_m3": round(length * w * d / 1.0e9, 4),
    }


# ---- horizontal slabs -------------------------------------------------------

def _rim_between(mesh, top_loop, bottom_loop, flip=False):
    n = len(top_loop)
    for i in range(n):
        j = (i + 1) % n
        quad = [top_loop[i], top_loop[j], bottom_loop[j], bottom_loop[i]]
        if flip:
            quad = list(reversed(quad))
        mesh.add_face(quad)


def build_slab(building, element) -> tuple[Mesh, dict]:
    """A floor slab: its outline extruded downward from the level."""
    params = element.get("params") or {}
    story = story_of(building, element)
    if story is None:
        raise ValueError("Sàn không thuộc tầng nào.")
    outline = params.get("outline_mm") or []
    if len(outline) < 3:
        raise ValueError("Sàn thiếu đường bao.")
    holes = params.get("holes_mm") or []
    thickness = float(params.get("thickness_mm", 120.0) or 0.0)
    z = float(story.get("z_mm", 0.0)) + float(
        params.get("top_offset_mm", 0.0) or 0.0)
    # up = +Y and perp = +Z: the outline's own (x, y) is the PLAN and the
    # thickness runs along -Z, which is what makes a slab a floor. Reading
    # it the other way (up = Z) stands the plate on its edge — a picture
    # nobody notices in the numbers, because the quantities come from the
    # outline alone.
    frame = Frame((0.0, 0.0, z), (1.0, 0.0, 0.0), (0.0, 1.0, 0.0),
                  perp=(0.0, 0.0, 1.0))
    mesh = _slab_mesh(frame, outline, holes, thickness, top=True)
    area = _areas(outline, holes)
    return mesh, {
        "area_m2": round(area / 1.0e6, 4),
        "volume_m3": round(area * thickness / 1.0e9, 4),
        "z_mm": round(z, 3),
    }


def build_ceiling(building, element) -> tuple[Mesh, dict]:
    """A ceiling: its outline extruded upward from the ceiling level."""
    params = element.get("params") or {}
    story = story_of(building, element)
    if story is None:
        raise ValueError("Trần không thuộc tầng nào.")
    outline = params.get("outline_mm") or []
    if len(outline) < 3:
        raise ValueError("Trần thiếu đường bao.")
    thickness = float(params.get("thickness_mm", 9.0) or 9.0)
    z = base_z(building, params, story) + float(
        params.get("height_mm", 2900.0) or 2900.0)
    frame = Frame((0.0, 0.0, z), (1.0, 0.0, 0.0), (0.0, 1.0, 0.0),
                  perp=(0.0, 0.0, 1.0))
    cut = params.get("cut_mm") or []
    mesh = _slab_mesh(frame, outline, cut, max(thickness, 1.0), top=False)
    area = _areas(outline, cut)
    return mesh, {
        "area_m2": round(area / 1.0e6, 4),
        "z_mm": round(z, 3),
        "height_mm": round(float(params.get("height_mm", 2900.0)), 3),
    }


def _slab_mesh(frame, outline, holes, thickness, top: bool):
    """A plate: outline extruded by ``thickness``, the holes punched through."""
    mesh = Mesh()
    depth = float(thickness)
    if depth <= 0:
        raise ValueError("Chiều dày phải dương.")
    outer_hi = [frame.point(float(x), float(y), 0.0) for x, y in outline]
    outer_lo = [frame.point(float(x), float(y), depth) for x, y in outline]
    hole_hi = [[frame.point(float(x), float(y), 0.0) for x, y in h]
               for h in (holes or ())]
    hole_lo = [[frame.point(float(x), float(y), depth) for x, y in h]
               for h in (holes or ())]
    if not top:
        outer_hi, outer_lo = outer_lo, outer_hi
        hole_hi, hole_lo = hole_lo, hole_hi
    mesh.add_face(outer_hi, hole_hi or None)
    mesh.add_face(list(reversed(outer_lo)),
                  [list(reversed(h)) for h in hole_lo] or None)
    _rim_between(mesh, outer_hi, outer_lo)
    for hi, lo in zip(hole_hi, hole_lo):
        _rim_between(mesh, lo, hi)
    return mesh


def _areas(outline, holes) -> float:
    from core.building.planar import area
    total = abs(area([(float(p[0]), float(p[1])) for p in outline]))
    for h in holes or ():
        total -= abs(area([(float(p[0]), float(p[1])) for p in h]))
    return max(total, 0.0)


# ---- zones ------------------------------------------------------------------

def build_zone(building, element) -> tuple[None, dict]:
    """A room is area data, not a solid — nothing is drawn into the model."""
    params = element.get("params") or {}
    outer = params.get("outline_mm") or []
    if len(outer) < 3:
        raise ValueError("Phòng thiếu đường bao.")
    return None, {
        "area_m2": round(_areas(outer, params.get("holes_mm") or []) / 1.0e6,
                         3),
    }


def build_grid(building, element) -> tuple[None, dict]:
    """A grid is axis data, not a solid — nothing is drawn into the model.

    But it is NOT a free pass: an axis with no name, or two axes sharing
    one, is an error a reader would catch at the first sheet, so it is
    caught here while the office can still fix the model.
    """
    params = element.get("params") or {}
    axes = list(params.get("axes") or [])
    if not axes:
        raise ValueError("Trục thiếu danh sách trục.")
    names = [str(a.get("name") or "").strip() for a in axes]
    if any(not n for n in names):
        raise ValueError("Có trục chưa đặt tên.")
    if len(set(names)) != len(names):
        raise ValueError("Tên trục bị trùng.")
    for axis in axes:
        if str(axis.get("dir") or "x") not in ("x", "y"):
            raise ValueError("Trục chỉ chạy theo x hoặc y.")
        float(axis.get("offset_mm") or 0.0)
    return None, {
        "axis_count": len(axes),
        "frame_mm": _grid_frame(axes),
    }


def _grid_frame(axes) -> tuple:
    """``(x0, y0, x1, y1)`` of the axes' crossing points, in mm.

    Two families of lines cross; the four extremes of those crossings are
    where the bubbles go, and they are what the grid's own bounding box
    is. A grid with one family only (all vertical) frames as a line,
    widened so a plan still has something to zoom to.
    """
    xs = sorted(float(a.get("offset_mm") or 0.0) for a in axes
                if str(a.get("dir") or "x") == "y")
    ys = sorted(float(a.get("offset_mm") or 0.0) for a in axes
                if str(a.get("dir") or "x") == "x")
    if not xs or not ys:
        return (-1000.0, -1000.0, 1000.0, 1000.0)
    return (xs[0], ys[0], xs[-1], ys[-1])


# ---- dispatch ---------------------------------------------------------------

#: ``type id -> builder``. Types not listed here (door, window, curtain wall,
#: roof, stair, fixture) are built by their own modules and registered into
#: this table at import time.
BUILDERS = {
    "wall": build_wall,
    "column": build_column,
    "beam": build_beam,
    "slab": build_slab,
    "ceiling": build_ceiling,
    "zone": build_zone,
    "grid": build_grid,
}


def build(building, element):
    """Build one element's geometry; returns ``(mesh_or_None, derived)``."""
    kind = str(element.get("type"))
    builder = BUILDERS.get(kind)
    if builder is None:
        builder = _EXTRA_BUILDERS.get(kind)
    if builder is None and not _EXTRAS_LOADED[0]:
        # The opening/roof/stair/fixture builders live apart (extras.py) and
        # register themselves on import; import them once, on first need.
        _EXTRAS_LOADED[0] = True
        from core.building import extras  # noqa: F401
        builder = _EXTRA_BUILDERS.get(kind)
    if builder is None:
        raise ValueError(f"Chưa có bộ dựng hình cho '{kind}'.")
    if kind == "wall":
        story = story_of(building, element)
        if story is None:
            raise ValueError("Tường không thuộc tầng nào.")
        joins = joins_for_story(building, str(story.get("id")))
        return builder(building, element, joins)
    return builder(building, element)


def joins_for_story(building, story_id: str) -> dict:
    """Solve every wall join on one storey (cached on the building object).

    The key FINGERPRINTS the geometry the solver reads — every wall's
    baseline, thickness and material on the storey, plus the storey's own
    elevation. A count of elements is not enough: moving one partner wall
    changes the join at its neighbour without changing any count, and a
    stale trim then reaches the scene, the drawings and the IFC.
    """
    cache = getattr(building, "_joins_cache", None)
    key = (story_id, len(building.elements),
           _joins_fingerprint(building, story_id))
    if cache is not None and cache[0] == key:
        return cache[1]
    from core.building.planar import join_input, join_walls
    story = building.story(story_id)
    inputs = []
    for el in building.on_story(story_id, "wall"):
        params = el.get("params") or {}
        p0, p1 = params.get("baseline_start_mm"), params.get("baseline_end_mm")
        if not p0 or not p1:
            continue
        h = effective_height(building, params, story)
        inputs.append(join_input(str(el["id"]), params, (p0, p1),
                                 float((story or {}).get("z_mm", 0.0)), h))
    result = join_walls(inputs)
    building._joins_cache = (key, result)
    return result


def _joins_fingerprint(building, story_id: str):
    """A hashable digest of what the join solver reads on one storey.

    Everything ``join_input`` reads has to be in here, or the cache serves
    a trim the solver would no longer produce: the baselines, the faces'
    signed offsets (which is where ``reference_line``, ``flip_side`` and
    the thickness land), the priority, and the storey's own z AND the
    wall's effective height, because both ends of the extent the solver
    compares move with them.
    """
    story = building.story(story_id)
    z = float((story or {}).get("z_mm", 0.0))
    parts: list = [("z", z), ("stories", len(building.stories))]
    for el in building.on_story(story_id, "wall"):
        params = el.get("params") or {}
        p0 = tuple(round(float(v), 3) for v in
                   (params.get("baseline_start_mm") or (0.0, 0.0))[:2])
        p1 = tuple(round(float(v), 3) for v in
                   (params.get("baseline_end_mm") or (0.0, 0.0))[:2])
        from core.building.planar import side_offsets
        lo, hi = side_offsets(params)
        parts.append((str(el.get("id")), p0, p1,
                      round(float(lo), 3), round(float(hi), 3),
                      round(effective_height(building, params, story), 3),
                      round(float(params.get("base_offset_mm", 0.0) or 0.0), 3),
                      int(schemas.priority_of(params))))
    return tuple(parts)


#: Builders for the element types whose geometry modules are heavier
#: (openings, roofs, stairs, fixtures). Registered when those modules import.
_EXTRA_BUILDERS: dict = {}


def register_builder(kind: str, builder) -> None:
    """Let an element module add its own builder to the dispatch."""
    _EXTRA_BUILDERS[str(kind)] = builder


#: Whether the optional builders (extras.py) have been imported yet.
_EXTRAS_LOADED = [False]
