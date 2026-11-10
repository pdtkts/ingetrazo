# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Marco Sumari Tellez and IngeTrazo contributors.
"""Tô mặt cắt theo CẤU KIỆN — each cut area in its own material's pattern.

A Vietnamese section is read by its hatch: concrete dense and dotted,
masonry a single 45°, earth back-slanted. One pattern for the whole sheet
is not that drawing — a concrete column standing in a masonry wall is
exactly what a reader looks for, and hatching both as masonry throws it
away.

The hidden-line pass returns closed cut rings carrying no identity (they
are chained chords from a triangle soup), so the attribution is recovered
from each element's own geometry, projected through the same camera the
drawing used. This is the test that the recovered attribution is right:
the numbers below are the model's, not a snapshot.
"""
from __future__ import annotations

import os
import pathlib
import sys
import tempfile

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

from core.building import commands as C  # noqa: E402
from core.building import samples as S  # noqa: E402
from core.building.model import building_of  # noqa: E402
from core.building.scene_sync import sync  # noqa: E402
from core.history import History  # noqa: E402
from core.scene import Scene  # noqa: E402

_app = QApplication.instance() or QApplication([])

MASONRY = "Tường gạch (cắt)"
CONCRETE = "Bê tông cốt thép"


def _storey_scene(with_column: bool):
    """A townhouse's ground floor, optionally with a concrete column
    standing INSIDE the masonry walls — the case a single hatch cannot
    tell apart."""
    scene = Scene()
    history = History(scene)
    S.build_sample(history, scene, "townhouse")
    building = building_of(scene)
    story_id = str(building.stories[0]["id"])
    if with_column:
        command = C.add_element("column", story_id, {
            "x_mm": 2000.0, "y_mm": 1500.0, "width_mm": 300.0,
            "depth_mm": 300.0, "height_mm": 3300.0})
        command._rebuild = lambda s, b: sync(s, b)
        history.execute(command)
    return scene, building_of(scene), story_id


def _drawing(scene, building, story_id):
    from core.building import drawings as _drawings
    from core.hlr import hlr_drawing

    view = _drawings.view_for(building,
                             {"kind": "story", "story_id": story_id})
    plane = view.section_planes[0] if view.section_planes else None
    drawing = hlr_drawing(scene, view.camera(), profiles=True, fills=True,
                          section=plane)
    return view, plane, drawing


def test_each_cut_area_is_attributed_to_its_own_element():
    """The wall rings come back masonry and the column's ring concrete:
    the attribution is recovered from the elements' own geometry rather
    than guessed from position."""
    from core.building.surface_fill import (cut_rings_per_element,
                                            element_material,
                                            material_of_ring)

    scene, building, story_id = _storey_scene(with_column=True)
    view, plane, model = _drawing(scene, building, story_id)
    assert len(model.loops) > 1

    attributed = cut_rings_per_element(scene, plane, view.camera())
    assert attributed, "không quy được vùng cắt nào về cấu kiện"

    seen = {}
    for ring in model.loops:
        name = material_of_ring(scene, ring, attributed, "")
        seen[name] = seen.get(name, 0) + 1

    assert CONCRETE in seen, \
        f"cột bê tông không có vùng tô riêng: {seen}"
    assert MASONRY in seen, f"tường gạch mất vùng tô: {seen}"
    assert seen[CONCRETE] >= 1 and seen[MASONRY] >= 2, seen

    # …and the column's own entry really is the concrete one, so the
    # answer above came from the material table and not from a default.
    column = next(e for e in building.elements if e.get("type") == "column")
    assert element_material(scene, column) == CONCRETE


def test_an_unattributable_ring_falls_back_instead_of_vanishing():
    """A ring with no matching element keeps the caller's own material:
    an area white-on-white loses the poché itself, which is worse than
    losing a detail of it."""
    from core.building.surface_fill import material_of_ring

    scene, building, story_id = _storey_scene(with_column=False)
    _view, _plane, _model = _drawing(scene, building, story_id)
    stray = [[0.0, 0.0], [10.0, 0.0], [10.0, 10.0]]
    assert material_of_ring(scene, stray, [], "DỰ-PHÒNG") == "DỰ-PHÒNG"


def test_the_dxf_writes_one_hatch_per_material():
    """Two materials in the model mean two hatch objects in the file, each
    carrying its own regenerable pattern definition — the receiving CAD
    redraws them at any zoom, which is the whole point of a PATTERN hatch
    over anonymous lines."""
    import ezdxf

    from formats.dxf_bim import save_drawing_dxf

    scene, building, story_id = _storey_scene(with_column=True)
    view, _plane, _model = _drawing(scene, building, story_id)
    out = pathlib.Path(tempfile.mkdtemp()) / "fills.dxf"
    counts = save_drawing_dxf(str(out), view, scene)
    assert counts["hatch"] > 1

    doc = ezdxf.readfile(str(out))
    hatches = [e for e in doc.modelspace() if e.dxftype() == "HATCH"]
    assert len(hatches) >= 2, "cả bản vẽ chỉ có một kiểu tô"

    signatures = set()
    for hatch in hatches:
        signatures.add(tuple(
            (round(line.angle, 1), round(line.offset.x, 2),
             round(line.offset.y, 2))
            for line in hatch.pattern.lines))
    assert len(signatures) >= 2, signatures
    # The masonry family is a single 45°; the concrete one interleaves two
    # 45° families with a lateral shift and a 135° — the trade's own.
    straight = [s for s in signatures if len(s) == 1 and s[0][0] == 45.0]
    assert straight, signatures


def test_the_paper_frame_carries_each_area_s_own_material():
    """The sheet hatches by the same rule the file does: every fill the
    frame draws has a material name beside it, and there is more than one
    material in a mixed model."""
    from PySide6.QtWidgets import QWidget

    from core.building import docset as _docset
    from tests.test_composer_canvas import _FakeViewport
    from views.composer import ComposerWindow

    scene, building, story_id = _storey_scene(with_column=True)
    host = QWidget()
    host.viewport = _FakeViewport()
    host.viewport.scene = scene
    res = _docset.generate_docset(scene, building_of(scene),
                                 annotations=True)
    issued = next(s for s in res.sheets
                  if "Mặt bằng — Tầng 1" in str(getattr(s, "name", "")))
    composer = ComposerWindow(host)
    composer.comp = issued
    frame = issued.frames[0]
    frame.cut_fill = "hatch"
    composer.compute_hlr(frame)

    materials = list(frame.cut_materials or ())
    fills = composer.hlr_fills.get(id(frame)) or []
    assert fills, "khung không có vùng cắt nào"
    assert len(materials) == len(fills), (len(materials), len(fills))
    assert len(set(materials)) >= 2, sorted(set(materials))
    assert CONCRETE in set(materials), set(materials)


def test_the_paper_hatches_each_ring_in_its_own_pattern():
    """The frame's paint is where the hatching happens, and it is the one
    place a missing import is invisible to every test that only checks the
    materials: `QPainterPath` was used there without being imported, so
    every frame with a hatched cut raised NameError as it PAINTED — a
    drawing that renders blank on the sheet an office sends out.

    So this paints: two rings, two materials, and the ink they leave on
    the image must differ, because masonry is one 45° family and concrete
    interleaves two with a lateral shift.
    """
    import numpy as np
    from PySide6.QtGui import QImage, QPainter

    from core.composition import MarcoVista
    from views.composer import _paint_cut_fills_mm

    frame = MarcoVista()
    frame.cut_fill = "hatch"
    frame.cut_materials = [MASONRY, CONCRETE]
    masonry_ring = np.array([[10.0, 10.0], [110.0, 10.0],
                             [110.0, 60.0], [10.0, 60.0]])
    concrete_ring = np.array([[150.0, 10.0], [250.0, 10.0],
                              [250.0, 60.0], [150.0, 60.0]])

    image = QImage(300, 90, QImage.Format_ARGB32)
    image.fill(0xFFFFFFFF)
    painter = QPainter(image)
    try:                       # this raised NameError before the fix
        _paint_cut_fills_mm(painter, frame, [masonry_ring, concrete_ring])
    finally:
        painter.end()

    def ink(x0, x1):
        return sum(1 for y in range(10, 60) for x in range(x0, x1)
                   if image.pixel(x, y) != 0xFFFFFFFF)

    masonry_ink, concrete_ink = ink(10, 110), ink(150, 250)
    assert masonry_ink > 0, "vùng gạch không được tô gì"
    assert concrete_ink > 0, "vùng bê tông không được tô gì"
    assert masonry_ink != concrete_ink, \
        "hai vật liệu tô ra cùng một vệt — mất hẳn ý nghĩa của poché"
