# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Marco Sumari Tellez and IngeTrazo contributors.
"""The Schedule: the takeoff read where the model is, not in a CSV file."""
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

    history = win.viewport.history
    rebuild = lambda s, b: sync(s, b)            # noqa: E731 — a fixture
    rows = []
    for i in range(storeys):
        history.execute(add_story(f"Tầng {i + 1}", i * 3300.0, 3300.0))
        rows.append(building_of(win.viewport.scene).stories[-1])
    for i, story in enumerate(rows):
        history.execute(add_element("wall", story["id"], {
            "baseline_start_mm": [0, 0], "baseline_end_mm": [6000, 0],
            "thickness_mm": 200.0, "height_mm": 3300.0}, rebuild=rebuild))
        history.execute(add_element("zone", story["id"], {
            "outline_mm": [[0, 0], [6000, 0], [6000, 4000], [0, 4000]],
            "name": f"Phòng {i + 1}"}, rebuild=rebuild))
        history.execute(add_element("slab", story["id"], {
            "outline_mm": [[0, 0], [6000, 0], [6000, 4000], [0, 4000]],
            "thickness_mm": 120.0}, rebuild=rebuild))
    door_host = building_of(win.viewport.scene).elements[0]
    history.execute(add_element("door", rows[0]["id"], {
        "host_wall_id": door_host["id"], "offset_along_wall_mm": 3000.0,
        "width_mm": 900.0, "height_mm": 2200.0, "name": "D1"},
        rebuild=rebuild))
    return building_of(win.viewport.scene), history


def test_the_schedule_has_a_table_per_trade(window):
    from views.schedule_dialog import open_schedule

    _b, _h = _house(window, storeys=1)
    dialog = open_schedule(window)
    titles = [dialog.kind_box.itemText(i)
              for i in range(dialog.kind_box.count())]
    assert titles == ["Phòng — diện tích", "Cửa đi & cửa sổ", "Tường",
                      "Sàn", "Cột", "Dầm"]
    dialog.close()


def test_the_columns_are_the_table_s_own_headings(window):
    """The rows carry their headings — they are what the CSV writes — so
    the dialog reads them off the data: one definition, and a figure added
    to the takeoff appears here without an edit."""
    from core.building.takeoff import tables as takeoff_tables
    from views.schedule_dialog import open_schedule

    building, _h = _house(window, storeys=1)
    dialog = open_schedule(window)
    dialog.kind_box.setCurrentIndex(2)                   # Tường
    shown = [dialog.table.horizontalHeaderItem(c).text()
             for c in range(dialog.table.columnCount())]
    wanted = list((takeoff_tables(building).get("walls") or [{}])[0].keys())
    assert shown == wanted, shown
    dialog.close()


def test_the_storey_box_filters_the_table(window):
    from views.schedule_dialog import open_schedule

    _b, _h = _house(window, storeys=2)
    dialog = open_schedule(window)
    dialog.kind_box.setCurrentIndex(2)                   # Tường
    everything = dialog.table.rowCount()
    dialog.story_box.setCurrentIndex(1)                  # a storey
    filtered = dialog.table.rowCount()
    assert 0 < filtered < everything, (filtered, everything)
    names = {dialog.table.item(r, 0).text()
             for r in range(dialog.table.rowCount())}
    assert names == {dialog.story_box.currentText()}, names
    dialog.close()


def test_the_filter_box_narrows_by_any_word(window):
    from views.schedule_dialog import open_schedule

    _b, _h = _house(window, storeys=2)
    dialog = open_schedule(window)
    dialog.kind_box.setCurrentIndex(0)                   # Phòng — diện tích
    assert dialog.table.rowCount() == 2
    dialog.filter.setText("Phòng 2")
    assert dialog.table.rowCount() == 1
    assert "Phòng 2" in dialog.table.item(0, 2).text()
    dialog.close()


def test_the_table_follows_the_model(window):
    """A schedule is read WHILE the model is edited; it re-reads on the
    app's own signal rather than showing the numbers of an hour ago."""
    from core.building.commands import add_story
    from views.schedule_dialog import open_schedule

    _b, history = _house(window, storeys=1)
    dialog = open_schedule(window)
    dialog.kind_box.setCurrentIndex(2)                   # Tường
    before = dialog.table.rowCount()
    history.execute(add_story("Tầng 2", 3300.0, 3300.0))
    window.viewport.notify_scene_changed()
    assert dialog.story_box.count() >= 3, "bảng không theo mô hình"
    assert dialog.table.rowCount() >= before
    dialog.close()


def test_the_numbers_are_the_takeoff_s_own(window):
    """The figure on screen and the figure a printed bill shows come from
    one source; a schedule that recomputed them could disagree."""
    from core.building.takeoff import tables as takeoff_tables
    from views.schedule_dialog import open_schedule

    building, _h = _house(window, storeys=1)
    dialog = open_schedule(window)
    dialog.kind_box.setCurrentIndex(3)                   # Sàn
    area_column = [dialog.table.horizontalHeaderItem(c).text()
                   for c in range(dialog.table.columnCount())]
    at = area_column.index("Diện tích (m²)")
    shown = float(dialog.table.item(0, at).text().replace(" ", "")
                  .replace(",", "."))
    wanted = float((takeoff_tables(building)["slabs"][0])["Diện tích (m²)"])
    assert abs(shown - wanted) < 0.01, (shown, wanted)
    dialog.close()


def test_the_window_is_reused_not_stacked(window):
    from views.schedule_dialog import open_schedule

    _b, _h = _house(window, storeys=1)
    first = open_schedule(window)
    again = open_schedule(window)
    assert first is again
    first.close()


def test_the_menu_opens_the_schedule(window):
    labels = [a.text() for a in window._bim_menu.actions()]
    assert "Bảng thống kê tương tác…" in labels
    window._on_open_schedule()
    assert window._schedule_dialog is not None
    window._schedule_dialog.close()
