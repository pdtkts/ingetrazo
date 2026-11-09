# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Marco Sumari Tellez and IngeTrazo contributors.
"""Trục: the grid a building is laid out from, written as a model element."""
from __future__ import annotations

import os
import sys

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

if QApplication.instance() is None:
    QApplication(sys.argv[:1])


@pytest.fixture()
def house():
    from core.building import samples as S
    from core.building.model import building_of
    from views.main_window import MainWindow

    win = MainWindow()
    S.build_sample(win.viewport.history, win.viewport.scene, "townhouse")
    yield win, building_of(win.viewport.scene)
    win.hide()


def test_axes_come_from_the_walls_the_way_a_house_actually_is(house):
    """«Từ tường đã dựng»: a rectilinear house has its grid where its
    walls are, so the first draft is those positions — named in order,
    numbers across and letters down, the way the trade reads them."""
    from views.grid_dialog import derive_axes

    _win, building = house
    story_id = str(building.stories[0]["id"])
    axes = derive_axes(building, story_id)
    assert axes, "nhà có tường mà không lấy được trục nào"
    vertical = [a for a in axes if a["dir"] == "y"]
    horizontal = [a for a in axes if a["dir"] == "x"]
    assert vertical and horizontal, "một nhà phải ra cả hai họ trục"
    assert [a["name"] for a in vertical] == [
        str(i + 1) for i in range(len(vertical))]
    assert [a["name"] for a in horizontal][0] == "A"
    # A 6×4 m house: the axes stand on its own wall lines.
    assert [a["offset_mm"] for a in vertical] == [0.0, 6000.0]
    assert [a["offset_mm"] for a in horizontal] == [0.0, 4000.0]


def test_the_grid_is_a_model_element_not_a_drawing_note(house):
    """It is what a section mark, a sheet and a colleague on site all
    refer to, so it is an element of the building: one undo step, saved
    with the document, rebuilt by the same sync as any other."""
    from core.building.model import building_of
    from views.grid_dialog import GridDialog, existing_grid

    win, building = house
    story_id = str(building.stories[0]["id"])
    assert existing_grid(building, story_id) is None

    dialog = GridDialog(win, story_id)
    dialog._fill_from_walls()
    dialog._save()
    scene = win.viewport.scene
    rebuilt = building_of(scene)
    element = existing_grid(rebuilt, story_id)
    assert element is not None, "trục chưa vào mô hình"
    assert element.get("type") == "grid"
    assert len(element["params"]["axes"]) == 4
    assert (element.get("derived") or {}).get("axis_count") == 4

    # ONE undo takes the whole grid back
    assert win.viewport.history.undo()
    assert existing_grid(building_of(scene), story_id) is None


def test_a_grid_written_twice_is_edited_not_doubled(house):
    """A second visit to the dialog edits the grid the storey has."""
    from core.building.model import building_of
    from views.grid_dialog import GridDialog, existing_grid

    win, building = house
    story_id = str(building.stories[0]["id"])
    first = GridDialog(win, story_id)
    first._fill_from_walls()
    first._save()
    count = len(existing_grid(building_of(win.viewport.scene),
                              story_id)["params"]["axes"])
    second = GridDialog(win, story_id)
    assert second.table.rowCount() == count, "lần mở sau không thấy lưới cũ"
    second._add_axis()
    second.table.item(count, 0).setText("C")
    second.table.cellWidget(count, 2).setValue(8000.0)
    second._save()
    rebuilt = building_of(win.viewport.scene)
    grids = [e for e in rebuilt.elements if e.get("type") == "grid"]
    assert len(grids) == 1, "thêm một lưới nữa thay vì sửa lưới cũ"
    assert len(grids[0]["params"]["axes"]) == count + 1


def test_a_duplicate_or_empty_axis_name_is_refused(house):
    from core.building.model import building_of
    from views.grid_dialog import GridDialog, existing_grid

    win, building = house
    story_id = str(building.stories[0]["id"])
    dialog = GridDialog(win, story_id)
    dialog._fill_from_walls()
    dialog.table.item(1, 0).setText(dialog.table.item(0, 0).text())
    dialog._save()
    assert "trùng" in dialog.status.text()
    assert existing_grid(building_of(win.viewport.scene), story_id) is None

    dialog2 = GridDialog(win, story_id)
    dialog2._fill_from_walls()
    dialog2.table.item(0, 0).setText("   ")
    dialog2._save()
    assert "tên" in dialog2.status.text()
    assert existing_grid(building_of(win.viewport.scene), story_id) is None


def test_the_grid_reaches_the_sheet_and_survives_the_file(house, tmp_path):
    """The point of the grid is that the drawing carries it: a plan read
    on site must show the axes and the bubbles with the names the office
    used."""
    from core.building.drawings import draw_grid, view_for
    from core.building.model import building_of
    from formats.igz import load_into, save_scene
    from core.scene import Scene
    from views.grid_dialog import GridDialog

    win, building = house
    scene = win.viewport.scene
    story_id = str(building.stories[0]["id"])
    dialog = GridDialog(win, story_id)
    dialog._fill_from_walls()
    dialog._save()

    rebuilt = building_of(scene)
    view = view_for(rebuilt, {"kind": "story", "story_id": story_id})
    made = draw_grid(scene, rebuilt, view, key="sheet·grid")
    bubbles = [e for e in made if getattr(e, "text", None)]
    assert {str(b.text) for b in bubbles} == {"1", "2", "A", "B"}
    assert len(scene.mesh.edges) == 4, "mỗi trục một nét"

    doc = tmp_path / "grid.igz"
    save_scene(scene, doc)
    back = Scene()
    load_into(back, doc)
    grid = [e for e in building_of(back).elements if e.get("type") == "grid"]
    assert grid and len(grid[0]["params"]["axes"]) == 4
    assert len(back.mesh.edges) == 4


def test_the_menu_has_the_grid_editor(house):
    win, _building = house
    labels = [a.text() for a in win._bim_menu.actions()]
    assert "Trục…" in labels
