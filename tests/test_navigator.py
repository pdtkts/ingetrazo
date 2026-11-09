# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Marco Sumari Tellez and IngeTrazo contributors.
"""The Navigator: project, views, sheets and publisher, over live data."""
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


def _house(win, storeys: int = 2):
    from core.building import building_of
    from core.building.commands import add_element, add_story
    from core.building.scene_sync import sync

    scene = win.viewport.scene
    history = win.viewport.history
    rebuild = lambda s, b: sync(s, b)            # noqa: E731 — a fixture
    building = building_of(scene)
    building.project["name"] = "Nhà phố"
    rows = []
    for i in range(storeys):
        history.execute(add_story(f"Tầng {i + 1}", i * 3300.0, 3300.0))
        rows.append(building_of(scene).stories[-1])
    for story in rows:
        history.execute(add_element("wall", story["id"], {
            "baseline_start_mm": [0, 0], "baseline_end_mm": [6000, 0],
            "thickness_mm": 200.0, "height_mm": 3300.0}, rebuild=rebuild))
    return building_of(scene), scene, history


def test_the_navigator_has_the_four_tabs_of_a_bim_workspace(window):
    """Project, views, sheets, publisher: the four questions the workspace
    answers all day, in the order the work happens in."""
    nav = window._navigator_panel
    titles = [nav.tabs.tabText(i) for i in range(nav.tabs.count())]
    assert titles == ["Dự án", "Bản vẽ", "Bộ tờ", "Phát hành"]
    assert nav.tabs.count() == 4


def test_the_project_tab_reads_the_building_it_has_now(window):
    """Storeys by elevation, elements under each, counts — and it follows
    the model rather than a snapshot taken when the dock opened."""
    building, _scene, history = _house(window, storeys=1)
    nav = window._navigator_panel
    nav.refresh()
    root = nav.project_tree.topLevelItem(0)
    assert root.text(0) == "Nhà phố"
    assert root.childCount() == 1
    storey = root.child(0)
    assert "Tầng 1" in storey.text(0)
    assert "+0.000 m" in storey.text(0)
    assert storey.childCount() == 1                       # one trade: walls
    assert "Wall" in storey.child(0).text(0)
    assert "(1)" in storey.child(0).text(0)
    del building


def test_the_project_tab_adds_a_storey_when_the_model_gains_one(window):
    from core.building.commands import add_story

    _b, _s, history = _house(window, storeys=1)
    nav = window._navigator_panel
    history.execute(add_story("Tầng 2", 3300.0, 3300.0))
    window.viewport.notify_scene_changed()
    root = nav.project_tree.topLevelItem(0)
    assert root.childCount() == 2, "Navigator không theo mô hình"


def test_the_layout_tab_lists_the_sheets_the_set_issued(window):
    from core.building import docset as DS
    from core.building import sheets as S

    building, scene, _h = _house(window, storeys=1)
    S.ensure_sheets(scene, building)
    nav = window._navigator_panel
    nav.refresh()
    root = nav.layout_tree.topLevelItem(0)
    names = [root.child(i).text(0) for i in range(root.childCount())]
    assert root.text(0).endswith(f"({len(scene.compositions)})")
    assert any(n.startswith("KT00") for n in names), names
    generated = [root.child(i) for i in range(root.childCount())
                 if root.child(i).toolTip(0)]
    assert generated, "tờ do máy sinh phải nói rõ điều đó"
    del DS


def test_the_view_tab_lists_the_saved_scenes(window):
    from core.building import docset as DS
    from core.saved_views import SavedView

    scene = window.viewport.scene
    scene.saved_views.append(SavedView("Góc nhìn của tôi",
                                       target=(1.0, 2.0, 3.0)))
    _b, _s, _h = _house(window, storeys=1)
    nav = window._navigator_panel
    nav.refresh()
    root = nav.view_tree.topLevelItem(0)
    names = [root.child(i).text(0) for i in range(root.childCount())]
    assert any("Góc nhìn của tôi" in n for n in names), names
    del DS


def test_a_double_click_on_a_storey_makes_it_the_active_one(window):
    """«Go to this storey» is the one write the dock makes: it is a
    navigator, not an editor."""
    from core.building import building_of

    _b, scene, _h = _house(window, storeys=2)
    nav = window._navigator_panel
    nav.refresh()
    first = nav.project_tree.topLevelItem(0).child(0)
    label = first.text(0)                    # read before the activate:
    nav._on_activate(first)                  # the refresh rebuilds the tree
    active = building_of(scene).active_story()
    assert active is not None
    assert active["name"] in label


def test_a_double_click_on_an_element_selects_it_in_the_model(window):
    _b, scene, _h = _house(window, storeys=1)
    nav = window._navigator_panel
    nav.refresh()
    leaf = (nav.project_tree.topLevelItem(0).child(0).child(0).child(0))
    assert leaf.childCount() == 0
    nav._on_activate(leaf)
    assert scene.selection, "bấm đúp cấu kiện phải chọn nó trong mô hình"


def test_the_publisher_rows_run_the_app_s_own_commands(window):
    """The dock does not reimplement the exports: it triggers the menu's
    actions, so a command added there is reachable here unchanged."""
    nav = window._navigator_panel
    nav.refresh()
    root = nav.publisher_tree.topLevelItem(0)
    labels = [root.child(i).text(0) for i in range(root.childCount())]
    assert labels, "tab Phát hành phải có lệnh"
    menu_labels = [a.text() for a in window._bim_menu.actions()]
    for label in labels:
        assert label in menu_labels, f"{label!r} không có trong menu BIM"


def test_the_navigator_owns_no_data_of_its_own(window):
    """Every tab is a view over the document: nothing to fall out of step."""
    _b, scene, _h = _house(window, storeys=1)
    nav = window._navigator_panel
    scene.saved_views.clear()
    scene.compositions.clear()
    nav.refresh()
    assert nav.view_tree.topLevelItem(0).childCount() == 0
    assert nav.layout_tree.topLevelItem(0).childCount() == 0


def test_the_workspace_toggle_brings_the_bim_environment_forward(window):
    """One key switches between modelling and issuing documents: the
    Navigator and the Building panel come forward, and go away again."""
    action = window._act_bim_workspace
    assert action.isCheckable()
    window._toggle_workspace(True)
    assert not window.navigator.isHidden()
    assert not window.bim_tray.isHidden()
    window._toggle_workspace(False)
    assert window.navigator.isHidden()
    assert window.bim_tray.isHidden()


def test_the_workspace_choice_is_remembered(window):
    """It is a preference, like every other panel visibility here."""
    from PySide6.QtCore import QSettings

    window._toggle_workspace(True)
    assert bool(QSettings().value("ui/bim_workspace", False, type=bool))
    window._toggle_workspace(False)
    assert not bool(QSettings().value("ui/bim_workspace", False, type=bool))
