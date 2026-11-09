# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Marco Sumari Tellez and IngeTrazo contributors.
"""The detail manager: an office's own details, edited and kept.

The library in :mod:`core.building.detail_lib` is the set every office
starts from. An office that builds a floor-up differently draws it once,
here, and reissues it every job — which means the edit has to SURVIVE the
file, and this dialog is what writes and reads ``scene.detail_overrides``:
a plain ``{key: record}`` beside the model, saved in the .igz like every
other document datum.

Nothing here re-draws a detail: the editor writes the same structure the
library uses (a name, a stack of ``(label, material, thickness, pattern)``
rows, a note), and the insert path in ``detail_lib`` reads it unchanged.
"""
from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (QComboBox, QDialog, QDialogButtonBox,
                               QDoubleSpinBox, QHBoxLayout, QLabel,
                               QLineEdit, QPushButton, QTableWidget,
                               QTableWidgetItem, QVBoxLayout)

from core.i18n import tr

STORAGE_KEY = "detail_overrides"


def overrides(scene) -> dict:
    """The office's own detail edits, made on first use."""
    store = getattr(scene, STORAGE_KEY, None)
    if not isinstance(store, dict):
        store = {}
        setattr(scene, STORAGE_KEY, store)
    return store


def merged_details(scene) -> dict:
    """The library as THIS document reads it: the standard set, with the
    office's own edits over it."""
    from core.building import detail_lib

    out = {key: dict(record) for key, record in detail_lib.DETAILS.items()}
    for key, record in overrides(scene).items():
        base = out.get(key, {})
        merged = dict(base)
        merged.update({k: v for k, v in record.items() if v not in (None, "")})
        out[key] = merged
    return out


class DetailManagerDialog(QDialog):
    """Pick a detail, edit its stack, save the edit to the document."""

    def __init__(self, window) -> None:
        super().__init__(window)
        self.setWindowTitle(tr("Quản lý chi tiết"))
        self.resize(880, 560)
        self._window = window
        self._scene = window.viewport.scene

        lay = QVBoxLayout(self)
        head = QHBoxLayout()
        head.addWidget(QLabel(tr("Chi tiết:")))
        self.pick = QComboBox()
        for key in merged_details(self._scene):
            self.pick.addItem(self._label(key), key)
        self.pick.currentIndexChanged.connect(lambda _i: self._load())
        head.addWidget(self.pick, 1)
        reset = QPushButton(tr("Về mặc định"))
        reset.setToolTip(tr("Bỏ mọi sửa đổi của văn phòng cho chi tiết này."))
        reset.clicked.connect(self._reset_one)
        head.addWidget(reset)
        lay.addLayout(head)

        form = QHBoxLayout()
        form.addWidget(QLabel(tr("Tên:")))
        self.name_edit = QLineEdit()
        form.addWidget(self.name_edit, 2)
        add = QPushButton(tr("Thêm lớp"))
        add.clicked.connect(lambda: self._add_row())
        form.addWidget(add)
        remove = QPushButton(tr("Xoá lớp"))
        remove.clicked.connect(self._remove_row)
        form.addWidget(remove)
        lay.addLayout(form)

        self.table = QTableWidget(0, 4)
        self.table.setHorizontalHeaderLabels(
            [tr("Lớp"), tr("Vật liệu"), tr("Dày (mm)"), tr("Mặt cắt (pattern)")])
        self.table.verticalHeader().setVisible(False)
        self.table.setAlternatingRowColors(True)
        lay.addWidget(self.table, 1)

        note_row = QHBoxLayout()
        note_row.addWidget(QLabel(tr("Ghi chú:")))
        self.note_edit = QLineEdit()
        note_row.addWidget(self.note_edit, 1)
        lay.addLayout(note_row)

        self.status = QLabel("")
        self.status.setProperty("role", "muted")
        lay.addWidget(self.status)

        buttons = QDialogButtonBox(QDialogButtonBox.Close)
        buttons.rejected.connect(self.reject)
        save = buttons.addButton(tr("Lưu vào tài liệu"),
                                 QDialogButtonBox.ActionRole)
        save.clicked.connect(self._save)
        lay.addWidget(buttons)
        self._load()

    # ---- the table -------------------------------------------------------
    def _label(self, key: str) -> str:
        record = merged_details(self._scene).get(key, {})
        return str(record.get("name") or key)

    def _load(self) -> None:
        key = self.pick.currentData()
        if not key:
            return
        record = merged_details(self._scene).get(key, {})
        self.name_edit.setText(str(record.get("name") or key))
        self.note_edit.setText(str(record.get("note") or ""))
        rows = list(record.get("layers") or ())
        self.table.setRowCount(len(rows))
        for r, row in enumerate(rows):
            label, material, thickness, pattern = (list(row) + ["", "", 0, ""])[:4]
            self._set_row(r, label, material, float(thickness or 0.0), pattern)
        edited = key in overrides(self._scene)
        self.status.setText(
            tr("Chi tiết này đã được văn phòng sửa.") if edited
            else tr("Đang dùng bản chuẩn của thư viện."))

    def _set_row(self, r: int, label, material, thickness: float,
                 pattern) -> None:
        self.table.setItem(r, 0, QTableWidgetItem(str(label)))
        materials = QComboBox()
        names = self._materials()
        materials.addItems(names)
        if str(material) in names:
            materials.setCurrentText(str(material))
        materials.setEditable(True)
        self.table.setCellWidget(r, 1, materials)
        spin = QDoubleSpinBox()
        spin.setRange(0.0, 2000.0)
        spin.setDecimals(1)
        spin.setValue(float(thickness or 0.0))
        self.table.setCellWidget(r, 2, spin)
        pat = QComboBox()
        patterns = self._patterns()
        pat.addItems(patterns)
        if str(pattern) in patterns:
            pat.setCurrentText(str(pattern))
        pat.setEditable(True)
        self.table.setCellWidget(r, 3, pat)

    @staticmethod
    def _materials() -> list:
        """The material names the library already uses — one vocabulary."""
        from core.building import detail_lib

        seen: list = []
        for record in detail_lib.DETAILS.values():
            for _label, material, _t, _p in record.get("layers") or ():
                if material not in seen:
                    seen.append(material)
        return ["", *seen]

    @staticmethod
    def _patterns() -> list:
        from core.building.patterns import names

        return ["", *names()]

    def _add_row(self) -> None:
        r = self.table.rowCount()
        self.table.insertRow(r)
        self._set_row(r, tr("Lớp mới"), "", 10.0, "")

    def _remove_row(self) -> None:
        row = self.table.currentRow()
        if row >= 0:
            self.table.removeRow(row)

    # ---- the writes ------------------------------------------------------
    def _save(self) -> None:
        """Write the edit into the document, under the detail's own key."""
        key = self.pick.currentData()
        if not key:
            return
        layers: list = []
        for r in range(self.table.rowCount()):
            label = (self.table.item(r, 0).text()
                     if self.table.item(r, 0) else "")
            material = self._cell_text(r, 1, QComboBox)
            thickness = self._cell_value(r, 2, QDoubleSpinBox)
            pattern = self._cell_text(r, 3, QComboBox)
            if not label and not material:
                continue
            layers.append((label, material, float(thickness or 0.0), pattern))
        if not layers:
            self.status.setText(tr("Chi tiết phải còn ít nhất một lớp."))
            return
        overrides(self._scene)[str(key)] = {
            "name": self.name_edit.text().strip() or self._label(key),
            "layers": layers,
            "note": self.note_edit.text().strip(),
        }
        self.status.setText(tr("Đã lưu — chi tiết dùng bản này từ giờ."))
        self._window.viewport.update()

    def _reset_one(self) -> None:
        key = self.pick.currentData()
        if key:
            overrides(self._scene).pop(str(key), None)
            self._load()
            self.status.setText(tr("Đã trả về bản chuẩn của thư viện."))

    def _cell_text(self, row: int, col: int, kind) -> str:
        widget = self.table.cellWidget(row, col)
        return widget.currentText() if isinstance(widget, kind) else ""

    def _cell_value(self, row: int, col: int, kind) -> float:
        widget = self.table.cellWidget(row, col)
        return float(widget.value()) if isinstance(widget, kind) else 0.0


def open_detail_manager(window) -> DetailManagerDialog:
    dialog = DetailManagerDialog(window)
    dialog.exec()
    return dialog
