# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Marco Sumari Tellez and IngeTrazo contributors.
"""Văn phòng: one folder, the same tables on every machine."""
from __future__ import annotations

import json
import os
import sys

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

if QApplication.instance() is None:
    QApplication(sys.argv[:1])
    # The app names the real entry point sets before anything reads
    # QSettings; without them a test's settings land in another store.
    QApplication.instance().setApplicationName("IngeTrazo")
    QApplication.instance().setOrganizationName("IngeTrazo")


@pytest.fixture()
def office_folder(tmp_path):
    folder = tmp_path / "office"
    folder.mkdir()
    (folder / "office.json").write_text(json.dumps({
        "project": {"name": "VP Kiến trúc A", "chief": "KS C"},
        "pens": {"cut": [0.75, 1, "center"], "hidden": [0.2, 5, "dotted"]},
        "layer_renames": {"KT-CUT": "A-WALL"},
    }, ensure_ascii=False), encoding="utf-8")
    (folder / "chi-tiet.json").write_text(json.dumps({
        "roof_flat": {"name": "Mái VP",
                      "layers": [["Bê tông", "concrete", 120.0, ""]],
                      "note": "theo cấu tạo của văn phòng"},
    }, ensure_ascii=False), encoding="utf-8")
    (folder / "mau").mkdir()
    (folder / "mau" / "nha_pho_mau.igz").write_text("{}", encoding="utf-8")
    return folder


def _office(folder):
    from core.building.office import Office

    return Office(folder)


def test_the_folder_is_optional_and_an_empty_one_changes_nothing():
    """An office that never sets a folder must get EXACTLY the app it had:
    the standard pens, the standard details, an empty project."""
    from core.building import detail_lib as DL
    from core.building import pens as P
    from core.scene import Scene

    scene = Scene()
    standard_cut = P.pen(scene, "cut")
    standard_detail = DL.name("roof_flat", scene)
    applied = _office(None).apply_to(scene)
    assert applied == {}
    assert P.pen(scene, "cut") == standard_cut
    assert DL.name("roof_flat", scene) == standard_detail


def test_the_office_tables_land_on_a_new_document(office_folder):
    """One path, set once, and every machine that points at it issues the
    same drawing: the pens, the layer names, the title data and the
    office's own build-ups."""
    from core.building import detail_lib as DL
    from core.building import pens as P
    from core.building.model import building_of
    from core.scene import Scene

    scene = Scene()
    applied = _office(office_folder).apply_to(scene)
    assert set(applied) == {"project", "pens", "layer_renames", "details"}
    assert building_of(scene).project["name"] == "VP Kiến trúc A"
    assert P.pen(scene, "cut") == (0.75, 1, "center")
    assert P.pen(scene, "hidden") == (0.2, 5, "dotted")
    assert P.layer_name(scene, "cut") == "A-WALL"
    assert DL.name("roof_flat", scene) == "Mái VP"
    assert len(DL.stack_rect("roof_flat", scene)[1]) == 1


def test_a_broken_file_is_skipped_not_raised(office_folder):
    """An office folder that stopped the app would be worse than none: a
    file somebody broke must be ignored, and the rest must still apply."""
    from core.building import pens as P
    from core.scene import Scene

    (office_folder / "office.json").write_text("{ not json at all",
                                               encoding="utf-8")
    scene = Scene()
    applied = _office(office_folder).apply_to(scene)
    assert "pens" not in applied
    assert P.pen(scene, "cut")[0] == 0.5      # the standard table survived
    # but the detail library, a separate file, still applies
    assert "details" in applied


def test_writing_keeps_the_sections_it_was_not_given(office_folder):
    """The title data and the pens share one file in a shared folder: an
    office setting its pen table must not erase what a colleague wrote."""
    office = _office(office_folder)
    office.write_tables(project={"name": "Công trình B"})
    office.write_tables(pens={"cut": (0.9, 3, "dashed")})
    office = _office(office_folder)
    assert office.project_defaults() == {"name": "Công trình B"}
    assert office.config()["pens"]["cut"] == [0.9, 3, "dashed"]
    assert office.config()["layer_renames"] == {"KT-CUT": "A-WALL"}


def test_the_folder_can_be_remembered_and_cleared(tmp_path):
    from core.building.office import Office

    Office.remember(tmp_path)
    assert Office.from_settings().path == tmp_path
    Office.remember(None)
    try:
        assert Office.from_settings().path != tmp_path
    finally:
        Office.remember(None)


def test_the_dialog_reads_and_writes_the_folder(office_folder):
    """The window: point at a folder, see what it holds, and write the
    open document's tables into it."""
    from core.building import office as O
    from core.building import pens as P
    from core.building.model import building_of
    from views.main_window import MainWindow
    from views.office_dialog import OfficeDialog

    win = MainWindow()
    building_of(win.viewport.scene).project.update({"name": "Việc đang làm",
                                                   "chief": "KS D"})
    P.pens(win.viewport.scene)["cut"] = (0.6, 2, "continuous")

    dialog = OfficeDialog(win)
    dialog.path_edit.setText(str(office_folder))
    dialog._use()
    assert O.Office.from_settings().path == office_folder
    assert "có" in dialog.rows["pens"].text()
    assert "mẫu" in dialog.rows["samples"].text()

    dialog._write("project")
    rebuilt = O.Office(office_folder)
    assert rebuilt.project_defaults()["name"] == "Việc đang làm"
    assert rebuilt.config()["pens"]["cut"][0] == 0.75, \
        "ghi số liệu khung tên không được xoá bảng bút của văn phòng"

    dialog._write("pens")
    assert O.Office(office_folder).config()["pens"]["cut"] == \
        [0.6, 2, "continuous"]
    O.Office.remember(None)
    dialog.close()
    win.hide()


def test_a_document_that_is_opened_is_not_restyled(office_folder):
    """The office's tables apply to a NEW document. An opened one is a
    record of what was issued, and silently restyling last year's drawing
    would change a document nobody asked to change."""
    from core.building import office as O
    from core.building import pens as P
    from core.scene import Scene
    from formats.igz import load_into

    win_path = office_folder / "issued.igz"
    from core.history import History
    from core.building import samples as S
    from formats.igz import save_scene

    made = Scene()
    S.build_sample(History(made), made, "townhouse")
    P.pens(made)["cut"] = (0.35, 5, "continuous")     # as issued last year
    save_scene(made, win_path)

    opened = Scene()
    load_into(opened, win_path)
    assert P.pen(opened, "cut") == (0.35, 5, "continuous"), \
        "mở tài liệu cũ mà bút bị đổi theo văn phòng"
    del O
