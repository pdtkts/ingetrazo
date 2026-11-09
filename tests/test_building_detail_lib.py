# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Marco Sumari Tellez and IngeTrazo contributors.
"""The detail library — the standard details an office reissues per job."""
from __future__ import annotations

from core.building import detail_lib as DL
from core.building import patterns as P
from core.composition import Composicion


def test_the_library_covers_the_details_an_office_keeps():
    """The six families every set carries, by name, in Vietnamese."""
    names = " | ".join(DL.name(k) for k in DL.keys())
    for wanted in ("sàn", "mái", "thang", "cửa", "vệ sinh"):
        assert wanted in names, f"thiếu chi tiết: {wanted}"


def test_every_layer_hatches_with_a_pattern_that_exists():
    """A band naming a pattern the table does not have would vanish from
    the drawing, which reads as a hole in the build-up."""
    for key in DL.keys():
        _rect, layers = DL.stack_rect(key)
        assert layers, key
        for label, pattern, y0, y1 in layers:
            assert y1 > y0, f"{key}/{label}: bề dày phải dương"
            if pattern:
                assert pattern in P.PATTERNS, f"{key}/{label}: {pattern}"


def test_a_stack_is_contiguous_from_its_own_floor():
    """Bands must join edge to edge: a gap is a drawing mistake the office
    would read as a second material."""
    for key in DL.keys():
        _rect, layers = DL.stack_rect(key)
        y = 0.0
        for _label, _pattern, y0, y1 in layers:
            assert abs(y0 - y) < 1e-9, f"{key}: hở giữa các lớp tại {y0}"
            y = y1


def test_the_callout_carries_the_thickness_the_layer_states():
    out = DL.annotation("roof_flat")
    text = " | ".join(t for t, _y in out)
    assert "120 mm" in text          # the concrete slab of the roof
    assert "100 mm" in text          # the brick heat barrier
    assert "4 mm" in text            # the membrane


def test_a_detail_lands_on_the_sheet_as_editable_items():
    """Not a baked picture: the office can drag it and restyle it."""
    sheet = Composicion(name="KT13-01 Chi tiết")
    made = DL.insert_detail_on_sheet(sheet, "floor_tile")
    assert made["bands"] == len(DL.detail("floor_tile")["layers"])
    assert made["labels"] == made["bands"]
    assert len(sheet.shapes) == made["bands"]
    assert len(sheet.etiquetas) == made["bands"]
    assert sheet.texts and "1:10" in sheet.texts[-1].text
    # The scale is a parameter, and the drawing follows it.
    other = Composicion(name="x")
    at20 = DL.insert_detail_on_sheet(other, "floor_tile", scale_denom=20.0)
    assert at20["h_mm"] < made["h_mm"]


def test_the_detail_survives_the_round_trip_through_the_document():
    """A detail placed on a sheet is part of the .igz like any item."""
    sheet = Composicion(name="KT13-02")
    DL.insert_detail_on_sheet(sheet, "stair_step")
    again = Composicion.from_dict(sheet.to_dict())
    assert len(again.shapes) == len(sheet.shapes)
    assert len(again.etiquetas) == len(sheet.etiquetas)
    assert again.shapes[0].list_name.startswith("__detail__stair_step")


def test_inserting_the_same_detail_twice_replaces_it():
    """A second insert is a re-place, not a second copy: the items carry
    the detail's own key, so the old stack goes first."""
    from core.composition import Composicion

    sheet = Composicion()
    first = DL.insert_detail_on_sheet(sheet, DL.keys()[0], x_mm=40.0)
    again = DL.insert_detail_on_sheet(sheet, DL.keys()[0], x_mm=40.0)
    assert again["bands"] == first["bands"]
    assert len(sheet.shapes) == first["bands"], \
        f"chi tiết bị chồng: {len(sheet.shapes)} mảng"
    assert len(sheet.texts) == 1
