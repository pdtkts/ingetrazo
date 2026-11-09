# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Marco Sumari Tellez and IngeTrazo contributors.
"""Thông tin dự án — the job's own data, and the title block it prints on.

The title block is the sheet's identity, and the whole set prints it: the
point of editing it in ONE place is that forty sheets cannot disagree. What
these tests hold down is that editing reaches the model (one undo step),
that a blank field really goes blank rather than sticking, and that the
rows it edits are the rows the title block draws.
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


def _project(window) -> dict:
    from core.building.model import building_of

    return building_of(window.viewport.scene).project


def test_the_dialog_writes_the_project_data_in_one_undo_step(window):
    from views.project_dialog import ProjectInfoDialog

    dialog = ProjectInfoDialog(window)
    dialog._edits["name"].setText("Nhà phố 3 tầng — 25 Lê Lợi")
    dialog._edits["owner"].setText("Ông Nguyễn Văn A")
    assert not _project(window).get("name")

    dialog._save()
    assert _project(window)["name"] == "Nhà phố 3 tầng — 25 Lê Lợi"
    assert _project(window)["owner"] == "Ông Nguyễn Văn A"

    window.viewport.history.undo()
    assert not _project(window).get("name"), "Ctrl+Z còn tên công trình"
    window.viewport.history.redo()
    assert _project(window)["name"] == "Nhà phố 3 tầng — 25 Lê Lợi"


def test_emptying_a_field_really_empties_it(window):
    """The command merges, so a field the user cleared has to be written
    as empty rather than simply left out — otherwise the old value stays
    and the title block keeps printing a name the office deleted."""
    from views.project_dialog import ProjectInfoDialog

    dialog = ProjectInfoDialog(window)
    dialog._edits["name"].setText("Công trình cũ")
    dialog._save()

    second = ProjectInfoDialog(window)
    assert second._edits["name"].text() == "Công trình cũ"
    second._clear()
    assert _project(window).get("name") == "", _project(window)


def test_the_fields_the_dialog_edits_are_rows_the_title_block_prints(window):
    """A field collected here that the title block never draws is a field
    the user fills in for nothing."""
    from core.building import sheets as _sheets
    from views.project_dialog import FIELDS

    printed = {key for _label, key in _sheets.TITLE_ROWS}
    # ``name`` is the block's main band, ``item``/``owner``/``designer``/
    # ``chief``/``date`` are rows, and the rest are the block's own
    # numbering — every key the dialog writes must land somewhere.
    # ``name`` is the block's own main band (the row the trade reads
    # first), and ``code`` numbers the SHEET, not the block. Every other
    # key the dialog writes must be a row the block draws.
    for key, _label, _hint in FIELDS:
        if key in ("name", "code", "address", "revision"):
            continue
        assert key in printed, f"«{key}» không có dòng nào trên khung tên"


def test_the_investor_is_a_row_of_the_vietnamese_title_block(window):
    """The investor is who the set is drawn for; a Vietnamese title block
    carries them, and the office's own number goes with them."""
    from core.building import sheets as _sheets
    from core.composition import Composicion

    sheet = Composicion()
    _sheets.title_block(
        sheet, {"name": "Nhà phố", "owner": "Ông Nguyễn Văn A",
                "item": "Nhà ở riêng lẻ", "chief": "KS. Trần B"},
        _sheets.SheetSpec(key="x", group="plan", label="L",
                          title="MẶT BẰNG"), "KT-01")
    rows = dict(sheet.cajetin.campos)
    assert rows["CHỦ ĐẦU TƯ"] == "Ông Nguyễn Văn A"
    assert list(rows)[:3] == ["CÔNG TRÌNH", "HẠNG MỤC", "CHỦ ĐẦU TƯ"]


def test_the_project_name_reaches_an_issued_export(window, tmp_path):
    """The name the dialog writes is the one an exchange file carries."""
    from core.building import samples as _samples
    from core.building.model import building_of
    from formats.ifc import save_building_ifc
    from views.project_dialog import ProjectInfoDialog

    _samples.build_sample(window.viewport.history, window.viewport.scene,
                          "townhouse")
    dialog = ProjectInfoDialog(window)
    dialog._edits["name"].setText("Nhà phố 25 Lê Lợi")
    dialog._save()

    out = tmp_path / "job.ifc"
    save_building_ifc(window.viewport.scene, str(out))
    text = out.read_text(encoding="utf-8", errors="replace")
    # IFC is ISO-10303-21: a Vietnamese name travels as \X2\ escapes, so
    # the check decodes them before looking for the job's own name.
    import re as _re

    def decode(value: str) -> str:
        def expand(match):
            return "".join(chr(int(match.group(0)[i:i + 4], 16))
                           for i in range(4, len(match.group(0)) - 4, 4))

        return _re.sub(r"\\X2\\(?:[0-9A-F]{4})+\\X0\\", expand, value)

    names = [decode(part) for part in _re.findall(r"'(?:[^']|'')*'", text)]
    assert any("Nhà phố 25 Lê Lợi" in n for n in names), names[:8]
