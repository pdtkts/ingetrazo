# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Marco Sumari Tellez and IngeTrazo contributors.
"""The detail manager: an office's own build-ups, kept with the document."""
from __future__ import annotations

import os
import sys

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

if QApplication.instance() is None:
    QApplication(sys.argv[:1])


@pytest.fixture()
def window():
    from views.main_window import MainWindow

    win = MainWindow()
    yield win
    win.hide()


def _edit_the_floor_detail(scene) -> dict:
    """What the dialog writes when an office changes its floor build-up."""
    from views.detail_manager import overrides

    record = {
        "name": "Chi tiết sàn văn phòng",
        "layers": [("Gạch 600x600", "ceramic", 12.0, "Tô đặc xám"),
                   ("Vữa lót", "mortar", 25.0, "Cát đệm"),
                   ("Bê tông sàn", "concrete", 130.0, "Bê tông cốt thép")],
        "note": "Theo tiêu chuẩn của văn phòng.",
    }
    overrides(scene)["floor_tile"] = record
    return record


def test_the_library_reads_the_document_s_own_edits():
    """An edit is not a copy: the library keeps ONE record per detail, and
    the document's overrides are read through it, so the insert path, the
    dialog and the sheet all see the same build-up."""
    from core.building import detail_lib as DL

    scene = __import__("core.scene", fromlist=["Scene"]).Scene()
    before = DL.name("floor_tile", scene)
    assert before == "Chi tiết sàn lát gạch"
    edit = _edit_the_floor_detail(scene)
    assert DL.name("floor_tile", scene) == edit["name"]
    rect, layers = DL.stack_rect("floor_tile", scene)
    assert len(layers) == 3
    assert rect[3] == pytest.approx(167.0), rect
    # A detail nobody edited is untouched.
    assert DL.name("roof_flat", scene) == DL.name("roof_flat")


def test_an_edited_detail_lands_on_the_sheet_that_way():
    """The insert reads the same record: the drawing on the sheet IS the
    office's build-up, in its own order and thicknesses."""
    from core.building import detail_lib as DL
    from core.composition import Composicion
    from core.scene import Scene

    scene = Scene()
    _edit_the_floor_detail(scene)
    sheet = Composicion()
    made = DL.insert_detail_on_sheet(sheet, "floor_tile", scene=scene)
    assert made["name"] == "Chi tiết sàn văn phòng"
    assert made["bands"] == 3
    labels = [str(getattr(item, "text", "")) for item in sheet.etiquetas]
    assert "Gạch 600x600" in labels, labels
    assert "Bê tông sàn" in labels


def test_the_edit_survives_the_file(tmp_path):
    """It is document data: a detail reissued from a saved file must read
    the same build-up it was drawn from."""
    from core.building import detail_lib as DL
    from core.scene import Scene
    from formats.igz import load_into, save_scene

    scene = Scene()
    _edit_the_floor_detail(scene)
    doc = tmp_path / "office.igz"
    save_scene(scene, doc)
    back = Scene()
    load_into(back, doc)
    assert DL.name("floor_tile", back) == "Chi tiết sàn văn phòng"
    assert len(DL.stack_rect("floor_tile", back)[1]) == 3
    del DL


def test_resetting_a_detail_returns_the_standard_set():
    from core.building import detail_lib as DL
    from core.scene import Scene
    from views.detail_manager import overrides

    scene = Scene()
    _edit_the_floor_detail(scene)
    overrides(scene).pop("floor_tile")
    assert DL.name("floor_tile", scene) == "Chi tiết sàn lát gạch"
    assert len(DL.stack_rect("floor_tile", scene)[1]) == 5


def test_the_manager_dialog_edits_and_saves_one_detail(window):
    """The dialog's own path: pick, change a thickness, save."""
    from core.building import detail_lib as DL
    from views.detail_manager import DetailManagerDialog, merged_details

    scene = window.viewport.scene
    dialog = DetailManagerDialog(window)
    key = dialog.pick.currentData()
    assert key
    dialog.table.cellWidget(0, 2).setValue(77.0)
    dialog.note_edit.setText("Ghi chú của văn phòng.")
    dialog._save()
    record = merged_details(scene)[key]
    assert float(record["layers"][0][2]) == 77.0, record["layers"][0]
    assert record["note"] == "Ghi chú của văn phòng."
    assert DL.name(key, scene) == str(record["name"])
    dialog.close()


def test_the_manager_refuses_a_detail_with_no_layers(window):
    from views.detail_manager import DetailManagerDialog, overrides

    dialog = DetailManagerDialog(window)
    key = dialog.pick.currentData()
    for _ in range(dialog.table.rowCount()):
        dialog.table.removeRow(0)
    dialog._save()
    assert key not in overrides(window.viewport.scene), \
        "chi tiết rỗng không được lưu"
    assert "ít nhất một lớp" in dialog.status.text()
    dialog.close()


def test_the_menu_has_both_the_insert_and_the_manager(window):
    labels = [a.text() for a in window._bim_menu.actions()]
    assert "Chi tiết thư viện…" in labels
    assert "Quản lý chi tiết…" in labels
