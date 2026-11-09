# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Marco Sumari Tellez and IngeTrazo contributors.
"""Object snap — the drawing's own gravity.

A drawing office never types coordinates: it points at what is already
there. This is the small table of things a point can be pulled to — an
element's own end, the middle of a wall, the face the trowel will follow,
an axis of the grid, the crossing where an axis meets a wall — plus the
two locks that make a line straight: ortho (along the axes) and the polar
steps the trade uses.

It is pure geometry over the live building: nothing here draws or edits.
The plan window hands a raw point in and gets back the point the drawing
actually wants, together with which snap claimed it, so the status line
can say «Điểm cuối» and the operator can tell gravity from a slow mouse.
"""
from __future__ import annotations

import math

#: How close (screen pixels) a raw point must be for a snap to take it.
SNAP_PX = 10.0
#: The polar steps ortho mode is held to, in degrees.
ORTHO_STEP_DEG = 15.0


class Snap:
    """What a raw point was pulled to: ``(x_mm, y_mm, kind, label)``."""

    __slots__ = ("x_mm", "y_mm", "kind", "label")

    def __init__(self, x_mm: float, y_mm: float, kind: str, label: str = ""):
        self.x_mm = float(x_mm)
        self.y_mm = float(y_mm)
        self.kind = str(kind)
        self.label = str(label)

    def __repr__(self) -> str:                      # pragma: no cover
        return f"Snap({self.x_mm:.1f}, {self.y_mm:.1f}, {self.kind})"


#: The snap kinds in the order they win a tie: a real vertex beats the
#: middle of a segment, which beats a line, which beats the grid. The
#: order is the trade's own — you mean the corner when you point at it.
RANK = ("end", "mid", "face", "grid", "ortho")


def candidates(building, story_id: str, *, grid=True) -> list:
    """Every point this drawing can be pulled to, as ``[(x, y, kind, label)]``.

    Built from the MODEL, not from the picture: a snap that followed the
    linework would move when the hidden-line pass changed its mind about
    what is visible, and a wall's own end would stop snapping exactly when
    the view turned edge-on to it.
    """
    out: list = []
    if building is None:
        return out
    for element in building.elements:
        if str(element.get("story_id")) != str(story_id):
            continue
        kind = str(element.get("type"))
        params = element.get("params") or {}
        name = str(params.get("name") or kind)
        a = params.get("baseline_start_mm")
        b = params.get("baseline_end_mm")
        if a and b and len(a) >= 2 and len(b) >= 2:
            ax, ay = float(a[0]), float(a[1])
            bx, by = float(b[0]), float(b[1])
            out.append((ax, ay, "end", name))
            out.append((bx, by, "end", name))
            out.append(((ax + bx) / 2.0, (ay + by) / 2.0, "mid", name))
            if kind == "wall":
                thickness = float(params.get("thickness_mm", 200.0) or 200.0)
                length = math.hypot(bx - ax, by - ay) or 1.0
                # The two FACES run beside the baseline: that is the line
                # the trowel follows and the one a dimension measures to.
                # They are offered as SEGMENTS, so a point anywhere along
                # a wall snaps to its face — not only at the two ends.
                nx, ny = -(by - ay) / length, (bx - ax) / length
                half = thickness / 2.0
                for sign in (1.0, -1.0):
                    out.append((ax + nx * half * sign, ay + ny * half * sign,
                                bx + nx * half * sign, by + ny * half * sign,
                                "face", name))
            continue
        outline = params.get("outline_mm") or []
        for point in outline:
            if len(point) >= 2:
                out.append((float(point[0]), float(point[1]), "end", name))
        if kind == "fixture":
            angle = float(params.get("angle_deg") or 0.0)
            out.append((float(params.get("x_mm") or 0.0),
                        float(params.get("y_mm") or 0.0), "end", name))
            del angle
    if grid:
        from core.building.drawings import grid_axes

        story = building.story(story_id)
        if story is not None:
            for name, direction, offset, lo, hi in grid_axes(building, story):
                # One point per axis end where it stands alone, plus the
                # axis' own middle: an axis is a line, not a point, but
                # these three are where a drafter grabs it.
                if direction == "y":
                    out.append((offset, lo, "grid", str(name)))
                    out.append((offset, hi, "grid", str(name)))
                    out.append((offset, (lo + hi) / 2.0, "grid", str(name)))
                else:
                    out.append((lo, offset, "grid", str(name)))
                    out.append((hi, offset, "grid", str(name)))
                    out.append(((lo + hi) / 2.0, offset, "grid", str(name)))
    return out


def nearest(candidates_list, x_mm: float, y_mm: float,
            radius_mm: float) -> Snap | None:
    """The best candidate within ``radius_mm`` of the point.

    A candidate given as ``(x1, y1, x2, y2, kind, label)`` is a SEGMENT
    rather than a point (a wall's face): the nearest point ON it answers,
    which is what makes a house line dimensionable along its whole length
    instead of only at its two ends.
    """
    best = None
    best_key = None
    for row in candidates_list:
        if len(row) == 6:
            x1, y1, x2, y2, kind, label = row
            cx, cy = _on_segment(float(x1), float(y1), float(x2), float(y2),
                                 x_mm, y_mm)
        else:
            cx, cy, kind, label = row
        d = math.hypot(cx - x_mm, cy - y_mm)
        if d > radius_mm:
            continue
        rank = RANK.index(kind) if kind in RANK else len(RANK)
        key = (rank, d)
        if best_key is None or key < best_key:
            best_key = key
            best = Snap(cx, cy, kind, label)
    return best


def _on_segment(x1: float, y1: float, x2: float, y2: float,
                x_mm: float, y_mm: float) -> tuple:
    """The point of the segment closest to ``(x_mm, y_mm)``."""
    dx, dy = x2 - x1, y2 - y1
    length2 = dx * dx + dy * dy
    if length2 < 1e-12:
        return x1, y1
    t = ((x_mm - x1) * dx + (y_mm - y1) * dy) / length2
    t = max(0.0, min(1.0, t))
    return x1 + dx * t, y1 + dy * t


def apply_ortho(from_point, x_mm: float, y_mm: float,
                step_deg: float = ORTHO_STEP_DEG) -> Snap:
    """Pull a point onto the nearest polar ray from ``from_point``.

    Plain ortho (0°/90°) is the step of 90; the 15° steps are what makes a
    45° run and a 60° brace land exactly, including on a freely-drawn plan
    where nothing else is square.
    """
    fx, fy = float(from_point[0]), float(from_point[1])
    dx, dy = float(x_mm) - fx, float(y_mm) - fy
    length = math.hypot(dx, dy)
    if length < 1e-9:
        return Snap(x_mm, y_mm, "ortho")
    angle = math.degrees(math.atan2(dy, dx))
    step = 90.0 if abs(step_deg - 90.0) < 1e-9 else float(step_deg)
    snapped = round(angle / step) * step
    rad = math.radians(snapped)
    return Snap(fx + math.cos(rad) * length, fy + math.sin(rad) * length,
                "ortho", f"{snapped % 360:.0f}°")


def resolve(building, story_id: str, x_mm: float, y_mm: float, *,
            radius_mm: float, from_point=None, ortho: bool = False,
            candidates_list=None) -> Snap:
    """The point the drawing wants for a raw ``(x_mm, y_mm)``.

    Object snap wins over ortho: a drafter who points at a corner means the
    corner, and pulling that point onto a ray would move it off the thing
    they aimed at. Ortho only governs the points that are not on anything.
    """
    pool = candidates_list
    if pool is None:
        pool = candidates(building, story_id)
    found = nearest(pool, x_mm, y_mm, radius_mm)
    if found is not None:
        return found
    if ortho and from_point is not None:
        return apply_ortho(from_point, x_mm, y_mm)
    return Snap(x_mm, y_mm, "none")


def label_for(snap: Snap | None) -> str:
    """What the status line says about a snap."""
    from core.i18n import tr

    if snap is None:
        return ""
    kinds = {
        "end": tr("Điểm cuối"),
        "mid": tr("Điểm giữa"),
        "face": tr("Mặt tường"),
        "grid": tr("Trục"),
        "ortho": tr("Thẳng hướng"),
        "none": "",
    }
    text = kinds.get(snap.kind, "")
    if snap.kind == "grid" and snap.label:
        return f"{text} {snap.label}"
    if snap.label and snap.kind in ("end", "mid", "face"):
        return f"{text} · {snap.label}"
    return text
