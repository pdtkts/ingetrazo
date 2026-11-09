# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Marco Sumari Tellez and IngeTrazo contributors.
"""The Schedule: the takeoff as a table you can read, sort and re-filter.

A CSV is a file you leave the app to read; a schedule is the same numbers
where the model is, updating as the model does. It is deliberately one
dialog over ``core.building.takeoff.tables`` — the same source the CSV and
the sheet index read — so a figure it shows and a figure a printed bill
shows cannot be two different numbers.
"""
from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtGui import QFont
from PySide6.QtWidgets import (QComboBox, QDialog,
                               QDialogButtonBox, QHBoxLayout, QLabel,
                               QLineEdit, QTableWidget, QTableWidgetItem,
                               QVBoxLayout)

from core.i18n import tr

#: ``(table key, Vietnamese title)`` in the order a bill is read.
TABLES = (
    ("zones", "Phòng — diện tích"),
    ("openings", "Cửa đi & cửa sổ"),
    ("walls", "Tường"),
    ("slabs", "Sàn"),
    ("columns", "Cột"),
    ("beams", "Dầm"),
)

#: The column widths the office reads at, by heading, where the default is
#: too tight (the rows carry their own headings — this dialog does not
#: invent a second set that could drift from the CSV's).
WIDTHS = {
    "Tầng": 110, "Tên phòng": 220, "Mã": 90, "Loại": 120,
    "Diện tích (m²)": 120, "Thực tế (m²)": 120, "Trừ lỗ mở (m²)": 120,
    "Thể tích (m³)": 120, "Khối tích (m³)": 120, "Dài (m)": 90,
    "Dày (mm)": 90, "Cao (m)": 90, "Rộng (mm)": 90, "Cao (mm)": 90,
    "Số lượng": 90, "Tiết diện": 120, "Vật liệu": 140,
}


class ScheduleDialog(QDialog):
    """One window, one table at a time, filtered by storey and by words."""

    def __init__(self, window) -> None:
        super().__init__(window)
        self.setWindowTitle(tr("Bảng thống kê"))
        self.resize(960, 560)
        self._window = window
        self._tables: dict = {}
        self._story_ids: list = []

        lay = QVBoxLayout(self)
        head = QHBoxLayout()
        head.addWidget(QLabel(tr("Bảng:")))
        self.kind_box = QComboBox()
        for key, title in TABLES:
            self.kind_box.addItem(tr(title), key)
        self.kind_box.currentIndexChanged.connect(lambda _i: self._fill())
        head.addWidget(self.kind_box)
        head.addWidget(QLabel(tr("Tầng:")))
        self.story_box = QComboBox()
        self.story_box.currentIndexChanged.connect(lambda _i: self._fill())
        head.addWidget(self.story_box)
        self.filter = QLineEdit()
        self.filter.setPlaceholderText(tr("Lọc theo từ khoá…"))
        self.filter.textChanged.connect(lambda _t: self._fill())
        head.addWidget(self.filter, 1)
        lay.addLayout(head)

        self.table = QTableWidget(0, 0)
        self.table.setSortingEnabled(True)
        self.table.setAlternatingRowColors(True)
        self.table.setEditTriggers(QTableWidget.NoEditTriggers)
        self.table.verticalHeader().setVisible(False)
        lay.addWidget(self.table, 1)

        self.summary = QLabel("")
        self.summary.setProperty("role", "muted")
        lay.addWidget(self.summary)

        buttons = QDialogButtonBox(QDialogButtonBox.Close)
        buttons.rejected.connect(self.reject)
        csv = buttons.addButton(tr("Xuất CSV…"), QDialogButtonBox.ActionRole)
        csv.clicked.connect(self._export_csv)
        lay.addWidget(buttons)

        self.refresh()
        # A schedule is read WHILE the model is edited, so it follows the
        # app's own version signal rather than showing the numbers of an
        # hour ago. showEvent keeps it current when a hidden window is
        # brought back, which is the other half of «follow».
        viewport = getattr(window, "viewport", None)
        version = getattr(viewport, "sceneVersionChanged", None)
        if version is not None:
            version.connect(lambda _v: self.refresh())

    def showEvent(self, event) -> None:               # noqa: N802 — Qt
        super().showEvent(event)
        self.refresh()

    # ---- data ------------------------------------------------------------
    def _building(self):
        from core.building.model import building_of

        return building_of(self._window.viewport.scene)

    def refresh(self) -> None:
        """Re-read the model and refill: the table follows the building."""
        from core.building.takeoff import tables as takeoff_tables

        building = self._building()
        keep_story = self.story_box.currentData()
        self._tables = takeoff_tables(building)
        self.story_box.blockSignals(True)
        self.story_box.clear()
        self.story_box.addItem(tr("Tất cả"), "")
        for story in sorted(building.stories,
                            key=lambda s: float(s.get("z_mm", 0.0))):
            self.story_box.addItem(str(story.get("name") or story.get("id")),
                                   str(story.get("id")))
        at = self.story_box.findData(keep_story or "")
        self.story_box.setCurrentIndex(max(at, 0))
        self.story_box.blockSignals(False)
        self._fill()

    def _story_names(self) -> dict:
        """``{story_id: name}`` — the table says the NAME, the box the id."""
        building = self._building()
        return {str(s.get("id") or ""): str(s.get("name") or "")
                for s in building.stories}

    def _rows(self) -> tuple:
        """``(rows, columns)`` of the active table, filtered as asked.

        The rows carry their own headings (they are what the CSV writes),
        so the columns are read off the data instead of declared here —
        one definition, and a new figure in the takeoff appears without an
        edit to this window.
        """
        key = self.kind_box.currentData()
        rows = list(self._tables.get(key) or ())
        story = str(self.story_box.currentData() or "")
        if story:
            name = self._story_names().get(story, "")
            rows = [r for r in rows
                    if str(r.get("Tầng") or "") in (name, story)]
        needle = self.filter.text().strip().lower()
        if needle:
            rows = [r for r in rows
                    if any(needle in str(v).lower() for v in r.values())]
        columns: list = []
        for row in rows:
            for heading in row:
                if heading not in columns:
                    columns.append(heading)
        return rows, columns

    def _fill(self) -> None:
        rows, columns = self._rows()
        # Sorting is off while the table is rebuilt: a live sort would
        # reorder the rows as they are written and pair them with the
        # wrong cells.
        self.table.setSortingEnabled(False)
        self.table.clear()
        self.table.setColumnCount(len(columns))
        self.table.setHorizontalHeaderLabels([str(c) for c in columns])
        self.table.setRowCount(len(rows))
        for r, row in enumerate(rows):
            for c, heading in enumerate(columns):
                value = row.get(heading, "")
                item = QTableWidgetItem(_readable(value))
                item.setTextAlignment(Qt.AlignRight | Qt.AlignVCenter
                                      if isinstance(value, (int, float))
                                      else Qt.AlignLeft | Qt.AlignVCenter)
                self.table.setItem(r, c, item)
        for c, heading in enumerate(columns):
            self.table.setColumnWidth(c, WIDTHS.get(str(heading), 110))
        self.table.setSortingEnabled(True)
        self.summary.setText(
            tr("{n} dòng — nguồn: core.building.takeoff.tables").format(
                n=len(rows)))

    def _export_csv(self) -> None:
        """Hand the same numbers to the app's own CSV export.

        The export writes EVERY table (it is the bill, not the screen), so
        the button says so where a reader would otherwise wonder why the
        file has more in it than the table on screen.
        """
        self._window._on_export_takeoff_csv()


def _readable(value) -> str:
    """A cell's text: numbers to the precision a bill is read at, and a
    blank cell where the model has nothing rather than a «None»."""
    if value is None or value == "":
        return ""
    if isinstance(value, bool):
        return "x" if value else ""
    if isinstance(value, float):
        return f"{value:,.2f}".replace(",", " ")
    if isinstance(value, int):
        return str(value)
    return str(value)


def open_schedule(window) -> ScheduleDialog:
    """The window's one schedule (made on first use, then reused)."""
    existing = getattr(window, "_schedule_dialog", None)
    if existing is not None:
        existing.refresh()
        existing.show()
        existing.raise_()
        return existing
    dialog = ScheduleDialog(window)
    window._schedule_dialog = dialog
    return dialog
