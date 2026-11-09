# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Marco Sumari Tellez and IngeTrazo contributors.
"""Element builders that need the host's frame — openings, roofs, stairs,
fixtures.

The core builders (wall, column, beam, slab, ceiling, zone) stand alone:
their parameters are all the geometry needs. The elements here do not:

* A **door or window** lives in a wall. Its position is "u along the host's
  baseline", so its body is built in the *host wall's* frame — the same frame
  that cut the hole. Building it from its own coordinates would let the leaf
  drift out of its opening the moment the wall is edited, which is exactly
  what a parametric opening must never do.
* A **curtain wall** is the same idea with a grid of glazed cells.
* A **roof** and a **stair** are self-contained but need the storey's height
  (a roof plate is lifted to its pivot; a stair rises to the floor above).
* A **fixture** is a small body at a point.

Everything here registers itself into ``core.building.builder`` on import, so
:func:`core.building.builder.build` finds them without a second dispatch
table.
"""
from __future__ import annotations

import math

from core.building.builder import (base_z, effective_height, register_builder,
                                   story_of, story_above)
from core.building.geometry import Frame, add_box, world_frame
from core.mesh import Mesh

__all__ = ["register_all"]

#: Where a door leaf sits inside the wall thickness when no depth is given.
DEFAULT_LEAF_GAP = 3.0


# ---- shared -----------------------------------------------------------------

def _host_frame(building, opening):
    """The host wall's frame, exactly as the wall builder computed it.

    The opening's own parameters are in *wall-local* coordinates (u along the
    baseline, v up, w across the thickness), so this is the only frame that
    can place them correctly, and it must match the one that cut the hole.
    """
    from core.building import builder as core_builder
    from core.building import planar
    params = opening.get("params") or {}
    host_id = str(params.get("host_wall_id") or "")
    host = building.element(host_id) if host_id else None
    if host is None:
        raise ValueError("Lỗ mở không có tường chủ.")
    hparams = host.get("params") or {}
    p0 = hparams.get("baseline_start_mm")
    p1 = hparams.get("baseline_end_mm")
    if not p0 or not p1:
        raise ValueError("Tường chủ thiếu đường chuẩn.")
    story = story_of(building, host)
    length = math.hypot(float(p1[0]) - float(p0[0]),
                        float(p1[1]) - float(p0[1]))
    lo, hi = planar.side_offsets(hparams)
    joins = None
    if story is not None:
        joins = core_builder.joins_for_story(building, str(story["id"]))
    entry = (joins or {}).get(host_id) or {}
    start = entry.get("start") or (0.0, 0.0)
    end = entry.get("end") or (length, length)
    frame = world_frame((float(p0[0]), float(p0[1]),
                         base_z(building, hparams, story)),
                        (float(p1[0]) - float(p0[0]),
                         float(p1[1]) - float(p0[1])), w0=min(lo, hi))
    height = effective_height(building, hparams, story)
    del start, end
    return frame, float(hparams.get("thickness_mm", 200.0) or 200.0), height


def _frame_place(params, thickness: float) -> tuple:
    """``(w_start, depth)`` of the frame inside the wall thickness.

    ``frame_position`` is the trade's three placements: centred, hard against
    the outside face, or against the inside face.
    """
    depth = params.get("frame_depth_mm")
    position = str(params.get("frame_position") or "center")
    if depth is None:
        depth = (min(100.0, thickness)
                 if position in ("outer", "inner") else thickness)
    depth = max(0.0, min(float(depth), thickness))
    if position == "outer":
        w0 = 0.0
    elif position == "inner":
        w0 = thickness - depth
    else:
        w0 = (thickness - depth) / 2.0
    return w0, depth


def _bar(mesh, frame, u0, v0, w0, u1, v1, w1):
    add_box(mesh, frame, u0, v0, w0, u1, v1, w1)


# ---- doors and windows ------------------------------------------------------

def build_opening(building, element) -> tuple[Mesh, dict]:
    """A door or window body: frame bars, leaf, in the host wall's frame."""
    params = element.get("params") or {}
    frame, thickness, wall_height = _host_frame(building, element)
    width = float(params.get("width_mm", 900.0) or 0.0)
    height = float(params.get("height_mm", 2200.0) or 0.0)
    sill = float(params.get("sill_height_mm", 0.0) or 0.0)
    fw = float(params.get("frame_width_mm", 40.0) or 0.0)
    lt = float(params.get("leaf_thickness_mm", 40.0) or 0.0)
    if width <= 0 or height <= 0:
        raise ValueError("Kích thước cửa phải dương.")
    if lt <= 0:
        raise ValueError("Chiều dày cánh phải dương.")
    if sill + height > wall_height + 1.0:
        height = max(wall_height - sill, 1.0)

    u = float(params.get("offset_along_wall_mm", 0.0) or 0.0)
    u0, u1 = u - width / 2.0, u + width / 2.0
    v0, v1 = sill, sill + height
    w0, depth = _frame_place(params, thickness)
    w1 = w0 + depth

    mesh = Mesh()
    floor_level = v0 <= 0.5
    if fw > 0:
        # Jambs, head and (only off the floor) the sill: the reveals the wall
        # builder left open are closed by these.
        _bar(mesh, frame, u0, v0, w0, u0 + fw, v1, w1)
        _bar(mesh, frame, u1 - fw, v0, w0, u1, v1, w1)
        _bar(mesh, frame, u0 + fw, v1 - fw, w0, u1 - fw, v1, w1)
        if not floor_level:
            _bar(mesh, frame, u0 + fw, v0, w0, u1 - fw, v0 + fw, w1)

    # The leaf: a door hangs from its handing and opens by its angle; a
    # window is a glazed panel fixed in the frame.
    gap = max(fw * 0.15, DEFAULT_LEAF_GAP)
    handing = str(params.get("handing") or "left")
    lu0 = u0 + (fw if handing == "left" else 0.0) + gap
    lu1 = u1 - (fw if handing == "right" else 0.0) - gap
    lv0 = v0 if floor_level else v0 + fw + gap
    lv1 = v1 - fw - gap
    if lu1 - lu0 < 1.0 or lv1 - lv0 < 1.0:
        raise ValueError("Kích thước cửa quá nhỏ so với khuôn.")
    lw0 = w0 + (depth - lt) / 2.0
    _bar(mesh, frame, lu0, lv0, lw0, lu1, lv1, lw0 + lt)

    derived = {
        "width_mm": round(width, 3),
        "height_mm": round(height, 3),
        "sill_height_mm": round(sill, 3),
        "area_m2": round(width * height / 1.0e6, 4),
        "leaf_area_m2": round(max(lu1 - lu0, 0.0) * max(lv1 - lv0, 0.0)
                              / 1.0e6, 4),
    }
    return mesh, derived


def build_door(building, element):
    return build_opening(building, element)


def build_window(building, element):
    return build_opening(building, element)


def build_curtain_wall(building, element) -> tuple[Mesh, dict]:
    """A glazed run in a grid: border bars plus a pane per cell."""
    params = element.get("params") or {}
    frame, thickness, wall_height = _host_frame(building, element)
    width = float(params.get("width_mm", 2400.0) or 0.0)
    height = float(params.get("height_mm", 2700.0) or 0.0)
    sill = float(params.get("sill_height_mm", 0.0) or 0.0)
    fw = max(float(params.get("frame_width_mm", 50.0) or 0.0), 0.0)
    lt = float(params.get("leaf_thickness_mm", 10.0) or 10.0)
    cols = max(int(params.get("col_count", 3) or 1), 1)
    rows = max(int(params.get("row_count", 2) or 1), 1)
    if width <= 0 or height <= 0:
        raise ValueError("Kích thước vách kính phải dương.")
    u = float(params.get("offset_along_wall_mm", 0.0) or 0.0)
    u0, u1 = u - width / 2.0, u + width / 2.0
    v0, v1 = sill, min(sill + height, wall_height)
    w0, depth = _frame_place(params, thickness)
    w1 = w0 + depth
    fw = min(fw, min(width, height) / 4.0)

    mesh = Mesh()
    _bar(mesh, frame, u0, v0, w0, u0 + fw, v1, w1)          # left
    _bar(mesh, frame, u1 - fw, v0, w0, u1, v1, w1)          # right
    _bar(mesh, frame, u0 + fw, v1 - fw, w0, u1 - fw, v1, w1)  # head
    if v0 > 0.5:
        _bar(mesh, frame, u0 + fw, v0, w0, u1 - fw, v0 + fw, w1)  # sill

    step_u = (width - 2 * fw) / cols
    step_v = (v1 - v0 - 2 * fw) / rows
    for c in range(1, cols):
        cu = u0 + fw + step_u * c
        _bar(mesh, frame, cu - fw / 2.0, v0 + fw, w0, cu + fw / 2.0, v1 - fw,
             w1)
    for r in range(1, rows):
        cv = v0 + fw + step_v * r
        _bar(mesh, frame, u0 + fw, cv - fw / 2.0, w0, u1 - fw, cv + fw / 2.0,
             w1)
    # One glazed pane per cell, centred in the frame's depth.
    pw = w0 + (depth - lt) / 2.0
    for c in range(cols):
        for r in range(rows):
            cu0 = u0 + fw + step_u * c
            cu1 = cu0 + step_u
            cv0 = v0 + fw + step_v * r
            cv1 = cv0 + step_v
            inset_u = min(fw / 2.0, (cu1 - cu0) / 2.0)
            inset_v = min(fw / 2.0, (cv1 - cv0) / 2.0)
            _bar(mesh, frame, cu0 + inset_u, cv0 + inset_v, pw,
                 cu1 - inset_u, cv1 - inset_v, pw + lt)

    glass = max(0.0, (width - 2 * fw)) * max(0.0, (v1 - v0 - 2 * fw))
    return mesh, {
        "width_mm": round(width, 3),
        "height_mm": round(v1 - v0, 3),
        "cells": cols * rows,
        "area_m2": round(width * (v1 - v0) / 1.0e6, 4),
        "glass_area_m2": round(glass / 1.0e6, 4),
    }


# ---- roofs ------------------------------------------------------------------

def build_roof(building, element) -> tuple[Mesh, dict]:
    """A roof plate over its outline, lifted to the pivot and tilted.

    A roof drawn on the top storey sits at the storey level (there is no
    storey above to link to); anywhere else the plate is lifted by the
    element's height, which is what makes "mái" land on top of the walls.
    """
    params = element.get("params") or {}
    story = story_of(building, element)
    if story is None:
        raise ValueError("Mái không thuộc tầng nào.")
    from core.building import planar
    outline = planar.clean_polygon(params.get("outline_mm") or [])
    if len(outline) < 3:
        raise ValueError("Mái thiếu đường bao.")
    if not _is_convex(outline):
        raise ValueError("Mái chỉ hỗ trợ đường bao LỒI (chia mái chữ L "
                         "thành nhiều mái).")
    thickness = max(float(params.get("thickness_mm", 150.0) or 150.0), 1.0)
    slope = float(params.get("slope_deg", 30.0) or 0.0)
    slope = max(0.0, min(slope, 89.0))
    overhang = float(params.get("overhang_mm", 500.0) or 0.0)

    above = story_above(building, story)
    if params.get("top_link") == "next" and above is None:
        pivot = float(story.get("z_mm", 0.0)) + float(
            params.get("base_offset_mm", 0.0) or 0.0)
    else:
        pivot = base_z(building, params, story) + effective_height(
            building, params, story)

    plan = _offset_out(outline, overhang) if overhang > 0 else outline
    lowest = 0
    for i, p in enumerate(plan):
        if p[1] < plan[lowest][1] or (p[1] == plan[lowest][1]
                                      and p[0] < plan[lowest][0]):
            lowest = i
    tan_s = math.tan(math.radians(slope))
    # The eave edge stays at the pivot; the plate rises with the distance
    # measured away from that edge (the classic single-slope build).
    edge_a = plan[lowest]
    edge_b = plan[(lowest + 1) % len(plan)]
    ex, ey = edge_b[0] - edge_a[0], edge_b[1] - edge_a[1]
    elen = math.hypot(ex, ey) or 1.0
    nx, ny = -ey / elen, ex / elen                 # normal to the eave edge
    cx = sum(p[0] for p in plan) / len(plan)
    cy = sum(p[1] for p in plan) / len(plan)
    if (cx - edge_a[0]) * nx + (cy - edge_a[1]) * ny < 0:
        nx, ny = -nx, -ny                          # point into the plate

    def lift(p):
        d = (p[0] - edge_a[0]) * nx + (p[1] - edge_a[1]) * ny
        return max(d, 0.0) * tan_s

    mesh = Mesh()
    frame = Frame((0.0, 0.0, pivot), (1.0, 0.0, 0.0), (0.0, 0.0, 1.0),
                  perp=(0.0, 1.0, 0.0))
    top = [frame.point(p[0], p[1], lift(p)) for p in plan]
    bottom = [frame.point(p[0], p[1], lift(p) - thickness) for p in plan]
    mesh.add_face(top)
    mesh.add_face(list(reversed(bottom)))
    for i in range(len(plan)):
        j = (i + 1) % len(plan)
        mesh.add_face([top[i], top[j], bottom[j], bottom[i]])
    area = planar.area_m2(plan)
    slope_factor = 1.0 / max(math.cos(math.radians(slope)), 1e-6)
    return mesh, {
        "area_m2": round(area, 4),
        "slope_area_m2": round(area * slope_factor, 4),
        "volume_m3": round(area * thickness * slope_factor / 1000.0, 4),
        "pivot_mm": round(pivot, 3),
        "eave_edges": len(plan),
    }


def _is_convex(points) -> bool:
    n = len(points)
    sign = 0
    for i in range(n):
        a, b, c = points[i], points[(i + 1) % n], points[(i + 2) % n]
        cross = ((b[0] - a[0]) * (c[1] - b[1])
                 - (b[1] - a[1]) * (c[0] - b[0]))
        if abs(cross) < 1e-9:
            continue
        s = 1 if cross > 0 else -1
        if sign and s != sign:
            return False
        sign = s
    return True


def _offset_out(points, distance: float):
    """Offset a convex outline outward by ``distance`` (the eave overhang)."""
    cx = sum(p[0] for p in points) / len(points)
    cy = sum(p[1] for p in points) / len(points)
    out = []
    for x, y in points:
        dx, dy = x - cx, y - cy
        n = math.hypot(dx, dy)
        if n < 1e-9:
            out.append((x, y))
            continue
        out.append((x + dx / n * distance, y + dy / n * distance))
    return out


# ---- stairs -----------------------------------------------------------------

def build_stair(building, element) -> tuple[Mesh, dict]:
    """A stair: one box per tread rising to the storey above, plus the waist.

    The treads follow the centre line (``path_mm``), so a straight, an L or a
    U stair is the same builder — the landings are simply the segments whose
    length is not a multiple of the tread, drawn as one plate.
    """
    params = element.get("params") or {}
    story = story_of(building, element)
    if story is None:
        raise ValueError("Cầu thang không thuộc tầng nào.")
    path = params.get("path_mm") or []
    if len(path) < 2:
        raise ValueError("Cầu thang thiếu đường tim.")
    width = float(params.get("width_mm", 1000.0) or 0.0)
    tread = float(params.get("tread_mm", 260.0) or 0.0)
    waist = float(params.get("waist_mm", 150.0) or 0.0)
    if width <= 0 or tread <= 0:
        raise ValueError("Kích thước cầu thang phải dương.")
    z0 = float(story.get("z_mm", 0.0))
    above = story_above(building, story)
    story_h = ((float(above.get("z_mm", 0.0)) - z0) if above is not None
               else float(story.get("height_mm", 3300.0)))

    steps = []
    for i in range(len(path) - 1):
        a = (float(path[i][0]), float(path[i][1]))
        b = (float(path[i + 1][0]), float(path[i + 1][1]))
        seg = math.hypot(b[0] - a[0], b[1] - a[1])
        if seg < 1.0:
            continue
        n = max(int(round(seg / tread)), 1)
        for k in range(n):
            t0, t1 = k / n, (k + 1) / n
            steps.append(((a[0] + (b[0] - a[0]) * t0,
                           a[1] + (b[1] - a[1]) * t0),
                          (a[0] + (b[0] - a[0]) * t1,
                           a[1] + (b[1] - a[1]) * t1)))
    if not steps:
        raise ValueError("Cầu thang quá ngắn.")
    riser = story_h / (len(steps) + 1)

    mesh = Mesh()
    for index, (sa, sb) in enumerate(steps):
        level = z0 + riser * (index + 1)
        frame = world_frame((sa[0], sa[1], level - max(waist, 1.0)),
                            (sb[0] - sa[0], sb[1] - sa[1]), w0=-width / 2.0)
        seg = math.hypot(sb[0] - sa[0], sb[1] - sa[1])
        add_box(mesh, frame, 0.0, 0.0, 0.0, seg, max(waist, 1.0), width)
    warn = None
    if not (150.0 <= riser <= 190.0):
        warn = f"Chiều cao bậc {riser:.0f} mm ngoài 150 - 190"
    return mesh, {
        "treads": len(steps),
        "riser_mm": round(riser, 1),
        "width_mm": round(width, 3),
        "warn": warn,
        "slope_length_mm": round(sum(
            math.hypot(sb[0] - sa[0], sb[1] - sa[1]) for sa, sb in steps), 1),
    }


# ---- fixtures ---------------------------------------------------------------

def build_fixture(building, element) -> tuple[Mesh, dict]:
    """A sanitary fixture: its bounding body at the centre, turned by its
    angle. The catalogue's sizes come from the element's own parameters."""
    params = element.get("params") or {}
    story = story_of(building, element)
    if story is None:
        raise ValueError("Thiết bị không thuộc tầng nào.")
    center = params.get("center_mm") or (0.0, 0.0)
    width = float(params.get("width_mm", 500.0) or 0.0)
    depth = float(params.get("depth_mm", 700.0) or 0.0)
    height = float(params.get("height_mm", 500.0) or 0.0)
    z = float(params.get("z_mm", 0.0) or 0.0)
    if width <= 0 or depth <= 0 or height <= 0:
        raise ValueError("Kích thước thiết bị phải dương.")
    angle = math.radians(float(params.get("angle_deg", 0.0) or 0.0))
    base = float(story.get("z_mm", 0.0)) + z
    frame = Frame((float(center[0]), float(center[1]), base),
                  (math.cos(angle), math.sin(angle), 0.0),
                  (0.0, 0.0, 1.0))
    mesh = Mesh()
    add_box(mesh, frame, -width / 2.0, 0.0, -depth / 2.0,
            width / 2.0, height, depth / 2.0)
    return mesh, {
        "width_mm": round(width, 3),
        "depth_mm": round(depth, 3),
        "height_mm": round(height, 3),
        "volume_m3": round(width * depth * height / 1.0e9, 4),
    }


def register_all() -> None:
    """Register every builder here into the shared dispatch."""
    register_builder("door", build_door)
    register_builder("window", build_window)
    register_builder("curtain_wall", build_curtain_wall)
    register_builder("roof", build_roof)
    register_builder("stair", build_stair)
    register_builder("fixture", build_fixture)


register_all()
