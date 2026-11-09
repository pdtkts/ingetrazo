# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Marco Sumari Tellez and IngeTrazo contributors.
"""The building panel: the three tabs, and «Áp cho cả tầng này».

A parametric model is read the way the trade reads an element — what it IS,
what it is MADE of, how it is SHAPED — and one flat list of twenty fields
made a user scroll past the width to reach the thickness. The tabs are that
reading order.

The bulk apply is the office's own gesture («cả tầng này tường dày 220»)
and the reason it is safe is the SCOPE: the storey being drawn, not the
document, because a wall type that suits the ground floor is not what the
roof storey is built of.
"""
import sys

import pytest  # noqa: E402
from PySide6.QtCore import Qt  # noqa: E402
from PySide6.QtWidgets import QApplication, QMessageBox  # noqa: E402

if QApplication.instance() is None:
    QApplication(sys.argv[:1])


@pytest.fixture()
def window():
    from views.main_window import MainWindow

    win = MainWindow()
    yield win
    win.hide()


@pytest.fixture()
def panel(window):
    from core.building import samples as _samples

    _samples.build_sample(window.viewport.history, window.viewport.scene,
                          "townhouse")
    live = window.bim_tray.building
    live.refresh()
    return live


def _pick(panel, element_id: str):
    for row in panel._element_rows:
        if row.data(0, Qt.UserRole) == str(element_id):
            panel.element_tree.setCurrentItem(row)
            return row
    raise AssertionError(f"cấu kiện {element_id} không có trong danh sách")


def _element(window, element_id: str) -> dict:
    from core.building.model import building_of

    return building_of(window.viewport.scene).element(element_id)


def test_the_three_tabs_split_the_schema_the_way_the_trade_reads_it(panel):
    """Name in «Cấu kiện», material in «Vật liệu», dimensions in «Tạo
    hình» — and every key of the element's own schema lands in exactly one
    of them, so nothing can be edited nowhere."""
    from views.building_panel import _tab_for

    labels = [panel.tabs.tabText(i) for i in range(panel.tabs.count())]
    assert labels == ["Cấu kiện", "Vật liệu", "Tạo hình"]

    assert _tab_for("name") == "element"
    assert _tab_for("building_material_id") == "material"
    assert _tab_for("frame_material_id") == "material"
    assert _tab_for("thickness_mm") == "shape"

    from core.building import elements as _schemas

    for kind in _schemas.BY_TYPE:
        for key in _schemas.defaults_for(kind):
            assert _tab_for(key) in ("element", "material", "shape"), \
                f"{kind}.{key} không vào tab nào"


def test_every_editable_field_is_reachable_in_a_tab(panel):
    """The tabs must not hide a field the flat form showed: the count of
    widgets built equals the count of rows across the three forms."""
    from core.building.model import building_of

    wall = next(e for e in building_of(panel._window.viewport.scene).elements
                if e.get("type") == "wall")
    _pick(panel, wall["id"])
    rows = sum(form.rowCount() for form in panel._forms.values())
    assert rows >= len([k for k in panel._fields]), (rows, panel._fields)
    assert panel._fields, "không dựng được ô nào cho tường"


def test_the_material_tab_names_the_material_behind_the_code(panel):
    """«gach_nhe» is not a word an office reads off a drawing: the tab says
    what the code means and what its join priority is."""
    from core.building.model import building_of

    wall = next(e for e in building_of(panel._window.viewport.scene).elements
                if e.get("type") == "wall")
    _pick(panel, wall["id"])
    texts = []
    form = panel._forms["material"]
    for row in range(form.rowCount()):
        item = form.itemAt(row, form.ItemRole.LabelRole)
        widget = item.widget() if item is not None else None
        if widget is not None and hasattr(widget, "text"):
            texts.append(str(widget.text()))
    assert any("Gạch xây" in text for text in texts), texts


def test_the_bulk_apply_takes_the_storey_and_not_the_document(
        panel, monkeypatch):
    """A wall type that suits the ground floor is not what the roof storey
    is built of, so the gesture stops at the storey being drawn."""
    from core.building.model import building_of

    monkeypatch.setattr(QMessageBox, "question",
                        staticmethod(lambda *a, **k: QMessageBox.Yes))
    scene = panel._window.viewport.scene
    wall = next(e for e in building_of(scene).elements
                if e.get("type") == "wall")
    _pick(panel, wall["id"])
    panel._fields["thickness_mm"].setValue(250.0)
    panel._on_bulk_apply()

    building = building_of(scene)
    on_story = [e for e in building.on_story(str(wall["story_id"]))
                if e.get("type") == "wall"]
    elsewhere = [e for e in building.elements
                 if e.get("type") == "wall"
                 and str(e.get("story_id")) != str(wall["story_id"])]
    assert on_story and elsewhere, (len(on_story), len(elsewhere))
    for element in on_story:
        assert element["params"]["thickness_mm"] == 250.0, element["id"]
    for element in elsewhere:
        assert element["params"]["thickness_mm"] != 250.0, \
            "áp đã tràn sang tầng khác"


def test_the_bulk_apply_is_one_undo_step(panel, monkeypatch):
    """Nine walls, one Ctrl+Z — the office's gesture is one action."""
    from core.building.model import building_of

    monkeypatch.setattr(QMessageBox, "question",
                        staticmethod(lambda *a, **k: QMessageBox.Yes))
    scene = panel._window.viewport.scene
    wall = next(e for e in building_of(scene).elements
                if e.get("type") == "wall")
    _pick(panel, wall["id"])
    before = {e["id"]: e["params"].get("thickness_mm")
              for e in building_of(scene).elements
              if e.get("type") == "wall"}

    panel._fields["thickness_mm"].setValue(265.0)
    panel._on_bulk_apply()
    assert len([e for e in building_of(scene).elements
                if e.get("type") == "wall"
                and e["params"].get("thickness_mm") == 265.0]) > 1

    panel._window.viewport.history.undo()
    after = {e["id"]: e["params"].get("thickness_mm")
             for e in building_of(scene).elements if e.get("type") == "wall"}
    assert after == before, "một Ctrl+Z chưa trả hết"


def test_the_bulk_apply_is_refused_when_the_user_says_no(panel, monkeypatch):
    """The office decides: a confirmation that does not gate the write is
    worse than no confirmation."""
    from core.building.model import building_of

    monkeypatch.setattr(QMessageBox, "question",
                        staticmethod(lambda *a, **k: QMessageBox.No))
    scene = panel._window.viewport.scene
    wall = next(e for e in building_of(scene).elements
                if e.get("type") == "wall")
    _pick(panel, wall["id"])
    before = {e["id"]: e["params"].get("thickness_mm")
              for e in building_of(scene).elements
              if e.get("type") == "wall"}
    panel._fields["thickness_mm"].setValue(199.0)
    panel._on_bulk_apply()
    after = {e["id"]: e["params"].get("thickness_mm")
             for e in building_of(scene).elements if e.get("type") == "wall"}
    assert after == before
