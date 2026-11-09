# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Marco Sumari Tellez and IngeTrazo contributors.
"""Doors, windows, curtain walls, roofs, stairs and fixtures.

The invariants worth protecting are: an opening's body lands exactly where
its host wall cut the hole, a stair's riser stays inside the trade's range,
and a roof refuses an outline it cannot build instead of drawing nonsense.
"""
from __future__ import annotations

import pytest

from core.building import builder
from core.building.model import Building


@pytest.fixture()
def two_storeys() -> Building:
    b = Building()
    b.add_story("Tầng 1", 0.0, 3300.0)
    b.add_story("Tầng 2", 3300.0, 3300.0)
    return b


@pytest.fixture()
def wall(two_storeys) -> dict:
    b = two_storeys
    return b.add_element("wall", b.stories[0]["id"], {
        "baseline_start_mm": [0, 0], "baseline_end_mm": [6000, 0],
        "thickness_mm": 200.0, "height_mm": 3300.0, "top_link": "next",
        "building_material_id": "gach"})


def test_a_door_body_sits_in_its_host_wall(two_storeys, wall):
    """The opening's frame is the host's, so the leaf cannot drift out of the
    hole when the wall is edited."""
    b = two_storeys
    door = b.add_element("door", b.stories[0]["id"], {
        "host_wall_id": wall["id"], "offset_along_wall_mm": 3000.0,
        "width_mm": 900.0, "height_mm": 2200.0, "sill_height_mm": 0.0})
    mesh, derived = builder.build(b, door)
    assert len(mesh.faces) > 0
    xs = [v.position.x() * 1000.0 for f in mesh.faces for v in f.loop]
    assert min(xs) >= 2549.0 and max(xs) <= 3451.0      # inside its opening
    assert derived["area_m2"] == pytest.approx(1.98)


def test_a_window_keeps_its_sill(two_storeys, wall):
    b = two_storeys
    win = b.add_element("window", b.stories[0]["id"], {
        "host_wall_id": wall["id"], "offset_along_wall_mm": 1500.0,
        "width_mm": 1200.0, "height_mm": 1200.0, "sill_height_mm": 900.0})
    mesh, derived = builder.build(b, win)
    zs = [v.position.z() * 1000.0 for f in mesh.faces for v in f.loop]
    assert min(zs) >= 900.0 - 0.01      # float32 positions
    assert derived["sill_height_mm"] == 900.0


def test_a_curtain_wall_carries_its_grid(two_storeys, wall):
    b = two_storeys
    cw = b.add_element("curtain_wall", b.stories[0]["id"], {
        "host_wall_id": wall["id"], "offset_along_wall_mm": 4000.0,
        "width_mm": 2000.0, "height_mm": 2400.0, "sill_height_mm": 0.0,
        "col_count": 3, "row_count": 2})
    mesh, derived = builder.build(b, cw)
    assert derived["cells"] == 6
    assert derived["glass_area_m2"] < derived["area_m2"]


def test_a_roof_lifts_to_its_pivot_and_slopes(two_storeys):
    """On the top storey there is no storey above, so the plate sits at the
    level; its slope adds area, which the takeoff must bill."""
    b = two_storeys
    roof = b.add_element("roof", b.stories[1]["id"], {
        "outline_mm": [[0, 0], [8000, 0], [8000, 6000], [0, 6000]],
        "slope_deg": 30.0, "overhang_mm": 0.0, "thickness_mm": 150.0,
        "top_link": "next", "height_mm": 3300.0})
    mesh, derived = builder.build(b, roof)
    assert len(mesh.faces) == 6
    assert derived["pivot_mm"] == pytest.approx(3300.0)
    assert derived["slope_area_m2"] > derived["area_m2"]


def test_a_roof_refuses_a_concave_outline(two_storeys):
    """An L-shaped roof is several roofs; building it as one would be wrong
    geometry, so it is refused in words the user can act on."""
    b = two_storeys
    roof = b.add_element("roof", b.stories[0]["id"], {
        "outline_mm": [[0, 0], [5000, 0], [5000, 5000], [2500, 2500],
                       [0, 5000]], "slope_deg": 20.0})
    with pytest.raises(ValueError):
        builder.build(b, roof)


def test_a_stair_rises_to_the_storey_above_within_the_trade_range(two_storeys):
    """20 treads over 3.3 m gives a 157 mm riser — inside 150–190, so no
    warning is raised and the walker's foot is where the code expects it."""
    b = two_storeys
    stair = b.add_element("stair", b.stories[0]["id"], {
        "path_mm": [[0, 0], [0, 3000], [2000, 3000]], "width_mm": 1000.0,
        "tread_mm": 260.0, "waist_mm": 150.0})
    mesh, derived = builder.build(b, stair)
    assert derived["treads"] == 20
    assert 150.0 <= derived["riser_mm"] <= 190.0
    assert derived["warn"] is None
    # The last riser reaches the next floor: the top TREAD is one riser
    # below it, which is what walking the stair to arrive upstairs means.
    zs = [v.position.z() * 1000.0 for f in mesh.faces for v in f.loop]
    assert max(zs) == pytest.approx(3300.0 - derived["riser_mm"], abs=1.0)


def test_a_stair_warns_when_the_riser_leaves_the_range(two_storeys):
    b = two_storeys
    b.stories[1]["z_mm"] = 4400.0          # a tall storey: long risers
    stair = b.add_element("stair", b.stories[0]["id"], {
        "path_mm": [[0, 0], [0, 3000]], "width_mm": 1000.0,
        "tread_mm": 260.0})
    _mesh, derived = builder.build(b, stair)
    assert derived["warn"]


def test_a_fixture_is_turned_by_its_angle(two_storeys):
    b = two_storeys
    fx = b.add_element("fixture", b.stories[0]["id"], {
        "center_mm": [1000.0, 1000.0], "width_mm": 500.0,
        "depth_mm": 700.0, "height_mm": 584.0, "z_mm": 0.0,
        "angle_deg": 90.0})
    mesh, derived = builder.build(b, fx)
    assert len(mesh.faces) == 6
    xs = [v.position.x() * 1000.0 for f in mesh.faces for v in f.loop]
    # Turned 90°, the body's 700 mm depth now runs along X.
    assert max(xs) - min(xs) == pytest.approx(700.0, abs=1.0)
    assert derived["volume_m3"] == pytest.approx(0.2044, abs=1e-4)
