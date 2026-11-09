# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Marco Sumari Tellez and IngeTrazo contributors.
"""Element parameter schemas — one declaration per element type.

Every default, every field name and every unit lives here, so the properties
panel, the tools, the MCP bridge and the tests all speak one vocabulary. The
defaults are the *standard Vietnamese construction sizes* an architect starts
from, not arbitrary numbers.

Units: lengths in **millimetres**, angles in degrees. Baselines, outlines and
centres are **absolute world XY** (millimetres); Z comes from the element's
storey plus its own offsets.
"""
from __future__ import annotations

# ---- building materials (the civil list) ------------------------------------
#: ``id -> {name, priority, cut_fill, surface_color, cut_pen}``. The priority
#: drives the wall-join solver: at a corner the higher priority runs through
#: and the lower trims to its face (concrete beats masonry).
MATERIALS = {
    "btct": {"name": "Bê tông cốt thép", "priority": 900,
             "cut_fill": "Bê tông cốt thép", "surface_color": "#FFFFFF",
             "cut_pen": 3},
    "gach": {"name": "Gạch xây", "priority": 500,
             "cut_fill": "Tường gạch (cắt)", "surface_color": "#FFFFFF",
             "cut_pen": 3},
    "gach_nhe": {"name": "Gạch nhẹ / AAC", "priority": 400,
                 "cut_fill": "Gạch block", "surface_color": "#FFFFFF",
                 "cut_pen": 3},
    "thach_cao": {"name": "Vách thạch cao", "priority": 200,
                  "cut_fill": "", "surface_color": "#FFFFFF", "cut_pen": 3},
    "go": {"name": "Gỗ", "priority": 300, "cut_fill": "Gỗ",
           "surface_color": "#A0764A", "cut_pen": 3},
    "nhom": {"name": "Nhôm / khung kim loại", "priority": 800,
             "cut_fill": "Kim loại (đặc)", "surface_color": "#9AA5AE",
             "cut_pen": 2},
    "kinh": {"name": "Kính", "priority": 100, "cut_fill": "Kính",
             "surface_color": "#BEE3F8", "cut_pen": 2},
    "da_granite": {"name": "Đá granite", "priority": 600,
                   "cut_fill": "Bê tông cốt thép", "surface_color": "#FFFFFF",
                   "cut_pen": 3},
    "dat": {"name": "Đất", "priority": 50, "cut_fill": "Đất tự nhiên",
            "surface_color": "#FFFFFF", "cut_pen": 3},
    "vua": {"name": "Vữa trát / láng", "priority": 150, "cut_fill": "Cát đệm",
            "surface_color": "#E8E2D6", "cut_pen": 3},
    "be_tong": {"name": "Bê tông (lót)", "priority": 700,
                "cut_fill": "Bê tông cốt thép", "surface_color": "#C9C9C9",
                "cut_pen": 3},
    "gach_op": {"name": "Gạch lát / ốp", "priority": 250, "cut_fill": "Tô đặc xám",
                "surface_color": "#D9D2C5", "cut_pen": 3},
    "chong_tham": {"name": "Chống thấm", "priority": 120,
                   "cut_fill": "Kim loại (đặc)", "surface_color": "#404040",
                   "cut_pen": 3},
    "cach_nhiet": {"name": "Cách nhiệt", "priority": 110, "cut_fill": "Cách nhiệt",
                   "surface_color": "#F2E6A6", "cut_pen": 3},
    "thep": {"name": "Thép", "priority": 850, "cut_fill": "Kim loại (đặc)",
             "surface_color": "#7F8C99", "cut_pen": 3},
}

DEFAULT_WALL = "gach"
DEFAULT_SLAB = "btct"
DEFAULT_FRAME = "nhom"
DEFAULT_GLASS = "kinh"
DEFAULT_DOOR_LEAF = "go"


# ---- element defaults -------------------------------------------------------
#: The parameter set every element type starts from. ``None`` in a copy of one
#: of these is a deliberate "not set" (e.g. an element with no material).

STORY_DEFAULTS = {
    "name": "Tầng", "z_mm": 0.0, "height_mm": 3300.0,
    # The plane plan drawings are cut at, ABOVE the storey floor.
    "cut_mm": 1200.0,
    # Per-storey floor drop for wet rooms (level marks, §level_drop).
    "wet_drop_mm": -50.0,
}

WALL_DEFAULTS = {
    "height_mm": 3300.0, "thickness_mm": 200.0, "base_offset_mm": 0.0,
    "reference_line": "center", "flip_side": False, "material_id": None,
    "building_material_id": DEFAULT_WALL,
    "top_link": "next", "top_offset_mm": 0.0,
}

DOOR_DEFAULTS = {
    "width_mm": 900.0, "height_mm": 2200.0, "sill_height_mm": 0.0,
    "frame_width_mm": 40.0, "frame_depth_mm": None, "leaf_thickness_mm": 40.0,
    "handing": "left", "opening_side": "in", "opening_angle_deg": 90.0,
    "material_id": None, "frame_material_id": DEFAULT_DOOR_LEAF,
    "leaf_material_id": DEFAULT_DOOR_LEAF, "leaf_type": "single",
    "frame_position": "center", "frame_left": True, "frame_right": True,
}

WINDOW_DEFAULTS = {
    "width_mm": 1200.0, "height_mm": 1200.0, "sill_height_mm": 900.0,
    "frame_width_mm": 60.0, "frame_depth_mm": None, "leaf_thickness_mm": 10.0,
    "handing": "left", "opening_side": "in", "opening_angle_deg": 0.0,
    "material_id": None, "frame_material_id": DEFAULT_FRAME,
    "leaf_material_id": DEFAULT_GLASS, "leaf_type": "single",
    "frame_position": "center", "frame_left": True, "frame_right": True,
}

CURTAIN_WALL_DEFAULTS = {
    "width_mm": 2400.0, "height_mm": 2700.0, "sill_height_mm": 0.0,
    "col_count": 3, "row_count": 2, "col_widths": [],
    "row_heights": [1000.0, 0.0], "cells": {}, "merges": [],
    "frame_width_mm": 50.0, "frame_depth_mm": 100.0, "sash_width_mm": 40.0,
    "leaf_thickness_mm": 10.0, "frame_position": "center",
    "opening_angle_deg": 90.0, "material_id": None,
    "frame_material_id": DEFAULT_FRAME, "leaf_material_id": DEFAULT_GLASS,
}

SLAB_DEFAULTS = {
    "thickness_mm": 120.0, "top_offset_mm": 0.0,
    "building_material_id": DEFAULT_SLAB,
}

CEILING_DEFAULTS = {
    "height_mm": 2900.0, "thickness_mm": 9.0,
    "building_material_id": "thach_cao", "ifc_class": "IfcCovering",
    "predefined_type": "CEILING",
}

COLUMN_DEFAULTS = {
    "shape": "rect", "width_mm": 220.0, "depth_mm": 220.0,
    "diameter_mm": 300.0, "angle_deg": 0.0, "base_offset_mm": 0.0,
    "top_link": "next", "top_offset_mm": 0.0, "height_mm": 3300.0,
    "building_material_id": DEFAULT_SLAB,
}

BEAM_DEFAULTS = {
    "width_mm": 220.0, "depth_mm": 300.0, "top_link": "next",
    "top_offset_mm": 0.0, "height_mm": 3300.0, "base_offset_mm": 0.0,
    "building_material_id": DEFAULT_SLAB, "mark": "",
}

ROOF_DEFAULTS = {
    "slope_deg": 30.0, "gable_edges": "", "overhang_mm": 500.0,
    "thickness_mm": 150.0, "top_link": "next", "top_offset_mm": 0.0,
    "height_mm": 3300.0, "base_offset_mm": 0.0,
    "building_material_id": DEFAULT_SLAB,
}

STAIR_DEFAULTS = {
    "width_mm": 1000.0, "tread_mm": 260.0, "waist_mm": 150.0,
    "building_material_id": "btct", "structure": "concrete",
    "soffit": "sloped", "stringer_h_mm": 250.0, "stringer_t_mm": 12.0,
    "finish": "stone", "finish_mm": 30.0, "nosing_mm": 20.0,
    "nosing_shape": "square", "riser_clad": True, "riser_clad_mm": 20.0,
    "railing": "glass", "railing_side": "left", "rail_h_mm": 900.0,
    "post_step_mm": 1000.0, "rail_profile": "rect", "rail_w_mm": 60.0,
    "rail_t_mm": 45.0, "rail_bend_mm": 80.0, "rail_end": "cut", "mid_n": 2,
    "post_w_mm": 40.0, "bar_step_mm": 110.0, "post_mount": "top",
    "tread_kind": "plate", "tread_t_mm": 50.0, "shape": "path",
    "sweep_deg": 360.0, "r_in_mm": 100.0, "turn": "ccw", "winders": False,
    "winder_n": 3, "beam_w_mm": 220.0, "beam_h_mm": 450.0,
    "step_material_id": DEFAULT_WALL, "ifc_class": "IfcStair",
}

ZONE_DEFAULTS = {
    "name": "Phòng", "number": "", "category": "khac", "pen": 1,
    "show_area": True, "show_fill": False, "line_style": "dashed",
    "text_style": "",
}

FIXTURE_DEFAULTS = {
    "fixture_type": "wc", "angle_deg": 0.0,
    "ifc_class": "IfcSanitaryTerminal",
}

CUSTOM_DEFAULTS = {}  #: free-form geometry keeps whatever the user drew.

#: ``type id -> DEFAULTS``. The tools and the properties panel read this.
BY_TYPE = {
    "wall": WALL_DEFAULTS,
    "door": DOOR_DEFAULTS,
    "window": WINDOW_DEFAULTS,
    "curtain_wall": CURTAIN_WALL_DEFAULTS,
    "slab": SLAB_DEFAULTS,
    "ceiling": CEILING_DEFAULTS,
    "column": COLUMN_DEFAULTS,
    "beam": BEAM_DEFAULTS,
    "roof": ROOF_DEFAULTS,
    "stair": STAIR_DEFAULTS,
    "zone": ZONE_DEFAULTS,
    "fixture": FIXTURE_DEFAULTS,
    "custom": CUSTOM_DEFAULTS,
}

#: Types that live *inside* a wall group, never at the top level.
OPENING_TYPES = frozenset({"door", "window", "curtain_wall"})

#: Types whose top can follow the storey above.
LINKED_TOP_TYPES = frozenset({"wall", "column", "beam", "roof"})

#: The stored type id → the IFC4 class it exports as.
IFC_CLASS_OF = {
    "wall": "IfcWall",
    "door": "IfcDoor",
    "window": "IfcWindow",
    "curtain_wall": "IfcCurtainWall",
    "slab": "IfcSlab",
    "ceiling": "IfcCovering",
    "column": "IfcColumn",
    "beam": "IfcBeam",
    "roof": "IfcRoof",
    "stair": "IfcStair",
    "zone": "IfcSpace",
    "fixture": "IfcSanitaryTerminal",
    "custom": "IfcBuildingElementProxy",
}


def defaults_for(kind: str) -> dict:
    """A fresh copy of ``kind``'s defaults (never the shared dict itself)."""
    base = BY_TYPE.get(str(kind), {})
    return {key: (list(value) if isinstance(value, list) else value)
            for key, value in base.items()}


def material(material_id) -> dict:
    """The material record, falling back to masonry for unknown ids."""
    return MATERIALS.get(str(material_id or ""), MATERIALS[DEFAULT_WALL])


def priority_of(params: dict) -> int:
    """The join priority of an element's material (0 when it has none)."""
    mid = params.get("building_material_id")
    if not mid:
        return 0
    return int(material(mid).get("priority", 0))
