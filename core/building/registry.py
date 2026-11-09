# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Marco Sumari Tellez and IngeTrazo contributors.
"""The command catalogue — one declaration of every BIM action.

Menu, toolbar, palette, shortcut table and the MCP bridge all read from here,
so a command exists once and appears everywhere. Same doctrine as the rest of
the app: the label is shown through :func:`core.i18n.tr`, and the Vietnamese
catalogue (``i18n/vi.json``) carries the translation while English stays the
source string.

Groups are the seven of the classic BIM workspace, in their fixed order; the
plan bar adds the drawing/editing tools the plan window needs but the menu
does not list.
"""
from __future__ import annotations

#: ``(id, label, group)`` — the label is the English source string.
GROUPS = (
    ("select", "Select"),
    ("design", "Design"),
    ("viewpoint", "Viewpoint"),
    ("document", "Document"),
    ("draw", "Draw"),
    ("edit", "Edit"),
    ("layout", "Layout"),
)

#: Every command the building layer answers to.
LIST = (
    ("select", "Select", "select"),
    ("pick", "Eyedropper", "select"),
    ("inject", "Apply properties", "select"),
    ("wall", "Wall", "design"),
    ("curtain_wall", "Curtain wall", "design"),
    ("column", "Column", "design"),
    ("beam", "Beam", "design"),
    ("slab", "Slab", "design"),
    ("ceiling", "Ceiling", "design"),
    ("roof", "Roof", "design"),
    ("stair", "Stair", "design"),
    ("door", "Door", "design"),
    ("window", "Window", "design"),
    ("zone", "Zone", "design"),
    ("fixture", "Fixture", "design"),
    ("section", "Section", "viewpoint"),
    ("elevation", "Elevation", "viewpoint"),
    ("interior", "Interior elevation", "viewpoint"),
    ("detail", "Detail", "viewpoint"),
    ("worksheet", "Worksheet", "viewpoint"),
    ("crop", "Crop region", "viewpoint"),
    ("dimension", "Dimension", "document"),
    ("level", "Level", "document"),
    ("radial", "Radial dimension", "document"),
    ("angle", "Angle dimension", "document"),
    ("text", "Text", "document"),
    ("label", "Label", "document"),
    ("grid", "Grid", "document"),
    ("symbol", "Symbol", "document"),
    ("change", "Revision cloud", "document"),
    ("fill", "Fill", "document"),
    ("line", "Line", "draw"),
    ("polyline", "Polyline", "draw"),
    ("arc", "Arc / circle", "draw"),
    ("spline", "Spline", "draw"),
    ("image", "Image", "draw"),
    ("stretch", "Stretch", "edit"),
    ("copy2d", "Copy 2D", "edit"),
    ("paste2d", "Paste 2D", "edit"),
    ("region", "Place on sheet", "layout"),
    ("sheet_frame", "Sheet frame", "layout"),
    ("master_area", "Drawing area", "layout"),
    ("magnifier", "Magnifier", "layout"),
    # ---- the plan window's own editing and drawing tools ----------------
    # They live in this one catalogue so the bar, the shortcut table and
    # the palette all read the same declaration; a bar that showed raw
    # ids for a third of its buttons was reading a list that never
    # mentioned them.
    ("guide", "Guide", "select"),
    ("protractor", "Protractor", "select"),
    ("guideclr", "Clear guides", "select"),
    ("measure", "Tape measure", "select"),
    ("move", "Move", "edit"),
    ("rotate", "Rotate", "edit"),
    ("scale", "Scale", "edit"),
    ("mirror", "Mirror", "edit"),
    ("offset", "Offset edges", "edit"),
    ("trim", "Trim", "edit"),
    ("eraser", "Eraser", "edit"),
    ("delete", "Delete", "edit"),
    ("rect", "Rectangle", "draw"),
    ("rrect", "Rotated rectangle", "draw"),
    ("polygon", "Polygon", "draw"),
    ("circle", "Circle", "draw"),
    ("arc2", "Arc (2 points)", "draw"),
    ("arc3", "Arc (3 points)", "draw"),
    ("block", "Group 2D", "draw"),
    # The registry's own word for a dimension is ``dimension``; the plan
    # bar's id for the same command is ``dim``. Both resolve to one entry.
    ("dim", "Dimension", "document"),
)

#: Groups of the plan window's vertical bar — ids in the order they appear.
PLAN_BAR = (
    ("select", ("select", "pick", "inject", "guide", "protractor",
                "guideclr", "measure")),
    ("edit", ("move", "rotate", "scale", "mirror", "stretch", "offset",
              "trim", "eraser", "delete", "copy2d", "paste2d")),
    ("design", ("wall", "curtain_wall", "column", "beam", "slab", "ceiling",
                "roof", "stair", "door", "window", "zone", "fixture")),
    ("draw", ("line", "polyline", "rect", "rrect", "polygon", "circle",
              "arc2", "arc3", "spline", "image", "block")),
    ("document", ("dim", "level", "radial", "angle", "text", "label", "grid",
                  "symbol", "change", "fill")),
    ("viewpoint", ("section", "elevation", "interior", "detail", "worksheet",
                   "crop")),
    ("layout", ("region", "sheet_frame", "master_area", "magnifier")),
)

#: Keys the plan window gives its tools when no user shortcut overrides them.
PLAN_KEYS = {
    " ": "select",
    "l": "line",
    "w": "wall",
    "d": "door",
    "n": "window",
    "k": "dim",
    "m": "move",
    "q": "rotate",
    "t": "trim",
    "r": "rect",
    "c": "circle",
    "a": "arc2",
    "e": "eraser",
    "o": "offset",
    "s": "scale",
    "g": "guide",
}

_BY_ID = {cmd_id: (cmd_id, label, group) for cmd_id, label, group in LIST}


def all_commands():
    """Every ``(id, label, group)`` in catalogue order."""
    return list(LIST)


def find(cmd_id):
    """The ``(id, label, group)`` of ``cmd_id``, or ``None``."""
    return _BY_ID.get(str(cmd_id))


def tools():
    """``[(id, label), ...]`` in catalogue order — for shortcut assignment."""
    return [(cmd_id, label) for cmd_id, label, _group in LIST]


def by_group(group):
    """The ``(id, label)`` pairs declared in ``group``."""
    return [(cmd_id, label) for cmd_id, label, g in LIST if g == group]


def groups():
    """``[(group_id, group_label), ...]`` in their fixed order."""
    return list(GROUPS)
