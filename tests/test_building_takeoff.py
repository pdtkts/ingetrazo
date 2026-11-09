# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Marco Sumari Tellez and IngeTrazo contributors.
"""The takeoff tables and the CSV the office actually opens.

Each test states the invariant it protects. The quantities come from the
element builders' own ``derived`` numbers, so these tests are what keeps the
table and the geometry from drifting apart.
"""
from __future__ import annotations

import pytest

from core.building import building_of
from core.building.commands import add_element, add_story
from core.building.scene_sync import sync
from core.building.takeoff import HEADERS, all_csv, tables, to_csv
from core.history import History
from core.scene import Scene


@pytest.fixture()
def house() -> Scene:
    """A one-storey building: wall + door + slab + column + beam + room."""
    scene = Scene()
    history = History(scene)
    history.execute(add_story("Tầng 1", 0.0, 3300.0))
    story = building_of(scene).stories[0]["id"]
    history.execute(add_element("wall", story, {
        "baseline_start_mm": [0, 0], "baseline_end_mm": [6000, 0],
        "thickness_mm": 200.0, "height_mm": 3300.0, "top_link": "none",
        "building_material_id": "gach", "name": "W1"}))
    wall_id = building_of(scene).elements[0]["id"]
    history.execute(add_element("door", story, {
        "host_wall_id": wall_id, "offset_along_wall_mm": 3000.0,
        "width_mm": 900.0, "height_mm": 2200.0, "sill_height_mm": 0.0,
        "name": "D1"}))
    history.execute(add_element("slab", story, {
        "outline_mm": [[0, 0], [6000, 0], [6000, 4000], [0, 4000]],
        "thickness_mm": 120.0, "building_material_id": "btct"}))
    history.execute(add_element("column", story, {
        "center_mm": [1000, 1000], "shape": "rect", "width_mm": 220.0,
        "depth_mm": 220.0, "top_link": "none", "height_mm": 3300.0}))
    history.execute(add_element("beam", story, {
        "start_mm": [0, 2000], "end_mm": [6000, 2000],
        "width_mm": 220.0, "depth_mm": 300.0, "top_link": "none",
        "height_mm": 3300.0}))
    history.execute(add_element("zone", story, {
        "outline_mm": [[0, 0], [6000, 0], [6000, 4000], [0, 4000]],
        "name": "Phòng khách", "number": "01", "category": "phong_khach"}))
    sync(scene)
    return scene


def test_wall_row_area_is_the_gross_elevation_area(house):
    """The wall table bills the gross elevation area (openings are their own
    line): 6.0 m × 3.3 m = 19.8 m²."""
    row = tables(building_of(house))["walls"][0]
    assert row["Dài (m)"] == 6.0
    assert row["Cao (m)"] == 3.3
    assert row["Diện tích (m²)"] == 19.8
    assert row["Vật liệu"] == "Gạch xây"


def test_openings_table_counts_identical_openings(house):
    """Two identical doors bill as one row with Số lượng 2 — the way a door
    schedule is written."""
    history = History(house)
    wall_id = building_of(house).elements[0]["id"]
    story = building_of(house).stories[0]["id"]
    history.execute(add_element("door", story, {
        "host_wall_id": wall_id, "offset_along_wall_mm": 4500.0,
        "width_mm": 900.0, "height_mm": 2200.0, "sill_height_mm": 0.0,
        "name": "D1"}))
    rows = tables(building_of(house))["openings"]
    assert len(rows) == 1
    assert rows[0]["Số lượng"] == 2
    assert rows[0]["Rộng (mm)"] == 900


def test_slab_volume_is_area_times_thickness(house):
    """24.0 m² × 0.12 m = 2.88 m³ — the concrete the slab bills."""
    row = tables(building_of(house))["slabs"][0]
    assert row["Diện tích (m²)"] == 24.0
    assert row["Thể tích (m³)"] == 2.88


def test_totals_aggregate_every_table(house):
    totals = tables(building_of(house))["totals"]
    assert totals["wall_area_m2"] == 19.8
    assert totals["slab_volume_m3"] == 2.88
    assert totals["door_count"] == 1
    assert totals["window_count"] == 0
    assert totals["room_area_m2"] == 24.0


def test_csv_is_the_way_vietnamese_excel_reads_it(house):
    """`;` separator, a comma decimal mark, a BOM and CRLF — a plain .csv
    opens with the whole table in one column."""
    text = to_csv(building_of(house), "walls")
    assert text.startswith("\ufeff")
    assert "\r\n" in text
    assert ";" in text
    assert "3,3" in text           # 3.3 m as the decimal comma
    assert list(HEADERS["walls"])[0] in text


def test_every_table_has_the_declared_headers(house):
    data = tables(building_of(house))
    for which, headers in HEADERS.items():
        rows = data[which]
        assert rows, which
        assert set(rows[0]) == set(headers), which


def test_all_csv_carries_every_table(house):
    text = all_csv(building_of(house))
    for title in ("THỐNG KÊ PHÒNG", "THỐNG KÊ CỬA", "THỐNG KÊ TƯỜNG",
                  "THỐNG KÊ SÀN", "THỐNG KÊ CỘT", "THỐNG KÊ DẦM"):
        assert title in text
