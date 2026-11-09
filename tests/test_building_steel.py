# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Marco Sumari Tellez and IngeTrazo contributors.
"""Thép hình — the rolled-section table, and what it does to a schedule.

A steel member is never specified as «200x100»: the trade names the rolled
section (`H300x150x6.5x9`, TCVN 7571 / JIS G3192), and that name IS the
design — the flange and web thicknesses are what the fabricator orders.
What these tests hold down is that the NAME reaches the schedule and that
the bill is written from the section's own mass per metre, which is the one
number on a rolled section that the geometry does not carry.
"""
import sys

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


def test_the_table_states_the_trade_s_own_sections():
    """The names are the catalogue's, in the order the trade writes them
    (h × b × tw × tf), and every one carries a real mass per metre."""
    from core.building import steel

    assert steel.by_name("H300x150x6.5x9") == (300.0, 150.0, 6.5, 9.0, 37.3)
    assert steel.by_name("khong-co") is None
    assert steel.mass_per_m("khong-co") == 0.0
    for name, row in steel.SECTIONS.items():
        h, b, tw, tf, mass = row
        assert h > b or h == b, name
        assert 0 < tw < h and 0 < tf < h, name
        assert mass > 0, name


def test_the_table_is_grouped_by_family_not_alphabetically():
    """The trade picks by family first («cho tôi cái H»), and an A–Z list
    would put «H100x100x6x8» and «I100x50x5x7» side by side as if they were
    two sizes of one thing."""
    from core.building import steel

    groups = steel.families()
    assert set(groups) >= {"H", "I", "S", "R", "P"}
    assert all(name[0] == letter for letter, names in groups.items()
               for name in names)


def test_adopting_a_section_makes_the_element_that_section():
    """The model takes the section's real dimensions, records its NAME, and
    keeps the web and flange thicknesses — a re-open must not lose them."""
    from core.building import steel

    params = steel.adopt({}, "H300x150x6.5x9")
    assert params["steel_section"] == "H300x150x6.5x9"
    assert {params["width_mm"], params["depth_mm"]} == {150.0, 300.0}
    assert params["steel_web_mm"] == 6.5
    assert params["steel_flange_mm"] == 9.0
    assert params["building_material_id"] == "thep"

    pipe = steel.adopt({}, "P168x5")
    assert pipe["shape"] == "round" and pipe["diameter_mm"] == 168.0

    assert steel.adopt({}, "khong-co") == {}, "tên lạ phải từ chối, không đoán"


def test_the_schedule_names_the_section_a_fabricator_orders(window):
    """«H300x150x6.5x9» is what the schedule must say; «300x150» has thrown
    the thicknesses away and is not a section anyone can order."""
    from core.building import commands as _commands
    from core.building import samples as _samples
    from core.building import steel as _steel
    from core.building import takeoff as _takeoff
    from core.building.model import building_of
    from tools import building_tools as _tools

    _samples.build_sample(window.viewport.history, window.viewport.scene,
                          "townhouse")
    story = building_of(window.viewport.scene).stories[0]

    class _Beam(_tools.BuildingTool):
        kind = "beam"

    _Beam()._commit(window.viewport, _commands.add_element(
        "beam", str(story["id"]),
        dict({"start_mm": [0.0, 0.0], "end_mm": [4000.0, 0.0],
              "name": "D1"}, **_steel.adopt({}, "H300x150x6.5x9"))))

    rows = _takeoff.tables(building_of(window.viewport.scene))["beams"]
    steel_rows = [r for r in rows if "H300" in str(r.get("Tiết diện (b x h)"))]
    assert steel_rows, rows
    row = steel_rows[0]
    # The bill is written from the section's own kg/m: 4.00 m at 37.3 kg/m.
    assert row["KL (kg)"] == pytest.approx(149.2, abs=0.05), row
    assert row["Dài (m)"] == pytest.approx(4.0, abs=0.01)


def test_a_concrete_beam_keeps_its_own_section_reading():
    """A member that never came off the table must not be renamed: the
    table is a reference, not a rewrite of everything that is not steel."""
    from core.building import takeoff as _takeoff

    class _Fake:
        elements = [{"id": "b1", "type": "beam", "story_id": "s1",
                     "params": {"width_mm": 220.0, "depth_mm": 300.0},
                     "derived": {"length_mm": 4000.0}}]
        stories = [{"id": "s1", "name": "Tầng 1"}]

        def story(self, sid):
            return self.stories[0] if str(sid) == "s1" else None

    rows = _takeoff.tables(_Fake())["beams"]
    assert rows and rows[0]["Tiết diện (b x h)"] == "220x300", rows
    assert not rows[0]["KL (kg)"], "dầm bê tông không được ghi khối lượng thép"


def test_the_panel_offers_the_catalogue_as_a_list(window):
    """A rolled section is PICKED, never typed: «H300x150x6.5x9» is four
    dimensions and a mass, and a text field would let a user invent a
    section nobody rolls."""
    from core.building import commands as _commands
    from core.building import samples as _samples
    from core.building import steel as _steel
    from core.building.model import building_of

    _samples.build_sample(window.viewport.history, window.viewport.scene,
                          "townhouse")
    panel = window.bim_tray.building
    story = building_of(window.viewport.scene).stories[0]
    window.viewport.history.execute(_commands.add_element(
        "beam", str(story["id"]),
        dict({"start_mm": [0.0, 0.0], "end_mm": [4000.0, 0.0],
              "name": "D1"}, **_steel.adopt({}, "H300x150x6.5x9"))))
    panel.refresh()

    from PySide6.QtCore import Qt

    beam = next(e for e in building_of(window.viewport.scene).elements
                if e.get("type") == "beam")
    for row in panel._element_rows:
        if row.data(0, Qt.UserRole) == str(beam["id"]):
            panel.element_tree.setCurrentItem(row)
    picker = panel._fields.get("steel_section")
    assert picker is not None, "bảng không có ô tiết diện thép"
    # Every catalogue name plus the «không dùng» way back.
    assert picker.count() == len(_steel.SECTIONS) + 1
    assert picker.currentData() == "H300x150x6.5x9"


def test_choosing_a_section_writes_its_own_dimensions_in_one_step(window):
    """The user asked for the SECTION; leaving them a 300×150 rectangle
    with the thicknesses typed separately is how a drawing ends up with a
    section nobody rolls."""
    from PySide6.QtCore import Qt

    from core.building import commands as _commands
    from core.building import samples as _samples
    from core.building import steel as _steel
    from core.building.model import building_of

    _samples.build_sample(window.viewport.history, window.viewport.scene,
                          "townhouse")
    panel = window.bim_tray.building
    story = building_of(window.viewport.scene).stories[0]
    window.viewport.history.execute(_commands.add_element(
        "beam", str(story["id"]),
        dict({"start_mm": [0.0, 0.0], "end_mm": [4000.0, 0.0]},
             **_steel.adopt({}, "H200x100x5.5x8"))))
    panel.refresh()
    beam = next(e for e in building_of(window.viewport.scene).elements
                if e.get("type") == "beam")
    for row in panel._element_rows:
        if row.data(0, Qt.UserRole) == str(beam["id"]):
            panel.element_tree.setCurrentItem(row)

    picker = panel._fields["steel_section"]
    # A COPY, not the live dict: the command replaces the model's payload,
    # so a held reference would read the NEW values and the assertion would
    # pass whatever happened.
    before = dict(building_of(window.viewport.scene)
                  .element(beam["id"])["params"])
    assert before["steel_section"] == "H200x100x5.5x8"

    picker.setCurrentIndex(picker.findData("H400x200x8x13"))
    after = building_of(window.viewport.scene).element(beam["id"])["params"]
    assert after["steel_section"] == "H400x200x8x13"
    assert {after["width_mm"], after["depth_mm"]} == {200.0, 400.0}
    assert after["steel_web_mm"] == 8.0 and after["steel_flange_mm"] == 13.0

    window.viewport.history.undo()
    back = building_of(window.viewport.scene).element(beam["id"])["params"]
    assert back["steel_section"] == "H200x100x5.5x8", "một Ctrl+Z chưa trả về"
    assert back["width_mm"] == before["width_mm"]
