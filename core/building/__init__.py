# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Marco Sumari Tellez and IngeTrazo contributors.
"""Structured BIM — the parametric building layer on top of the freeform model.

Freeform geometry stays the drawing surface: you draw and push/pull as always.
On top of it sits a *building model*: elements carry their parameters (a wall
knows its thickness, its baseline and how its top links to the storey above),
their geometry is rebuilt from those parameters, and the drawings, the takeoff
and the exports are read from the parameters rather than measured off the mesh.

Layout::

    core/building/__init__.py   public surface: Building, the command registry
    core/building/model.py      Building: the document's element graphs
    core/building/elements.py   element parameter schemas + validation
    core/building/registry.py   the command catalogue (id, label, group)

Everything is JSON-safe: the whole building round-trips through ``.igz``
inside ``scene.plugin_data["building"]``.

This package is the *structured* half of :mod:`core.bim`, which keeps the
lightweight face/group tagging (a tag is metadata; a building element is a
model). The two meet at the takeoff: a tagged face set and a structured
element both bill quantities through the same quantity functions.
"""
from __future__ import annotations

from core.building.model import Building, building_of, store

__all__ = ["Building", "building_of", "store"]
