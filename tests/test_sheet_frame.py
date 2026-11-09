# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Marco Sumari Tellez and IngeTrazo contributors.
"""Khung tờ giấy — the border and title block, on ONE sheet.

Issuing the whole set puts a frame on every sheet it makes; a sheet drawn
by hand had none, and «khung tờ giấy» is the command that puts one there.
What these tests hold down is that the block is filled from the JOB's own
data — the same data the issued set prints — and that asking twice does not
stack a second frame on the first.
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


def _sheet(window, name="MẶT BẰNG TẦNG 1", paper="A3"):
    from core.composition import Composicion

    sheet = Composicion(name=name, paper=paper)
    window.viewport.scene.compositions.append(sheet)
    return sheet


def test_the_frame_carries_the_job_s_own_title_block(window):
    """The block is filled from `building.project` — the same data the
    issued set prints, so a hand-framed sheet and an issued one state the
    same job."""
    from core.building import commands as _commands
    from core.building import sheets as _sheets
    from core.building.model import building_of

    window.viewport.history.execute(_commands.set_project(
        {"name": "Nhà phố 25 Lê Lợi", "owner": "Ông Nguyễn Văn A",
         "chief": "KS. Trần B"}))
    sheet = _sheet(window)
    made = _sheets.sheet_frame(window.viewport.scene,
                               building_of(window.viewport.scene), sheet)

    assert made == {"border": True, "block": True}
    assert sheet.frames, "chưa có khung bao"
    rows = dict(sheet.cajetin.campos)
    assert rows["CÔNG TRÌNH"] == "Nhà phố 25 Lê Lợi"
    assert rows["CHỦ ĐẦU TƯ"] == "Ông Nguyễn Văn A"
    assert rows["CHỦ TRÌ"] == "KS. Trần B"


def test_asking_twice_does_not_stack_a_second_frame(window):
    """A second border inside the first is worse than none: the sheet is
    printed with both."""
    from core.building import sheets as _sheets
    from core.building.model import building_of

    sheet = _sheet(window)
    building = building_of(window.viewport.scene)
    _sheets.sheet_frame(window.viewport.scene, building, sheet)
    again = _sheets.sheet_frame(window.viewport.scene,
                                building_of(window.viewport.scene), sheet)

    assert again == {"border": False, "block": False}
    assert len(sheet.frames) == 1
    assert sheet.cajetin is not None


def test_the_frame_fits_the_sheet_s_own_paper(window):
    """An A4 sheet's block must not hang off the page: the size comes from
    the sheet, never from a constant."""
    from core.building import sheets as _sheets
    from core.building.model import building_of

    for paper in ("A4", "A3", "A2"):
        sheet = _sheet(window, name=f"TỜ {paper}", paper=paper)
        _sheets.sheet_frame(window.viewport.scene,
                            building_of(window.viewport.scene), sheet)
        page_w, page_h = sheet.page_size_mm()
        block = sheet.cajetin
        assert block.x_mm >= 0 and block.y_mm >= 0
        assert block.x_mm + block.w_mm <= page_w + 0.5, paper
        assert block.y_mm + block.h_mm <= page_h + 0.5, paper


def test_the_command_runs_from_the_registry_entry(window, monkeypatch):
    """The layout command must be ENABLED and do the work when clicked —
    a registry id with no path through `_run_bim_command` is a menu entry
    that does nothing."""
    from PySide6.QtWidgets import QMessageBox

    from core.building import commands as _commands
    from core.building.model import building_of
    from core.building.sheets import sheet_frame as _sheet_frame  # noqa: F401

    window.viewport.history.execute(_commands.set_project(
        {"name": "Nhà phố kiểm tra"}))

    action = window._bim_command_action("sheet_frame", window._bim_menu)
    assert action.isEnabled(), "«Khung tờ giấy» vẫn bị mờ"

    # No composer open: the command must SAY so, not do nothing.
    seen: list = []
    monkeypatch.setattr(QMessageBox, "information",
                        staticmethod(lambda *a, **k: seen.append(a[2])))
    window._run_bim_command("sheet_frame", "sheet_frame")
    assert seen and "Bố cục" in seen[-1], seen

    # With a composer showing a sheet, it frames THAT sheet.
    from views.composer import ComposerWindow

    composer = ComposerWindow(window)
    window.composer = composer
    sheet = _sheet(window, name="TỜ THỬ")
    composer.comp = sheet
    window._run_bim_command("sheet_frame", "sheet_frame")
    assert sheet.cajetin is not None
    assert dict(sheet.cajetin.campos)["CÔNG TRÌNH"] == "Nhà phố kiểm tra"
    composer.hide()


# ---- «Vùng vẽ» and «Vùng vẽ» (the drawing area) -------------------------------

def test_a_region_places_a_rule_backed_drawing_on_the_sheet(monkeypatch):
    """«Vùng vẽ» puts the storey being drawn on the sheet in front — as a
    RULE (scene + frame), the way an issued set does it, so the drawing
    keeps agreeing with the model after it is edited. A screenshot would
    not, and the difference is the whole point of the command."""
    from PySide6.QtWidgets import QMessageBox

    from core.building import samples as _samples
    from core.building.model import building_of
    from core.building.sheets import Composicion
    from views.main_window import MainWindow

    win = MainWindow()
    try:
        _samples.build_sample(win.viewport.history, win.viewport.scene,
                              "townhouse")
        scene = win.viewport.scene
        sheet = Composicion(name="Tờ thử", paper="A3", landscape=True)
        scene.compositions.append(sheet)

        class _Composer:
            comp = sheet

            def refresh(self):
                pass

        win.composer = _Composer()
        seen = []
        monkeypatch.setattr(QMessageBox, "information",
                            staticmethod(lambda *a, **k: seen.append(a[2])))
        monkeypatch.setattr(QMessageBox, "warning",
                            staticmethod(lambda *a, **k: seen.append(a[2])))

        before = len(scene.saved_views)
        win._run_sheet_command("region")

        assert len(sheet.frames) == 1, "không có khung nào được đặt"
        frame = sheet.frames[0]
        assert str(frame.view_key).startswith("scene:"), frame.view_key
        # The scene it names is the drawing's own rule, and it is REAL:
        # placed on the document, so reopening the file brings it back.
        name = str(frame.view_key[6:])
        saved = next((v for v in scene.saved_views if v.name == name), None)
        assert saved is not None, name
        assert saved.drawing, "cảnh không mang quy tắc vẽ nào"
        assert len(scene.saved_views) >= before
        assert "Tầng 1" in seen[-1], seen[-1]
    finally:
        win.hide()


def test_the_master_area_reports_the_sheet_s_own_numbers(monkeypatch):
    """The drawing area's numbers are the SHEET's — its paper, its margin
    and the area the drawings actually cover — not a guess and not a
    constant: an A3 with a 10 mm margin is 400 × 277 mm of usable page."""
    from PySide6.QtWidgets import QMessageBox

    from core.building.samples import build_sample
    from core.building.sheets import Composicion
    from views.main_window import MainWindow

    win = MainWindow()
    try:
        build_sample(win.viewport.history, win.viewport.scene, "townhouse")
        scene = win.viewport.scene
        sheet = Composicion(name="Tờ thử", paper="A3", landscape=True)
        sheet.margin_mm = 10.0
        scene.compositions.append(sheet)

        class _Composer:
            comp = sheet

            def refresh(self):
                pass

        win.composer = _Composer()
        seen = []
        monkeypatch.setattr(QMessageBox, "information",
                            staticmethod(lambda *a, **k: seen.append(a[2])))
        monkeypatch.setattr(QMessageBox, "warning",
                            staticmethod(lambda *a, **k: seen.append(a[2])))

        win._run_sheet_command("master_area")
        text = seen[-1].replace("\n", " | ")
        assert "A3" in text, text
        assert "400" in text and "277" in text, text
        assert "0.0%" in text or "%" in text, text
    finally:
        win.hide()
