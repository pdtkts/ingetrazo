# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Marco Sumari Tellez and IngeTrazo contributors.
"""The pens: how each class of line is inked, and what a layer's own name is.

A drawing office does not ink a wall and a dimension the same way, and it
does not accept the CAD vendor's layer names either — it has a table of
its own, agreed with the people who receive the files. This is that
table, stated once and used by all three consumers: the DXF export, the
paper (PDF) and the drawing frames.

``PENS`` is the class table: for every class of line the width in paper
millimetres, an index colour and a line pattern. ``LAYER_RENAMES`` is the
name table: the class's layer on the way out, e.g. ``KT-CUT`` → ``A-WALL``.

Both live on the document (``scene.pens`` / ``scene.layer_renames``),
because two jobs by the same office should not print two different walls.
"""
from __future__ import annotations

#: Where the document keeps them.
PENS_KEY = "pens"
RENAMES_KEY = "layer_renames"

#: The classes of line, in the order the manager shows them, with the
#: Vietnamese label the dialog uses.
CLASSES: tuple = (
    ("cut", "Nét cắt"),
    ("profile", "Nét thấy (bao)"),
    ("edge", "Nét thấy (cạnh)"),
    ("hidden", "Nét khuất"),
    ("dimension", "Kích thước"),
    ("text", "Chữ"),
    ("hatch", "Mặt cắt (hatch)"),
    ("construction", "Nét dựng"),
)

#: The trade's starting table: ``class -> (width_mm, autocad_colour,
#: linetype)``. Widths grow from the construction lines to the cut, which
#: is what makes a plan read at arm's length.
PENS: dict = {
    "cut": (0.50, 7, "continuous"),
    "profile": (0.35, 7, "continuous"),
    "edge": (0.18, 7, "continuous"),
    "hidden": (0.18, 8, "dashed"),
    "dimension": (0.13, 4, "continuous"),
    "text": (0.18, 7, "continuous"),
    "hatch": (0.09, 9, "continuous"),
    "construction": (0.05, 253, "continuous"),
}

#: ``class key -> (layer in the file, paper pen)`` as the exporter reads it.
#: The layer key is part of the drawing's contract with other CADs, so it
#: is spelled here, once, and not composed by string handling.
LAYER_KEYS: dict = {
    "cut": "KT-CUT",
    "profile": "KT-PROFILE",
    "edge": "KT-EDGE",
    "hidden": "KT-HIDDEN",
    "dimension": "KT-DIM",
    "text": "KT-TEXT",
    "hatch": "KT-HATCH",
    "construction": "KT-DUNG",
}

#: Starting name table, empty: the file carries the app's class layers
#: until the office says otherwise.
LAYER_RENAMES: dict = {}


def pens(scene) -> dict:
    """The document's pen table, made from the standard one on first use."""
    if scene is None:
        return dict(PENS)
    store = getattr(scene, PENS_KEY, None)
    if not isinstance(store, dict) or not store:
        store = {key: tuple(value) for key, value in PENS.items()}
        setattr(scene, PENS_KEY, store)
    return store


def renames(scene) -> dict:
    """The document's layer-name table (class layer → the office's name)."""
    if scene is None:
        return {}
    store = getattr(scene, RENAMES_KEY, None)
    if not isinstance(store, dict):
        store = {}
        setattr(scene, RENAMES_KEY, store)
    return store


def pen(scene, key: str) -> tuple:
    """``(width_mm, colour, linetype)`` for one class, falling back to the
    standard table for a key the document has never heard of."""
    return tuple(pens(scene).get(str(key))
                 or PENS.get(str(key)) or (0.18, 7, "continuous"))


def layer_name(scene, key: str) -> str:
    """The layer this class is written on: the office's name if it has one."""
    standard = LAYER_KEYS.get(str(key), str(key))
    return str(renames(scene).get(standard) or standard)


def width_mm(scene, key: str) -> float:
    return float(pen(scene, key)[0])


def as_frame_pens(scene, frame) -> None:
    """Copy the document's widths onto a frame, so the paper follows the
    same table the file does. A frame already stating its own widths (a
    composer frame the user set by hand) is left alone."""
    if scene is None or frame is None:
        return
    frame.pen_cut_mm = width_mm(scene, "cut")
    frame.pen_profile_mm = width_mm(scene, "profile")
    frame.pen_edge_mm = width_mm(scene, "edge")


def export_tables(scene) -> tuple:
    """``(pen_table, layer_map)`` in the exporter's own shapes.

    The pen table keeps the full ``(width, colour, linetype)`` triple: the
    DXF needs all three (a dashed line written solid is a lie), and the
    export's own reader is what picks them apart.
    """
    table = {}
    for key in CLASSES:
        width, color, linetype = pen(scene, key[0])
        table[key[0]] = (float(width), int(color), str(linetype))
    mapping = {standard: layer_name(scene, key)
               for key, standard in LAYER_KEYS.items()}
    mapping = {k: v for k, v in mapping.items() if k != v}
    return table, mapping
