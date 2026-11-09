# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Marco Sumari Tellez and IngeTrazo contributors.
"""The BIM tools — walls, columns, slabs, rooms and their kin.

These are the tools the Design menu and the plan window's vertical bar offer.
They all follow one pattern, which is what makes them feel like the drawing
tools beside them: click to start, click (or type a number) to finish, Esc to
abandon. What they *make* is a **parametric element**: the click gives a
baseline, a rectangle's two corners or a centre point, and the element records
that plus its default parameters — never the solid. The solid is built from
those parameters by :mod:`core.building.scene_sync`, which is why changing a
wall's thickness later moves its drawings and its quantities with it.

The three interaction shapes cover every tool in the catalogue:

* :class:`BaselineTool` — two clicks give a segment (walls, beams).
* :class:`AreaTool` — two clicks give a rectangle (slabs, ceilings, roofs) or
  a **pick** gives the room around the cursor (zones).
* :class:`PointTool` — one click gives a position (columns, fixtures).
"""
from __future__ import annotations

import math

from PySide6.QtCore import Qt
from PySide6.QtGui import QVector3D

from core.building import commands as bim_commands
from core.building import elements as schemas
from core.building import model as building_model
from core.building import planar
from core.building.scene_sync import sync
from core.i18n import tr
from tools.base import Tool, ToolContext


# ---- shared behaviour -------------------------------------------------------

class BuildingTool(Tool):
    """Common plumbing: the active storey, and committing through history."""

    #: The element type this tool creates.
    kind = ""

    def _reset(self) -> None:
        """Drop whatever the in-progress operation had gathered."""

    def on_activate(self, viewport) -> None:
        self._reset()
        self._ensure_story(viewport)

    def on_deactivate(self, viewport) -> None:
        self._reset()

    def on_cancel(self, viewport) -> None:
        self._reset()
        viewport.update()

    # ---- helpers ---------------------------------------------------------
    def _scene(self, viewport):
        return viewport.scene

    def _building(self, viewport):
        return building_model.building_of(self._scene(viewport))

    def _ensure_story(self, viewport):
        """A storey must exist before any element can be placed on it.

        The first BIM element in an empty document creates the ground storey,
        so the user is never stuck with a tool that refuses to work for a
        reason they cannot see.
        """
        building = self._building(viewport)
        if not building.stories:
            history = getattr(viewport, "history", None)
            cmd = bim_commands.add_story(tr("Tầng 1"), 0.0, 3300.0)
            if history is not None:
                history.execute(cmd)
            else:                      # no history (tests): apply directly
                cmd.do(self._scene(viewport))
        return self._building(viewport)

    def _commit(self, viewport, command) -> None:
        """Run a building command and refresh the geometry it changed."""
        history = getattr(viewport, "history", None)
        if history is not None:
            history.execute(command)
        else:
            command.do(self._scene(viewport))
        sync(self._scene(viewport), self._building(viewport))
        notify = getattr(viewport, "notify_scene_changed", None)
        if callable(notify):
            notify()
        else:
            viewport.update()

    def _ground_z(self, viewport) -> float:
        """The active storey's elevation in scene units (metres)."""
        building = self._building(viewport)
        story = building.active_story()
        return float((story or {}).get("z_mm", 0.0)) / 1000.0

    def _params(self, viewport) -> dict:
        return schemas.defaults_for(self.kind)

    def _next_name(self, viewport) -> str:
        building = self._building(viewport)
        return str(len(building.of_type(self.kind)) + 1)


class BaselineTool(BuildingTool):
    """Two clicks along the ground plane: the element's baseline."""

    vcb_label = "Length"

    def __init__(self) -> None:
        self.start = None
        self.end = None

    def _reset(self) -> None:
        self.start = None
        self.end = None

    def on_click(self, ctx: ToolContext) -> None:
        if self.start is None:
            self.start = ctx.world
            return
        self.end = ctx.world
        self._finish(ctx.viewport)

    def on_hover(self, ctx: ToolContext) -> None:
        if self.start is not None:
            self.end = ctx.world
            ctx.viewport.update()

    def on_value(self, viewport, value: float) -> bool:
        """A typed length finishes the segment along the current direction."""
        if self.start is None or self.end is None:
            return False
        direction = QVector3D(self.end) - QVector3D(self.start)
        if direction.length() < 1e-9:
            return False
        direction.normalize()
        self.end = QVector3D(self.start) + direction * float(value)
        self._finish(viewport)
        return True

    def drag_plane(self, viewport):
        z = self._ground_z(viewport)
        return (QVector3D(0.0, 0.0, z), QVector3D(0.0, 0.0, 1.0))

    def rubber_band_lines(self):
        if self.start is None or self.end is None:
            return []
        return [(self.start, self.end)]

    def _finish(self, viewport) -> None:
        if self.start is None or self.end is None:
            return
        p0 = _mm2(self.start)
        p1 = _mm2(self.end)
        if math.hypot(p1[0] - p0[0], p1[1] - p0[1]) < 10.0:
            self._reset()
            return
        building = self._ensure_story(viewport)
        story = building.active_story() or _first_story(building)
        params = self._params(viewport)
        params.update(self.baseline_params(p0, p1))
        params.setdefault("name", self._next_name(viewport))
        command = bim_commands.add_element(self.kind, str(story["id"]), params)
        self._reset()
        self._commit(viewport, command)

    def baseline_params(self, p0, p1) -> dict:
        return {"baseline_start_mm": [p0[0], p0[1]],
                "baseline_end_mm": [p1[0], p1[1]]}


class WallTool(BaselineTool):
    """Wall: click the start, click the end — chained so a run flows."""

    name = "Wall"
    description = "Draw walls between two points; corners join themselves."
    kind = "wall"

    def _finish(self, viewport) -> None:
        """Chain: the end of one wall starts the next, as Line does."""
        start = self.start
        super()._finish(viewport)
        if start is not None:
            self.start = None

    def on_triple_click(self, ctx: ToolContext) -> None:
        self.on_click(ctx)


class BeamTool(BaselineTool):
    """Beam: a straight axis between two points under the level above."""

    name = "Beam"
    description = "Draw a beam along an axis; it hangs under its top level."
    kind = "beam"

    def baseline_params(self, p0, p1) -> dict:
        return {"start_mm": [p0[0], p0[1]], "end_mm": [p1[0], p1[1]]}


class PointTool(BuildingTool):
    """One click: the element's centre."""

    vcb_label = None

    def __init__(self) -> None:
        self.point = None

    def _reset(self) -> None:
        self.point = None

    def drag_plane(self, viewport):
        z = self._ground_z(viewport)
        return (QVector3D(0.0, 0.0, z), QVector3D(0.0, 0.0, 1.0))

    def on_click(self, ctx: ToolContext) -> None:
        self.point = ctx.world
        p = _mm2(ctx.world)
        building = self._ensure_story(ctx.viewport)
        story = building.active_story() or _first_story(building)
        params = self._params(ctx.viewport)
        params.update(self.point_params(p))
        params.setdefault("name", self._next_name(ctx.viewport))
        command = bim_commands.add_element(self.kind, str(story["id"]),
                                           params)
        self._reset()
        self._commit(ctx.viewport, command)

    def point_params(self, point) -> dict:
        return {"center_mm": [point[0], point[1]]}


class ColumnTool(PointTool):
    """Column: one click on its centre."""

    name = "Column"
    description = "Place a column; its top can follow the storey above."
    kind = "column"


class FixtureTool(PointTool):
    """Sanitary fixture: one click where its centre sits."""

    name = "Fixture"
    description = "Place a sanitary fixture from the catalogue."
    kind = "fixture"


class AreaTool(BuildingTool):
    """A rectangle dragged across the plane, or a room picked from its walls."""

    vcb_label = "Area"

    def __init__(self) -> None:
        self.corner = None
        self.other = None
        self.picking = False

    def _reset(self) -> None:
        self.corner = None
        self.other = None
        self.picking = False

    def on_activate(self, viewport) -> None:
        super().on_activate(viewport)
        # ''Pick a room'' is how zones and slabs-in-a-room are drawn: the pick
        # point is what the boundary detection needs, so the first click
        # resolves a region instead of anchoring a rectangle.
        self.picking = bool(getattr(self, "pick_first", False))

    def drag_plane(self, viewport):
        z = self._ground_z(viewport)
        return (QVector3D(0.0, 0.0, z), QVector3D(0.0, 0.0, 1.0))

    def on_click(self, ctx: ToolContext) -> None:
        if self.picking:
            self._pick_region(ctx)
            return
        if self.corner is None:
            self.corner = ctx.world
            return
        self.other = ctx.world
        self._finish_rect(ctx.viewport)

    def on_hover(self, ctx: ToolContext) -> None:
        if self.corner is not None:
            self.other = ctx.world
            ctx.viewport.update()

    def rubber_band_lines(self):
        if self.corner is None or self.other is None:
            return []
        a, b = self.corner, self.other
        c = QVector3D(b.x(), a.y(), b.z())
        d = QVector3D(a.x(), b.y(), b.z())
        return [(a, c), (c, b), (b, d), (d, a)]

    def _pick_region(self, ctx: ToolContext) -> None:
        """Detect the room the cursor is in from the walls already drawn."""
        building = self._building(ctx.viewport)
        footprints = _story_footprints(building)
        point = _mm2(ctx.world)
        region = planar.detect_region(footprints, point)
        if region is None:
            self.refresh_hint(ctx.viewport)
            return
        story = building.active_story() or _first_story(building)
        params = self._params(ctx.viewport)
        params["outline_mm"] = [[p[0], p[1]] for p in region["outer"]]
        params["holes_mm"] = [[[p[0], p[1]] for p in h]
                              for h in region["holes"]]
        params["pick_mm"] = [point[0], point[1]]
        params.setdefault("name", self._next_name(ctx.viewport))
        command = bim_commands.add_element(self.kind, str(story["id"]),
                                           params)
        self._reset()
        self._commit(ctx.viewport, command)

    def _finish_rect(self, viewport) -> None:
        a, b = _mm2(self.corner), _mm2(self.other)
        x0, x1 = sorted((a[0], b[0]))
        y0, y1 = sorted((a[1], b[1]))
        if x1 - x0 < 10.0 or y1 - y0 < 10.0:
            self._reset()
            return
        building = self._ensure_story(viewport)
        story = building.active_story() or _first_story(building)
        params = self._params(viewport)
        params.update(self.area_params([(x0, y0), (x1, y0), (x1, y1),
                                        (x0, y1)]))
        params.setdefault("name", self._next_name(viewport))
        command = bim_commands.add_element(self.kind, str(story["id"]),
                                           params)
        self._reset()
        self._commit(viewport, command)

    def area_params(self, outline) -> dict:
        return {"outline_mm": [[p[0], p[1]] for p in outline]}


class SlabTool(AreaTool):
    """Slab: drag a rectangle, or pick the room it should fill."""

    name = "Slab"
    description = "Draw a floor slab over a rectangle or a room."
    kind = "slab"
    pick_first = False

    def on_key(self, viewport, key, modifiers) -> bool:
        """Ctrl turns the next click into a room pick — the same idiom the
        circle and arc tools use to reach their other mode."""
        if key == Qt.Key_Control:
            self.picking = not self.picking
            self.refresh_hint(viewport)
            return True
        return False

    def status_clause(self) -> str:
        return tr("Ctrl = pick the room's boundary") if not self.picking else \
            tr("Ctrl = draw a rectangle")


class CeilingTool(AreaTool):
    """Ceiling: a rectangle above the storey floor, or a room's own ceiling."""

    name = "Ceiling"
    description = "Draw a ceiling plane over a rectangle or a room."
    kind = "ceiling"


class RoofTool(AreaTool):
    """Roof: a rectangle (or room) to slope a roof plate over."""

    name = "Roof"
    description = "Draw a roof plate; it slopes from its lowest edge."
    kind = "roof"


class ZoneTool(AreaTool):
    """Room / zone: **one click** and the room around the cursor is found."""

    name = "Zone"
    description = "Click inside a room: its boundary and area are detected."
    kind = "zone"
    pick_first = True


class CurtainWallTool(BaselineTool):
    """Curtain wall: a glazed run between two points."""

    name = "Curtain wall"
    description = "Draw a glazed curtain wall along a line."
    kind = "curtain_wall"

    def _finish(self, viewport) -> None:
        """A curtain wall is a child of a carrier wall: make both."""
        if self.start is None or self.end is None:
            return
        p0, p1 = _mm2(self.start), _mm2(self.end)
        length = math.hypot(p1[0] - p0[0], p1[1] - p0[1])
        if length < 300.0:
            self._reset()
            return
        building = self._ensure_story(viewport)
        story = building.active_story() or _first_story(building)
        from core.building.model import new_id
        wall_id = new_id("wall")
        carrier_params = schemas.defaults_for("wall")
        cw = self._params(viewport)
        carrier_params.update({
            "baseline_start_mm": [p0[0], p0[1]],
            "baseline_end_mm": [p1[0], p1[1]],
            "thickness_mm": max(float(cw.get("frame_depth_mm", 100.0)), 50.0),
            "top_link": "none",
            "name": tr("Vách kính"),
        })
        cw_params = dict(cw)
        cw_params.update({
            "host_wall_id": wall_id,
            "offset_along_wall_mm": length / 2.0,
            "width_mm": length,
            "sill_height_mm": 0.0,
            "height_mm": float(carrier_params.get("height_mm", 3300.0)),
            "name": tr("Vách kính"),
        })

        def mutate(b):
            carrier = b.add_element("wall", str(story["id"]), carrier_params)
            carrier["id"] = wall_id
            b.add_element("curtain_wall", str(story["id"]), cw_params)

        self._reset()
        self._commit(viewport, bim_commands.BuildingEdit(mutate))


class DoorTool(BaselineTool):
    """Opening: click a wall, then the position along it."""

    name = "Door"
    description = "Click a wall, then where the door sits along it."
    kind = "door"
    vcb_label = "Distance"

    def __init__(self) -> None:
        super().__init__()
        self.host = None
        self.wall_p0 = None
        self.wall_p1 = None

    def _reset(self) -> None:
        super()._reset()
        self.host = None
        self.wall_p0 = None
        self.wall_p1 = None

    def on_click(self, ctx: ToolContext) -> None:
        if self.host is None:
            self._grab_wall(ctx)
            return
        # Second click: project onto the wall's baseline for the offset.
        p = _mm2(ctx.world)
        u = _along_baseline(self.wall_p0, self.wall_p1, p)
        self._place(ctx.viewport, u)

    def on_value(self, viewport, value: float) -> bool:
        if self.host is None:
            return False
        self._place(viewport, float(value))
        return True

    def _grab_wall(self, ctx: ToolContext) -> None:
        """Find the wall under the cursor (a click on its solid)."""
        building = self._building(ctx.viewport)
        p = _mm2(ctx.world)
        best = None
        for el in building.of_type("wall"):
            params = el.get("params") or {}
            p0, p1 = params.get("baseline_start_mm"), params.get(
                "baseline_end_mm")
            if not p0 or not p1:
                continue
            lo, hi = planar.side_offsets(params)
            quad = planar.wall_footprint(p0, p1, min(lo, hi), max(lo, hi))
            if planar.point_in_polygon(p, quad):
                # Nearest wall wins when footprints overlap at a corner.
                length = math.hypot(float(p1[0]) - float(p0[0]),
                                    float(p1[1]) - float(p0[1]))
                u = _along_baseline(p0, p1, p)
                d = abs(u - _clamp(u, 0.0, length))
                if best is None or d < best[0]:
                    best = (d, el, p0, p1)
        if best is None:
            return
        self.host, self.wall_p0, self.wall_p1 = (best[1], best[2],
                                               best[3])
        self.start = ctx.world
        self.refresh_hint(ctx.viewport)

    def status_clause(self) -> str:
        if self.host is None:
            return tr("Click a wall")
        return tr("Click where the opening sits, or type the distance")

    def rubber_band_lines(self):
        if self.host is None or self.end is None or self.start is None:
            return []
        return [(self.start, self.end)]

    def _place(self, viewport, u: float) -> None:
        building = self._ensure_story(viewport)
        host = building.element(str(self.host["id"]))
        if host is None:
            self._reset()
            return
        story_id = str(host.get("story_id") or
                       (building.active_story() or {}).get("id"))
        params = self._params(viewport)
        params["host_wall_id"] = str(self.host["id"])
        params["offset_along_wall_mm"] = round(float(u), 1)
        params.setdefault("name", self._next_name(viewport))
        command = bim_commands.add_element(self.kind, story_id, params)
        self._reset()
        self._commit(viewport, command)


class WindowTool(DoorTool):
    """Window: the same click-a-wall flow, with window defaults."""

    name = "Window"
    description = "Click a wall, then where the window sits along it."
    kind = "window"


# ---- helpers ----------------------------------------------------------------

def _first_story(building):
    """The storey a tool falls back to when none is active (never None here:
    ``_ensure_story`` guarantees one exists before a tool commits)."""
    return building.stories[0]


def _mm2(point) -> tuple:
    """Scene metres → planning millimetres (XY)."""
    return (float(point.x()) * 1000.0, float(point.y()) * 1000.0)


def _clamp(value, lo, hi):
    return max(lo, min(hi, value))


def _along_baseline(p0, p1, point) -> float:
    """How far along p0→p1 a world point projects (mm, unclamped)."""
    dx = float(p1[0]) - float(p0[0])
    dy = float(p1[1]) - float(p0[1])
    length = math.hypot(dx, dy)
    if length < 1e-9:
        return 0.0
    return ((point[0] - float(p0[0])) * dx
            + (point[1] - float(p0[1])) * dy) / length


def _story_footprints(building) -> list:
    """Every wall (and column) footprint on the active storey, in mm.

    The join solver trims the ends, so the footprints the region detector sees
    are the real plan shapes — a room's boundary then follows the mitres.
    """
    story = building.active_story()
    if story is None:
        return []
    sid = str(story["id"])
    joins = None
    try:
        from core.building.builder import joins_for_story
        joins = joins_for_story(building, sid)
    except Exception:                       # noqa: BLE001 — detection is best-effort
        joins = None
    out = []
    for el in building.on_story(sid):
        kind = str(el.get("type"))
        params = el.get("params") or {}
        if kind == "wall":
            p0, p1 = params.get("baseline_start_mm"), params.get(
                "baseline_end_mm")
            if not p0 or not p1:
                continue
            lo, hi = planar.side_offsets(params)
            entry = (joins or {}).get(str(el["id"])) or {}
            length = math.hypot(float(p1[0]) - float(p0[0]),
                                float(p1[1]) - float(p0[1]))
            start = entry.get("start") or (0.0, 0.0)
            end = entry.get("end") or (length, length)
            out.append(planar.wall_footprint(
                p0, p1, min(lo, hi), max(lo, hi),
                start=(start[0], start[1]), end=(end[0], end[1])))
        elif kind == "column":
            out.append(_column_footprint(params))
    return [p for p in out if p]


def _column_footprint(params) -> list:
    center = params.get("center_mm") or (0.0, 0.0)
    cx, cy = float(center[0]), float(center[1])
    if params.get("shape") == "round":
        r = float(params.get("diameter_mm", 300.0)) / 2.0
        n = 24
        return [(cx + r * math.cos(2 * math.pi * i / n),
                 cy + r * math.sin(2 * math.pi * i / n)) for i in range(n)]
    w = float(params.get("width_mm", 220.0)) / 2.0
    d = float(params.get("depth_mm", 220.0)) / 2.0
    angle = math.radians(float(params.get("angle_deg", 0.0) or 0.0))
    ca, sa = math.cos(angle), math.sin(angle)
    corners = ((-w, -d), (w, -d), (w, d), (-w, d))
    return [(cx + x * ca - y * sa, cy + x * sa + y * ca)
            for x, y in corners]


#: ``(key, class)`` — what the window registers, in menu order.
BIM_TOOLS = (
    ("wall", WallTool),
    ("curtain_wall", CurtainWallTool),
    ("column", ColumnTool),
    ("beam", BeamTool),
    ("slab", SlabTool),
    ("ceiling", CeilingTool),
    ("roof", RoofTool),
    ("zone", ZoneTool),
    ("door", DoorTool),
    ("window", WindowTool),
    ("fixture", FixtureTool),
)
