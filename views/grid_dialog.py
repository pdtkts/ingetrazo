# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Marco Sumari Tellez and IngeTrazo contributors.
"""Trục — the grid a building is laid out from, edited as a model element.

A grid is not a drawing decoration: it is what a drawing, a section mark
and a colleague on site all refer to («trục B»), so it lives in the model
as an element of its own (``type="grid"``, ``build_grid``) and every sheet
reads it from there. This dialog is how the office writes it down: a list
of axes with their names and offsets, plus the two ways a grid is actually
born — drawn by hand, or taken from the walls already standing on the
storey (which is what a rectilinear house needs nine times out of ten).
"""
from __future__ import annotations

from PySide6.QtWidgets import (QComboBox, QDialog, QDialogButtonBox,
                               QDoubleSpinBox, QHBoxLayout, QLabel,
                               QLineEdit, QPushButton, QTableWidget,
                               QTableWidgetItem, QVBoxLayout)

from core.i18n import tr

#: How far a derived axis may stand from a wall's own centreline and still
#: count as «the grid of this wall».
SNAP_MM = 250.0


def existing_grid(building, story_id: str):
    """The grid element of a storey, or ``None``."""
    for element in building.elements:
        if str(element.get("story_id")) == str(story_id) \
                and element.get("type") == "grid":
            return element
    return None


def derive_axes(building, story_id: str) -> list:
    """``[axis, …]`` from the walls standing on the storey.

    Every distinct wall face position becomes an axis: a rectilinear house
    drawn freely has its walls where they were drawn, and the office's grid
    is exactly those positions, named in order. It is a first draft the
    dialog then edits — never a replacement for the office's own naming.
    """
    xs: list = []
    ys: list = []
    for element in building.elements:
        if str(element.get("story_id")) != str(story_id) \
                or element.get("type") != "wall":
            continue
        params = element.get("params") or {}
        for key in ("baseline_start_mm", "baseline_end_mm"):
            point = params.get(key) or []
            if len(point) < 2:
                continue
            xs.append(float(point[0]))
            ys.append(float(point[1]))

    def cluster(values: list) -> list:
        out: list = []
        for value in sorted(values):
            if not out or abs(value - out[-1]) > SNAP_MM:
                out.append(value)
        return out

    axes: list = []
    for i, x in enumerate(cluster(xs)):
        axes.append({"name": str(i + 1), "dir": "y", "offset_mm": round(x, 1)})
    for i, y in enumerate(cluster(ys)):
        axes.append({"name": _letter(i), "dir": "x", "offset_mm": round(y, 1)})
    return axes


def _letter(index: int) -> str:
    name = ""
    n = int(index)
    while True:
        name = chr(ord("A") + n % 26) + name
        n = n // 26 - 1
        if n < 0:
            return name


class GridDialog(QDialog):
    """Write a storey's grid: the axes, their names and where they stand."""

    def __init__(self, window, story_id: str) -> None:
        super().__init__(window)
        self.setWindowTitle(tr("Trục"))
        self.resize(720, 520)
        self._window = window
        self._story_id = str(story_id)
        from core.building.model import building_of

        self._building = building_of(window.viewport.scene)

        lay = QVBoxLayout(self)
        lead = QLabel(tr(
            "Trục là cách cả công trường gọi tên vị trí («trục B»). Khai ở "
            "đây thì mặt bằng, mặt cắt và bảng thống kê đều đọc chung một "
            "bộ trục."))
        lead.setWordWrap(True)
        lead.setProperty("role", "muted")
        lay.addWidget(lead)

        head = QHBoxLayout()
        head.addWidget(QLabel(tr("Tên lưới:")))
        self.name_edit = QLineEdit(tr("Trục"))
        head.addWidget(self.name_edit, 1)
        draw = QPushButton(tr("Từ tường đã dựng"))
        draw.setToolTip(tr(
            "Lấy vị trí các tường trên tầng này làm trục (bản nháp để sửa "
            "lại) — nhà vuông vắn thì gần như xong ngay."))
        draw.clicked.connect(self._fill_from_walls)
        head.addWidget(draw)
        head.addWidget(QLabel(tr("Mới:")))
        self.axis_edit = QLineEdit()
        self.axis_edit.setPlaceholderText(tr("tên, ví dụ 1 hoặc A"))
        self.axis_edit.setMaximumWidth(120)
        head.addWidget(self.axis_edit)
        add = QPushButton(tr("Thêm trục"))
        add.clicked.connect(self._add_axis)
        head.addWidget(add)
        lay.addLayout(head)

        self.table = QTableWidget(0, 3)
        self.table.setHorizontalHeaderLabels(
            [tr("Tên trục"), tr("Chạy theo"), tr("Vị trí (mm)")])
        self.table.verticalHeader().setVisible(False)
        self.table.setAlternatingRowColors(True)
        lay.addWidget(self.table, 1)

        row = QHBoxLayout()
        remove = QPushButton(tr("Xoá trục"))
        remove.clicked.connect(self._remove_axis)
        row.addWidget(remove)
        self.status = QLabel("")
        self.status.setProperty("role", "muted")
        row.addWidget(self.status, 1)
        lay.addLayout(row)

        buttons = QDialogButtonBox(QDialogButtonBox.Close)
        buttons.rejected.connect(self.reject)
        lay.addWidget(buttons)
        save = buttons.addButton(tr("Ghi vào mô hình"),
                                 QDialogButtonBox.ApplyRole)
        save.clicked.connect(self._save)
        clear = buttons.addButton(tr("Bỏ lưới trục"),
                                  QDialogButtonBox.ResetRole)
        clear.clicked.connect(self._clear)
        self._load()

    # ---- the table -------------------------------------------------------
    def _load(self) -> None:
        element = existing_grid(self._building, self._story_id)
        params = (element or {}).get("params") or {}
        self.name_edit.setText(str(params.get("name") or tr("Trục")))
        axes = list(params.get("axes") or [])
        self._fill(axes)
        self.status.setText(
            tr("Tầng này đã có lưới trục (%d trục).") % len(axes) if axes
            else tr("Tầng này chưa có lưới trục."))

    def _fill(self, axes) -> None:
        self.table.setRowCount(len(axes))
        for r, axis in enumerate(axes):
            self.table.setItem(r, 0, QTableWidgetItem(str(axis.get("name", ""))))
            kind = QComboBox()
            kind.addItem(tr("y (đứng)"), "y")
            kind.addItem(tr("x (ngang)"), "x")
            kind.setCurrentIndex(0 if str(axis.get("dir") or "y") == "y" else 1)
            self.table.setCellWidget(r, 1, kind)
            spin = QDoubleSpinBox()
            spin.setRange(-1.0e6, 1.0e6)
            spin.setDecimals(1)
            spin.setValue(float(axis.get("offset_mm") or 0.0))
            self.table.setCellWidget(r, 2, spin)

    def _add_axis(self) -> None:
        name = self.axis_edit.text().strip() \
            or str(self.table.rowCount() + 1)
        r = self.table.rowCount()
        self.table.insertRow(r)
        self.table.setItem(r, 0, QTableWidgetItem(name))
        kind = QComboBox()
        kind.addItem(tr("y (đứng)"), "y")
        kind.addItem(tr("x (ngang)"), "x")
        self.table.setCellWidget(r, 1, kind)
        spin = QDoubleSpinBox()
        spin.setRange(-1.0e6, 1.0e6)
        spin.setDecimals(1)
        self.table.setCellWidget(r, 2, spin)
        self.axis_edit.clear()

    def _remove_axis(self) -> None:
        row = self.table.currentRow()
        if row >= 0:
            self.table.removeRow(row)

    def _fill_from_walls(self) -> None:
        axes = derive_axes(self._building, self._story_id)
        if not axes:
            self.status.setText(tr("Tầng này chưa có tường nào để lấy trục."))
            return
        self._fill(axes)
        self.status.setText(
            tr("Đã lấy %d trục từ tường — sửa lại tên và vị trí nếu cần.")
            % len(axes))

    # ---- the write -------------------------------------------------------
    def _axes(self) -> list:
        out: list = []
        for r in range(self.table.rowCount()):
            item = self.table.item(r, 0)
            name = (item.text() if item else "").strip()
            kind = self.table.cellWidget(r, 1)
            spin = self.table.cellWidget(r, 2)
            out.append({"name": name,
                        "dir": str(kind.currentData()) if kind else "y",
                        "offset_mm": round(float(spin.value()), 1)
                        if spin else 0.0})
        return out

    def _save(self) -> None:
        """One undo step: the grid written (or replaced) on this storey."""
        from core.building import commands as bim_commands
        from core.building.scene_sync import sync

        axes = self._axes()
        names = [a["name"] for a in axes]
        if not axes or any(not n for n in names):
            self.status.setText(tr("Mỗi trục cần một tên."))
            return
        if len(set(names)) != len(names):
            self.status.setText(tr("Tên trục bị trùng — đổi lại cho khác nhau."))
            return
        params = {"axes": axes, "name": self.name_edit.text().strip()
                  or tr("Trục")}
        element = existing_grid(self._building, self._story_id)
        history = self._window.viewport.history
        if element is None:
            command = bim_commands.add_element("grid", self._story_id, params)
        else:
            command = bim_commands.set_params(str(element["id"]), params)
        command._rebuild = lambda s, b: sync(s, b)
        history.execute(command)
        if history.last_error:
            self.status.setText(str(history.last_error))
            return
        self.status.setText(tr("Đã ghi %d trục vào mô hình.") % len(axes))
        self._window.viewport.notify_scene_changed()

    def _clear(self) -> None:
        element = existing_grid(self._building, self._story_id)
        if element is None:
            self.status.setText(tr("Tầng này chưa có lưới trục."))
            return
        from core.building import commands as bim_commands
        from core.building.scene_sync import sync

        history = self._window.viewport.history
        command = bim_commands.remove_element(str(element["id"]))
        command._rebuild = lambda s, b: sync(s, b)
        history.execute(command)
        # Re-ask the building: the command swapped plugin_data, and a
        # Building held across an undo step describes a document that no
        # longer exists.
        from core.building.model import building_of

        self._building = building_of(self._window.viewport.scene)
        self._load()
        self._window.viewport.notify_scene_changed()


def open_grid(window) -> GridDialog | None:
    """The grid editor for the ACTIVE storey (the one tools draw into)."""
    building = None
    from core.building.model import building_of

    building = building_of(window.viewport.scene)
    story = building.active_story() or (building.stories[0]
                                        if building.stories else None)
    if story is None:
        from PySide6.QtWidgets import QMessageBox

        QMessageBox.information(window, tr("Trục"),
                                tr("Chưa có tầng nào — dựng tầng trước đã."))
        return None
    dialog = GridDialog(window, str(story["id"]))
    dialog.exec()
    return dialog
