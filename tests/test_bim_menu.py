# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Marco Sumari Tellez and IngeTrazo contributors.
"""The BIM menu is where the office does the work: the set, the check,
the schedule, the DXF. A menu entry that opens nothing is worse than a
missing one, so each is exercised here.
"""
from __future__ import annotations

import os
import sys

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest  # noqa: E402
from PySide6.QtWidgets import (QApplication, QFileDialog,  # noqa: E402
                               QMessageBox)

if QApplication.instance() is None:
    QApplication(sys.argv[:1])


@pytest.fixture()
def window():
    """A fresh window per test.

    Each test drives a menu action against a live document, and the actions
    write into it (sheets, scenes, dimensions): sharing one window would
    make a result depend on which test ran first.
    """
    from views.main_window import MainWindow
    win = MainWindow()
    yield win
    # NEVER close a window holding an edited document: ``closeEvent`` asks
    # to save, and a modal question in a headless run never returns (it hung
    # this file for minutes). The window is disposed with the process.
    win.hide()


def _generate_through_the_screen(window):
    """Open the drawing-set window the menu opens, and run it.

    The menu action opens a window (it does not generate by itself), so a
    test that wants a set has to do what the user does — and asserts
    against the window it got.
    """
    from views.docset_dialog import DocSetDialog
    from core.building import building_of
    dlg = DocSetDialog(window, None,
                       window.viewport.scene)
    dlg._generate()
    return dlg


def _house(win, storeys: int = 2):
    from core.history import History
    from core.building import building_of
    from core.building.builder import build
    from core.building.commands import add_element, add_story
    scene = win.viewport.scene
    history = win.viewport.history
    building = building_of(scene)
    rows = []
    for i in range(storeys):
        history.execute(add_story(f"Tầng {i + 1}", i * 3300.0, 3300.0))
        rows.append(building.stories[-1])
    for i, story in enumerate(rows):
        history.execute(add_element("wall", story["id"], {
            "baseline_start_mm": [0, 0], "baseline_end_mm": [6000, 0],
            "thickness_mm": 200.0, "height_mm": 3300.0, "top_link": "next"}))
        history.execute(add_element("zone", story["id"], {
            "outline_mm": [[0, 0], [6000, 0], [6000, 4000], [0, 4000]],
            "name": f"Phòng {i + 1}"}))
    zone = building.elements[-1]
    _mesh, derived = build(building, zone)
    zone["derived"] = derived
    from core.building.scene_sync import sync
    sync(scene, building)
    return building, scene, history


def test_the_menu_offers_the_whole_office_workflow(window):
    labels = [a.text() for a in window._bim_menu.actions()]
    for wanted in ("Lập hồ sơ tự động…", "Kiểm tra hồ sơ…",
                   "Xuất bộ tờ PDF…", "Bảng thống kê (CSV)…",
                   "Xuất DXF bản vẽ…", "Building panel"):
        assert wanted in labels, wanted


def test_the_pdf_action_writes_the_issued_set(window, tmp_path, monkeypatch):
    """The office's last step: the set as ONE PDF a client can open."""
    building, scene, _history = _house(window)
    monkeypatch.setattr(QMessageBox, "information",
                        staticmethod(lambda *a, **k: None))
    _generate_through_the_screen(window)
    drawn = [s for s in scene.compositions
             if any(str(getattr(f, "view_key", "")).startswith("scene:")
                    for f in s.frames)]
    assert drawn, "lập hồ sơ phải để lại tờ có bản vẽ"
    path = tmp_path / "ho-so.pdf"
    monkeypatch.setattr(QFileDialog, "getSaveFileName",
                        staticmethod(lambda *a, **k: (str(path), "")))
    window._on_export_sheets_pdf()
    assert path.exists() and path.stat().st_size > 5000
    assert path.read_bytes().startswith(b"%PDF")


def test_the_pdf_action_says_so_when_there_is_nothing_to_issue(
        window, monkeypatch):
    """An empty document must get a word, not a zero-page file."""
    told: list = []
    monkeypatch.setattr(QMessageBox, "information",
                        staticmethod(lambda *a, **k: told.append(a)))
    monkeypatch.setattr(QMessageBox, "question",
                        staticmethod(lambda *a, **k: QMessageBox.No))
    window._on_export_sheets_pdf()
    assert told, "chưa có tờ thì phải báo"


def test_generating_the_docset_from_the_menu_fills_the_sheets(
        window, monkeypatch):
    """A complete house needs no question: it generates and says how many."""
    building, scene, _history = _house(window)
    asked: list = []
    told: list = []
    monkeypatch.setattr(QMessageBox, "question",
                        staticmethod(lambda *a, **k: asked.append(a)
                                     or QMessageBox.Yes))
    monkeypatch.setattr(QMessageBox, "information",
                        staticmethod(lambda *a, **k: told.append(a)))
    started = len(scene.compositions)
    dlg = _generate_through_the_screen(window)
    assert len(scene.compositions) > started
    assert any(sheet.frames for sheet in scene.compositions)
    assert not asked, "hồ sơ đủ thì không hỏi gì"
    # The result is stated where it is read — in the window's own list.
    steps = [dlg.step_list.item(i).text()
             for i in range(dlg.step_list.count())]
    assert any("Đã sinh" in s for s in steps), steps[-3:]


def test_the_menu_states_an_incomplete_set_before_generating(
        window, monkeypatch):
    """A missing wall is stated BEFORE the run, in the window that runs it."""
    _building, scene, _history = _house(window, storeys=1)
    # A storey with nothing on it: the check calls that a WARNING (a plan
    # with no walls is an empty sheet, which looks like success until it is
    # printed). A missing room is only an INFO — an office may legitimately
    # not have zoned the model yet, and that must not block the run.
    from core.building import building_of
    building = building_of(scene)
    building.elements[:] = []
    from views.docset_dialog import DocSetDialog
    building = building_of(scene)
    building.elements[:] = []
    before = list(scene.compositions)
    dlg = DocSetDialog(window, None, scene)
    warnings = [t for t, sev in dlg.issues if sev == "warn"]
    assert warnings, "thiếu tường phải được nói trước khi sinh"
    assert any("tường" in t for t in warnings), warnings
    # …and the run has not happened yet: the screen runs only when asked.
    assert list(scene.compositions) == before
    dlg.close()


def test_the_check_reports_before_anything_is_written(window, monkeypatch):
    """An empty model must be told, not silently given nothing."""
    shown: list = []
    monkeypatch.setattr(QMessageBox, "information",
                        staticmethod(lambda *a, **k: shown.append(a)))
    window._on_check_docset()              # no storeys: the word goes out
    assert shown
    assert any("tầng" in str(arg) for arg in shown[0])


def test_the_takeoff_grows_a_csv_the_vietnamese_excel_opens(
        window, tmp_path, monkeypatch):
    building, scene, _history = _house(window)
    path = tmp_path / "thong-ke.csv"
    monkeypatch.setattr(
        QFileDialog, "getSaveFileName",
        staticmethod(lambda *a, **k: (str(path), "")))
    monkeypatch.setattr(QMessageBox, "information",
                        staticmethod(lambda *a, **k: None))
    window._on_export_takeoff_csv()
    # Read the BYTES: ``read_text`` translates newlines, so a test that
    # asserts CRLF through it would pass on a file Excel chokes on.
    raw = path.read_bytes()
    assert raw.startswith(b"\xef\xbb\xbf")      # the BOM Excel needs
    assert b";" in raw and b"\r\n" in raw
    assert "THỐNG KÊ TƯỜNG".encode("utf-8") in raw


def test_the_dxf_action_writes_a_drawing(window, tmp_path, monkeypatch):
    building, scene, _history = _house(window, storeys=2)
    path = tmp_path / "mat-bang.dxf"
    monkeypatch.setattr(
        QFileDialog, "getSaveFileName",
        staticmethod(lambda *a, **k: (str(path), "")))
    monkeypatch.setattr(QMessageBox, "information",
                        staticmethod(lambda *a, **k: None))
    window._on_export_plan_dxf()
    assert path.exists()
    import ezdxf
    doc = ezdxf.readfile(str(path))
    msp = doc.modelspace()
    kinds = {}
    for entity in msp:
        kinds[entity.dxftype()] = kinds.get(entity.dxftype(), 0) + 1
    # The drawing the office sends has all four: linework, the section
    # hatch, the dimensions and the text. Asserting only "some LINE
    # exists" would pass with three of them silently gone.
    assert kinds.get("LINE", 0) > 0
    assert kinds.get("HATCH", 0) > 0, "mặt cắt phải có hatch"
    assert kinds.get("DIMENSION", 0) > 0, "phải có kích thước"
    layers = {e.dxf.layer for e in msp}
    assert "KT-CUT" in layers and "KT-HATCH" in layers


def test_the_docset_screen_shows_the_check_before_it_runs(window):
    """The office reads what the set will miss BEFORE generating it."""
    from views.docset_dialog import DocSetDialog
    building, scene, _history = _house(window)
    _story, _zone = building, None
    dlg = DocSetDialog(window, building, scene)
    assert dlg.issues, "nhà mẫu còn thiếu phòng nên phải có điểm lưu ý"
    texts = [dlg.step_list.item(i).text()
             for i in range(dlg.step_list.count())]
    assert texts == [], "chưa bấm Lập hồ sơ thì chưa có bước nào"
    dlg._generate()
    steps = [dlg.step_list.item(i).text()
             for i in range(dlg.step_list.count())]
    assert any("Trang bìa" in s for s in steps)
    assert dlg.docset is not None and dlg.docset.sheets
    drawn = [s for s in dlg.docset.sheets if s.frames]
    assert drawn, "phải có tờ mang bản vẽ"
    dlg.close()


def test_the_docset_screen_honours_its_options(window):
    """Unticking the elevation must remove its sheet, not just its label."""
    from views.docset_dialog import DocSetDialog
    building, scene, _history = _house(window)
    dlg = DocSetDialog(window, building, scene)
    dlg.elev_box.setChecked(False)
    dlg.sect_box.setChecked(False)
    dlg.annot_box.setChecked(False)
    dlg._generate()
    names = [s.name for s in dlg.docset.sheets]
    assert not any("Mặt đứng" in n for n in names)
    assert not any("Mặt cắt" in n for n in names)
    dlg.close()


def test_the_docset_screen_limits_the_issue_to_the_ticked_storeys(window):
    from views.docset_dialog import DocSetDialog
    building, scene, _history = _house(window)
    dlg = DocSetDialog(window, building, scene)
    assert len(dlg.story_boxes) >= 2, "nhà mẫu có nhiều tầng"
    dlg.story_boxes[1][1].setChecked(False)
    dlg._generate()
    names = " | ".join(s.name for s in dlg.docset.sheets)
    second = str(building.story(dlg.story_boxes[1][0]).get("name"))
    assert f"Mặt bằng — {second}" not in names
    dlg.close()


def test_the_docset_screen_reports_a_blank_sheet_instead_of_hiding_it(window):
    """A blank sheet that ships is the failure this screen must name."""
    from views.docset_dialog import DocSetDialog
    building, scene, _history = _house(window)
    dlg = DocSetDialog(window, building, scene)
    dlg._generate()
    texts = [dlg.step_list.item(i).text()
             for i in range(dlg.step_list.count())]
    assert any("Đã sinh" in t for t in texts), texts[-3:]
    assert not any("Tờ chưa có nội dung" in t for t in texts), \
        "bộ tờ này không được phát hành tờ trắng nào"
    dlg.close()


def test_the_menu_offers_the_library_details(window, monkeypatch):
    """The standard details must be reachable from the menu, and leave
    editable items on a sheet — not a picture of a detail."""
    from PySide6.QtWidgets import QComboBox, QDialog, QMessageBox
    from core.building import detail_lib as DL
    building, scene, _history = _house(window)
    _generate_through_the_screen(window)
    sheet = scene.compositions[-1]
    before = (len(sheet.shapes), len(sheet.etiquetas))
    monkeypatch.setattr(QDialog, "exec",
                        lambda self: QDialog.Accepted)
    told: list = []
    monkeypatch.setattr(QMessageBox, "information",
                        staticmethod(lambda *a, **k: told.append(a)))
    window._on_insert_library_detail()
    assert told, "phải xác nhận đã đặt chi tiết"
    assert (len(sheet.shapes), len(sheet.etiquetas)) != before
    assert sheet.shapes and sheet.etiquetas
    assert any(str(t.list_name).startswith("__detail__") for t in sheet.texts)
    del QComboBox, DL


def test_the_panel_names_an_element_it_could_not_build(window):
    """A silent absence is the worst thing a parametric tool can do: an
    element that fails must be said out loud, where the user is looking."""
    from core.building import building_of
    from core.building.commands import add_element
    from core.building.scene_sync import sync
    from views.building_panel import BuildingPanel

    building, scene, history = _house(window)
    sid = str(building.stories[0]["id"])
    # A door whose host wall does not exist: it cannot be cut into anything.
    history.execute(add_element(
        "door", sid, {"host_wall_id": "khong-co",
                      "offset_along_wall_mm": 1000.0,
                      "width_mm": 900.0, "height_mm": 2200.0},
        rebuild=lambda s, b: sync(s, b)))
    panel = BuildingPanel(window)
    assert panel.warnings.isVisibleTo(panel), "phải hiện cảnh báo"
    assert "không dựng được" in panel.warnings.text()
    assert "tường chủ" in panel.warnings.text()


def test_the_docset_window_follows_the_model_after_an_undo(window):
    """The window is non-modal on purpose: the user may undo while it is
    open. It must then describe the model as it IS, not the one it was
    opened for — a cached Building would issue a set for a deleted model."""
    from core.building import model as M
    from core.building.commands import add_story
    from views.docset_dialog import DocSetDialog

    scene = window.viewport.scene
    before = len(M.building_of(scene).stories)
    window.viewport.history.execute(add_story("Tầng mới", 0.0, 3300.0))
    dlg = DocSetDialog(window, scene=scene)
    assert len(dlg.building.stories) == before + 1
    window.viewport.history.undo()
    assert len(dlg.building.stories) == before, \
        "cửa sổ phải đọc mô hình hiện tại, không phải bản lúc mở"
    dlg.close()


def test_the_bim_context_menu_answers_the_office_s_questions():
    """Right-clicking a wall's 3D body must offer the WALL's entries — its
    kind, its parameters, the openings it hosts — not the mesh's. The 3D
    knows groups and the building knows elements; the join is the same key
    the rebuild uses, so a selection never resolves by name."""
    from PySide6.QtCore import QPoint
    from PySide6.QtWidgets import QMenu

    from core.building import samples as S
    from core.building.model import building_of
    from core.building.scene_sync import group_for
    from views.main_window import MainWindow

    win = MainWindow()
    scene = win.viewport.scene
    S.build_sample(win.viewport.history, scene, "townhouse")
    building = building_of(scene)
    wall = next(e for e in building.elements if e.get("type") == "wall")
    group = group_for(scene, wall["id"])
    assert group is not None
    scene.select([group])
    assert [e["id"] for e in win._bim_selection(scene.selection)] == \
        [wall["id"]]

    menu = QMenu(win)
    win._build_bim_context_menu(menu, win._bim_selection(scene.selection))
    labels = [a.text() for a in menu.actions()]
    assert any("Sửa" in t for t in labels), labels
    hosts = [a.menu() for a in menu.actions() if a.menu()]
    assert hosts, "tường phải có nhánh «Trong cấu kiện này»"
    assert "Trong cấu kiện này" in [a.text() for a in menu.actions()
                                    if a.menu()]

    # and a non-BIM selection gets no BIM branch at all
    assert win._bim_selection([]) == []
    win.hide()


def test_select_same_kind_takes_the_whole_storey():
    from core.building import samples as S
    from core.building.model import building_of
    from views.main_window import MainWindow

    win = MainWindow()
    scene = win.viewport.scene
    S.build_sample(win.viewport.history, scene, "townhouse")
    building = building_of(scene)
    story = building.active_story() or building.stories[0]
    expected = len([e for e in building.elements
                    if str(e.get("story_id")) == str(story["id"])
                    and e.get("type") == "wall"])
    assert expected > 1
    win._bim_select_same_kind({"wall"})
    assert len(scene.selection) == expected
    win.hide()


def test_the_seven_workspace_groups_are_built_from_the_registry():
    """The workspace claims seven groups of commands. The menu is built
    FROM `registry.LIST`, so a command added there appears without a
    second edit — and a command this build cannot run is DISABLED with a
    reason instead of doing nothing when clicked."""
    from core.building import registry

    from views.main_window import MainWindow

    win = MainWindow()
    menus = getattr(win, "_bim_group_menus", {})
    assert set(menus) == {str(g[0]) for g in registry.GROUPS}, sorted(menus)
    total = sum(len(m.actions()) for m in menus.values())
    expected = len([row for row in registry.LIST if len(row) > 2])
    assert total == expected, (total, expected)
    for menu in menus.values():
        for action in menu.actions():
            if action.isEnabled():
                continue
            assert action.toolTip(), action.text()
            assert "chưa có" in action.toolTip(), action.text()
    win.hide()


def test_a_plan_command_in_the_menu_opens_the_plan_and_arms_the_tool():
    """`Dimension` is a real command whose points come from the PLAN: the
    menu entry must open the window and arm the tool, not select a 3D
    tool that cannot measure."""
    from views.main_window import MainWindow

    win = MainWindow()
    document = win._bim_group_menus["document"]
    action = next(a for a in document.actions() if a.text() == "Dimension")
    assert action.isEnabled()
    action.trigger()
    plan = getattr(win, "_plan_window", None)
    assert plan is not None, "bấm Dimension mà không mở cửa sổ Plan"
    assert type(plan._draft).__name__ == "DimensionTool"
    plan.cancel_draft()
    plan.hide()
    win.hide()


def test_the_stair_tool_builds_a_stair_and_reports_a_bad_riser():
    """The stair is the one design command that had no tool. Its riser
    count follows the STOREY's own height, so the builder's warning
    (outside 150-190 mm) has to reach the person drawing it — a warning
    nobody sees may as well not exist."""
    from PySide6.QtGui import QVector3D

    from core.building import samples as S
    from core.building.model import building_of
    from views.main_window import MainWindow

    win = MainWindow()
    S.build_sample(win.viewport.history, win.viewport.scene, "townhouse")
    assert "stair" in win._tools
    tool = win._tools["stair"]
    tool.start = QVector3D(1.0, 1.0, 0.0)
    tool.end = QVector3D(1.0, 4.0, 0.0)
    tool._finish(win.viewport)
    building = building_of(win.viewport.scene)
    stair = next(e for e in building.elements if e.get("type") == "stair")
    params = stair["params"]
    assert params["path_mm"] == [[1000.0, 1000.0], [1000.0, 4000.0]]
    assert float(params["height_mm"]) == 3300.0, "chiều cao phải lấy từ tầng"
    derived = stair.get("derived") or {}
    assert derived.get("treads")
    if derived.get("warn"):
        assert "150" in win.statusBar().currentMessage(), \
            "cảnh báo bậc thang không tới người dựng"
    win.hide()
