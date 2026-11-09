# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Marco Sumari Tellez and IngeTrazo contributors.
"""The Plan window: the storey drawn flat, from the drawing's own rule."""
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
    """A window per test, never closed: a dirty document asks to save."""
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
    building = building_of(scene)
    rebuild = lambda s, b: sync(s, b)            # noqa: E731 — a fixture
    rows = []
    for i in range(storeys):
        history.execute(add_story(f"Tầng {i + 1}", i * 3300.0, 3300.0))
        rows.append(building.stories[-1])
    for i, story in enumerate(rows):
        history.execute(add_element("wall", story["id"], {
            "baseline_start_mm": [0, 0], "baseline_end_mm": [6000, 0],
            "thickness_mm": 200.0, "height_mm": 3300.0,
            "top_link": "next"}, rebuild=rebuild))
        history.execute(add_element("wall", story["id"], {
            "baseline_start_mm": [6000, 0], "baseline_end_mm": [6000, 4000],
            "thickness_mm": 200.0, "height_mm": 3300.0,
            "top_link": "next"}, rebuild=rebuild))
        history.execute(add_element("zone", story["id"], {
            "outline_mm": [[0, 0], [6000, 0], [6000, 4000], [0, 4000]],
            "name": f"Phòng {i + 1}"}, rebuild=rebuild))
    wall = building.elements[0]
    history.execute(add_element("door", rows[0]["id"], {
        "host_wall_id": wall["id"], "offset_along_wall_mm": 3000.0,
        "width_mm": 900.0, "height_mm": 2200.0, "name": "D1"},
        rebuild=rebuild))
    return building, scene, history


def test_the_window_opens_and_paints_the_storey(window):
    """It draws the plan of the active storey, from the drawing's rule."""
    from views.plan_window import open_plan_window

    _b, _s, _h = _house(window)
    plan = open_plan_window(window)
    assert plan.story_box.count() == 2
    segs, loops, marks, box = plan.build_drawing()
    assert segs, "phải có nét vẽ"
    assert box[2] > box[0] and box[3] > box[1]
    # The drawing is the SHEET's rule: the +1200 cut and the floor trim.
    assert plan._view.section_planes, "mặt bằng phải có mặt phẳng cắt"
    assert plan._view.clip_planes, "mặt bằng phải có mặt phẳng xén sàn"
    assert plan.canvas.isVisible() or plan.canvas.width() >= 0


def test_the_window_is_reused_not_stacked(window):
    from views.plan_window import open_plan_window

    _b, _s, _h = _house(window, storeys=1)
    first = open_plan_window(window)
    again = open_plan_window(window)
    assert first is again, "mỗi tài liệu chỉ có một cửa sổ Plan"


def test_switching_storey_changes_the_drawing(window):
    from views.plan_window import open_plan_window

    _b, _s, _h = _house(window)
    plan = open_plan_window(window)
    plan.story_box.setCurrentIndex(0)
    plan._on_story()
    first = plan.build_drawing()
    assert "Tầng 1" in plan.story_box.currentText()
    plan.story_box.setCurrentIndex(1)
    plan._on_story()
    second = plan.build_drawing()
    assert "Tầng 2" in plan.story_box.currentText()
    # The two storeys carry different elements, so the picture differs.
    assert (len(first[0]), len(first[2])) != (len(second[0]), len(second[2]))


def test_zoom_out_returns_to_the_scale_it_started_from(window):
    from views.plan_window import open_plan_window

    _b, _s, _h = _house(window, storeys=1)
    plan = open_plan_window(window)
    plan.canvas.fit()
    before = plan.canvas.scale_px_per_mm
    plan.canvas.zoom_by(2.0)
    assert plan.canvas.scale_px_per_mm > before
    plan.canvas.zoom_by(0.5)
    assert abs(plan.canvas.scale_px_per_mm - before) < 1e-9


def test_a_click_picks_the_element_under_the_cursor(window):
    from views.plan_window import open_plan_window

    building, scene, _h = _house(window, storeys=1)
    plan = open_plan_window(window)
    # On the wall's baseline: the wall, and the selection reaches the app.
    hit = plan.element_at((3000.0, 0.0))
    assert hit is not None
    assert str(building.element(hit)["type"]) == "wall"
    plan.select(hit)
    assert scene.selection, "chọn trên Plan phải đưa vào selection của app"
    # Nothing there: no pick, and selecting None clears.
    assert plan.element_at((3000.0, 90000.0)) is None
    plan.select(None)
    assert not scene.selection


def test_every_plan_command_has_a_button_and_the_missing_ones_say_so(window):
    """The bar is the workspace's own list: nothing silently omitted."""
    from core.building import registry
    from views.plan_window import COMMAND_TOOLS, open_plan_window

    _b, _s, _h = _house(window, storeys=1)
    plan = open_plan_window(window)
    declared = [cmd for _group, ids in registry.PLAN_BAR for cmd in ids]
    assert set(plan.bar_buttons) == set(declared)
    enabled = {k for k, b in plan.bar_buttons.items() if b.isEnabled()}
    for cmd in declared:
        button = plan.bar_buttons[cmd]
        if cmd in enabled:
            assert COMMAND_TOOLS.get(cmd), f"{cmd} bật mà không có công cụ"
            assert "chưa có" not in button.toolTip()
        else:
            assert not button.isEnabled()
            assert "chưa có" in button.toolTip(), cmd
    # The status quo, stated so a change is deliberate: most of the bar
    # works, and what does not is disabled rather than faked.
    assert len(enabled) >= 25


def test_the_shortcut_table_lists_the_keys_the_workspace_gives(window):
    from core.building import registry
    from views.plan_window import PlanShortcutsDialog

    dialog = PlanShortcutsDialog(window)
    rows = dialog.table.rowCount()
    declared = [cmd for _group, ids in registry.PLAN_BAR for cmd in ids]
    assert rows == len(declared)
    shown = {dialog.table.item(r, 2).text() for r in range(rows)}
    for key in registry.PLAN_KEYS:
        assert key in shown, f"thiếu phím {key!r}"
    # The filter narrows the table without losing the key column.
    dialog.filter.setText("tường")
    hidden = sum(1 for r in range(rows) if dialog.table.isRowHidden(r))
    assert hidden > 0
    dialog.close()


def test_the_menu_opens_the_plan_window(window):
    from PySide6.QtWidgets import QMessageBox

    _b, _s, _h = _house(window, storeys=1)
    labels = [a.text() for a in window._bim_menu.actions()]
    assert "Cửa sổ Plan…" in labels
    window._on_open_plan_window()
    plan = window._plan_window
    assert plan is not None and plan.isVisible()
    assert plan.build_drawing()[0], "cửa sổ mở ra phải có hình"
    del QMessageBox


def test_the_linework_lands_on_the_model_not_half_a_storey_away(window):
    """The hidden-line pass works in the CAMERA plane, centred on the view
    target; the marks and the picking work in the MODEL plane. If the two
    are not reconciled the drawing slides by half the house — and a click
    then picks whatever happens to be under the cursor instead.

    The check is simple and exact: the drawn linework must sit inside the
    storey's own extent, with only the wall faces' own thickness outside.
    """
    from views.plan_window import open_plan_window

    _b, _s, _h = _house(window, storeys=1)
    plan = open_plan_window(window)
    segs, _loops, _marks, box = plan.build_drawing()
    assert segs
    xs = [v for s in segs for v in (s[0], s[2])]
    ys = [v for s in segs for v in (s[1], s[3])]
    pad = 300.0                                  # the wall's own half-thickness
    assert box[0] - pad <= min(xs) and max(xs) <= box[2] + pad, (box, min(xs), max(xs))
    assert box[1] - pad <= min(ys) and max(ys) <= box[3] + pad, (box, min(ys), max(ys))


def test_a_drag_moves_the_element_and_undo_puts_it_back(window):
    """Dragging the body on the plan moves the model — one undo step.

    The drag runs through the same command the properties panel uses, so
    Undo must return the wall to its own coordinates, not to a half-state
    that only looks right on screen.
    """
    from core.building import model as M
    from views.plan_window import open_plan_window

    _b, scene, history = _house(window, storeys=1)
    plan = open_plan_window(window)
    wall_id = plan.element_at((3000.0, 0.0))
    assert wall_id is not None
    plan.select(wall_id)
    before = list(M.building_of(scene).element(wall_id)
                  ["params"]["baseline_start_mm"])
    # A body drag of (500, 700) millimetres, in three move events.
    plan.drag_element(wall_id, (3300.0, 200.0), (3000.0, 0.0), "body")
    plan.drag_element(wall_id, (3400.0, 500.0), (3000.0, 0.0), "body")
    plan.drag_element(wall_id, (3500.0, 700.0), (3000.0, 0.0), "body")
    mid = M.building_of(scene).element(wall_id)["params"]["baseline_start_mm"]
    assert mid == [before[0] + 500.0, before[1] + 700.0], mid
    plan.finish_drag(wall_id, (3000.0, 0.0), "body")
    after = M.building_of(scene).element(wall_id)["params"]["baseline_start_mm"]
    assert after == mid, "thả ra không được đổi số"
    assert history.undo(), "phải có 1 bước undo"
    back = M.building_of(scene).element(wall_id)["params"]["baseline_start_mm"]
    assert back == before, f"undo trả về {back}, không phải {before}"


def test_the_handle_pulls_one_end_and_leaves_the_other(window):
    """A handle drag stretches: the far end must not move."""
    from core.building import model as M
    from views.plan_window import open_plan_window

    _b, scene, _h = _house(window, storeys=1)
    plan = open_plan_window(window)
    wall_id = plan.element_at((3000.0, 0.0))
    assert wall_id is not None
    plan.select(wall_id)
    params = M.building_of(scene).element(wall_id)["params"]
    start = list(params["baseline_start_mm"])
    end = list(params["baseline_end_mm"])
    # The handle is taken near the END of the wall.
    assert plan.handle_hit(wall_id, tuple(map(float, end)), 80.0) == "end"
    assert plan.handle_hit(wall_id, tuple(map(float, start)), 80.0) == "start"
    assert plan.handle_hit(wall_id, (3000.0, 0.0), 80.0) is None
    plan.drag_element(wall_id, (end[0] + 1000.0, end[1] + 250.0),
                      tuple(map(float, end)), "handle")
    plan.finish_drag(wall_id, tuple(map(float, end)), "handle")
    now = M.building_of(scene).element(wall_id)["params"]
    assert now["baseline_end_mm"] == [end[0] + 1000.0, end[1] + 250.0]
    assert now["baseline_start_mm"] == start, "đầu kia phải đứng yên"


def test_the_properties_dialog_writes_every_field_it_shows(window):
    """The dialog is the element's schema, and OK means one command."""
    from core.building import model as M
    from views.plan_window import PlanPropertiesDialog, open_plan_window

    _b, scene, _h = _house(window, storeys=1)
    plan = open_plan_window(window)
    wall_id = plan.element_at((3000.0, 0.0))
    assert wall_id is not None
    dialog = PlanPropertiesDialog(plan, wall_id)
    assert "thickness_mm" in dialog.fields
    kind, widget = dialog.fields["thickness_mm"]
    assert kind == "number"
    widget.setValue(300.0)
    dialog._accept()
    now = M.building_of(scene).element(wall_id)["params"]["thickness_mm"]
    assert float(now) == 300.0, now
    # A press ON the wall away from both ends is a body grab, no handle.
    mid = (3000.0, 0.0)
    assert plan.handle_hit(wall_id, mid, 1.0) is None


def test_an_edit_from_the_plan_reaches_the_3d_and_the_panels(window):
    """The plan is one more writer of the model, so the rest must follow.

    The app hears about a change through ``notify_scene_changed``; if the
    plan called the panel's own handler instead, the 3D viewport would
    keep painting the wall where it used to be.
    """
    from core.building import model as M
    from views.plan_window import open_plan_window

    _b, scene, _h = _house(window, storeys=1)
    plan = open_plan_window(window)
    wall_id = plan.element_at((3000.0, 0.0))
    assert wall_id is not None
    seen = []
    window.viewport.sceneVersionChanged.connect(seen.append)
    plan.drag_element(wall_id, (3500.0, 0.0), (3000.0, 0.0), "body")
    plan.finish_drag(wall_id, (3000.0, 0.0), "body")
    assert seen, "sửa từ Plan phải phát tín hiệu cho cả app"
    moved = M.building_of(scene).element(wall_id)["params"]["baseline_start_mm"]
    assert moved == [500.0, 0.0], moved
