# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Marco Sumari Tellez and IngeTrazo contributors.
"""Pens & layers: one table, three consumers (dialog, DXF, paper)."""
from __future__ import annotations

import os
import sys

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

if QApplication.instance() is None:
    QApplication(sys.argv[:1])

ezdxf = pytest.importorskip("ezdxf")


def _scene_with_a_house():
    from core.building import samples as S
    from core.history import History
    from core.scene import Scene

    scene = Scene()
    history = History(scene)
    building, _counts = S.build_sample(history, scene, "townhouse")
    return scene, building


def test_a_document_starts_on_the_trade_s_table():
    from core.building import pens as P
    from core.scene import Scene

    scene = Scene()
    assert P.pen(scene, "cut") == (0.5, 7, "continuous")
    assert P.pen(scene, "hidden") == (0.18, 8, "dashed")
    # The cut is heavier than the edge, or a plan reads as a wireframe.
    assert P.width_mm(scene, "cut") > P.width_mm(scene, "edge")
    # A class nobody has heard of still inks something.
    assert P.pen(scene, "nope")[0] > 0.0
    assert P.layer_name(scene, "cut") == "KT-CUT"


def test_the_edit_is_the_document_s_not_a_copy():
    """The dialog writes the document; the readers read the document."""
    from core.building import pens as P

    scene, _building = _scene_with_a_house()
    P.pens(scene)["cut"] = (0.7, 1, "dashdot")
    P.renames(scene)["KT-CUT"] = "A-WALL"
    assert P.pen(scene, "cut") == (0.7, 1, "dashdot")
    assert P.layer_name(scene, "cut") == "A-WALL"
    assert P.export_tables(scene)[1] == {"KT-CUT": "A-WALL"}


def test_the_dxf_is_written_with_the_office_s_pens(tmp_path):
    """Three things have to travel: the layer NAME, the line WEIGHT and
    the line PATTERN. A dashed wall written solid is a lie about what was
    drawn, and it is the file's job to say which is which."""
    from core.building import drawings as D
    from core.building import pens as P
    from formats.dxf_bim import save_plan_dxf

    scene, building = _scene_with_a_house()
    P.pens(scene)["cut"] = (0.9, 1, "dashdot")
    P.pens(scene)["hidden"] = (0.2, 5, "dotted")
    P.renames(scene)["KT-CUT"] = "A-WALL"
    table, mapping = P.export_tables(scene)
    story = building.stories[1]
    path = tmp_path / "pens.dxf"
    save_plan_dxf(str(path), scene, building, str(story["id"]),
                  pens=table, layer_map=mapping)
    doc = ezdxf.readfile(str(path))
    names = {layer.dxf.name for layer in doc.layers}
    assert "A-WALL" in names
    assert "KT-CUT" not in names, "tên lớp cũ còn trong file"
    layer = doc.layers.get("A-WALL")
    assert layer.dxf.lineweight == 90, "bề rộng nét chưa theo bảng"
    assert layer.dxf.linetype == "DASHDOT"
    assert layer.color == 1
    assert doc.header.get("$LTSCALE") == 1.0, \
        "kiểu nét tính theo mm giấy nên LTSCALE phải là 1"
    hidden = doc.layers.get("KT-HIDDEN")
    assert hidden.dxf.linetype == "DOT"
    del D


def test_the_paper_follows_the_same_table():
    """A sheet and the DXF of it must be inked the same — the office set
    the table once, so the PDF cannot keep the default widths."""
    from core.building import pens as P
    from core.composition import MarcoVista

    scene, _building = _scene_with_a_house()
    P.pens(scene)["cut"] = (0.8, 3, "continuous")
    P.pens(scene)["profile"] = (0.4, 3, "continuous")
    frame = MarcoVista()
    P.as_frame_pens(scene, frame)
    assert frame.pen_cut_mm == 0.8
    assert frame.pen_profile_mm == 0.4


def test_a_linetype_the_file_does_not_have_is_defined_in_it(tmp_path):
    """The pattern travels in the FILE, not in the reader's head: a CAD
    that has never seen this app must still draw the dash."""
    from core.building import pens as P
    from formats.dxf_bim import _dxf_linetype_pattern, save_plan_dxf
    from core.building import drawings as D

    pattern = _dxf_linetype_pattern("dashdot")
    assert pattern and pattern[0] == sum(abs(v) for v in pattern[1:])
    assert any(v < 0 for v in pattern), "pattern phải có đoạn nghỉ"

    scene, building = _scene_with_a_house()
    P.pens(scene)["hidden"] = (0.13, 8, "dashdotdot")
    table, mapping = P.export_tables(scene)
    path = tmp_path / "lt.dxf"
    story = building.stories[0]
    save_plan_dxf(str(path), scene, building, str(story["id"]),
                  pens=table, layer_map=mapping)
    doc = ezdxf.readfile(str(path))
    assert "DIVIDE" in {t.dxf.name for t in doc.linetypes}
    del D


def test_the_pens_survive_the_file(tmp_path):
    from core.building import pens as P
    from core.scene import Scene
    from formats.igz import load_into, save_scene

    scene, _building = _scene_with_a_house()
    P.pens(scene)["cut"] = (0.65, 2, "center")
    P.renames(scene)["KT-HATCH"] = "A-HATCH"
    doc = tmp_path / "office.igz"
    save_scene(scene, doc)
    back = Scene()
    load_into(back, doc)
    assert P.pen(back, "cut") == (0.65, 2, "center")
    assert P.layer_name(back, "hatch") == "A-HATCH"
    assert P.layer_name(back, "edge") == "KT-EDGE", "lớp chưa sửa phải giữ chuẩn"


def test_the_manager_edits_both_tables_and_resets_them():
    from core.building import pens as P
    from views.main_window import MainWindow
    from views.pens_dialog import PensDialog

    win = MainWindow()
    labels = [a.text() for a in win._bim_menu.actions()]
    assert "Bút vẽ & Lớp bản vẽ…" in labels
    dialog = PensDialog(win)
    assert dialog.table.rowCount() == len(P.CLASSES)
    assert dialog.layers.rowCount() == len(P.LAYER_KEYS)
    dialog.table.cellWidget(0, 1).setValue(0.42)
    dialog.layers.item(0, 1).setText("A-WALL")
    dialog._apply()
    scene = win.viewport.scene
    assert P.width_mm(scene, "cut") == 0.42
    assert P.layer_name(scene, "cut") == "A-WALL"
    dialog._reset()
    assert P.pen(scene, "cut") == P.PENS["cut"]
    assert P.layer_name(scene, "cut") == "KT-CUT"
    dialog.close()
    win.hide()
