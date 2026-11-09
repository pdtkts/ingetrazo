# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Marco Sumari Tellez and IngeTrazo contributors.
"""The pen and layer manager: how this office inks a drawing.

Two tables, one dialog, because they are two halves of the same decision:
a class of line gets a width, a colour and a pattern (the pen), and the
layer it travels on gets a name the receiving CAD will recognise.

Both are written to the document, and all three consumers read them from
one place (``core.building.pens``): the DXF export, the paper (PDF — the
drawing frames), and this dialog. An office that sets the cut pen to
0.35 mm sees the sheet and the file change together, not one of them.
"""
from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtGui import QColor
from PySide6.QtWidgets import (QComboBox, QDialog, QDialogButtonBox,
                               QDoubleSpinBox, QHeaderView, QLabel,
                               QTableWidget, QTableWidgetItem, QVBoxLayout)

from core.building import pens as _pens
from core.i18n import tr

#: AutoCAD colour indices, as the receiving CAD names them.
ACI_NAMES = {1: "Đỏ", 2: "Vàng", 3: "Xanh lá", 4: "Xanh lơ", 5: "Xanh dương",
             6: "Hồng", 7: "Trắng/Đen", 8: "Xám", 9: "Xám nhạt",
             253: "Xám mờ", 250: "Xám 250", 30: "Cam", 40: "Nâu"}


class PensDialog(QDialog):
    """The document's pen table and layer-name table, edited together."""

    def __init__(self, window) -> None:
        super().__init__(window)
        self.setWindowTitle(tr("Bút vẽ & Lớp bản vẽ"))
        self.resize(900, 560)
        self._window = window
        self._scene = window.viewport.scene

        lay = QVBoxLayout(self)
        lead = QLabel(tr(
            "Nét của bản vẽ in ra giấy và ghi vào DXF lấy từ bảng này. "
            "Đổi ở đây thì tờ giấy (PDF) và file DXF đổi theo cùng lúc."))
        lead.setWordWrap(True)
        lead.setProperty("role", "muted")
        lay.addWidget(lead)

        self.table = QTableWidget(0, 4)
        self.table.setHorizontalHeaderLabels(
            [tr("Loại nét"), tr("Bề rộng (mm giấy)"), tr("Màu"),
             tr("Kiểu nét")])
        self.table.verticalHeader().setVisible(False)
        self.table.setAlternatingRowColors(True)
        self.table.horizontalHeader().setSectionResizeMode(
            0, QHeaderView.Stretch)
        lay.addWidget(self.table, 3)

        layer_head = QLabel(tr("Tên lớp khi xuất DXF (để trống = tên chuẩn)"))
        layer_head.setProperty("role", "muted")
        lay.addWidget(layer_head)
        self.layers = QTableWidget(0, 2)
        self.layers.setHorizontalHeaderLabels(
            [tr("Lớp chuẩn"), tr("Tên gửi đi cho CAD khác")])
        self.layers.verticalHeader().setVisible(False)
        self.layers.setAlternatingRowColors(True)
        self.layers.horizontalHeader().setSectionResizeMode(
            0, QHeaderView.Stretch)
        self.layers.horizontalHeader().setSectionResizeMode(
            1, QHeaderView.Stretch)
        lay.addWidget(self.layers, 2)

        buttons = QDialogButtonBox(QDialogButtonBox.Close)
        buttons.rejected.connect(self.reject)
        reset = buttons.addButton(tr("Về bảng chuẩn"),
                                  QDialogButtonBox.ResetRole)
        reset.clicked.connect(self._reset)
        apply_btn = buttons.addButton(tr("Áp dụng"),
                                      QDialogButtonBox.ApplyRole)
        apply_btn.clicked.connect(self._apply)
        lay.addWidget(buttons)
        self._load()

    # ---- tables ----------------------------------------------------------
    def _load(self) -> None:
        table = _pens.pens(self._scene)
        self.table.setRowCount(len(_pens.CLASSES))
        for row, (key, label) in enumerate(_pens.CLASSES):
            width, color, linetype = table.get(key) or _pens.PENS[key]
            self.table.setItem(row, 0, QTableWidgetItem(str(label)))
            self.table.item(row, 0).setData(Qt.UserRole, key)
            spin = QDoubleSpinBox()
            spin.setRange(0.01, 3.0)
            spin.setSingleStep(0.01)
            spin.setDecimals(2)
            spin.setValue(float(width))
            self.table.setCellWidget(row, 1, spin)
            combo = QComboBox()
            for index in sorted({*ACI_NAMES, int(color)}):
                combo.addItem(f"{index} — {ACI_NAMES.get(index, '')}", index)
                combo.setItemData(combo.count() - 1,
                                  QColor(*_aci_rgb(index)), Qt.DecorationRole)
            combo.setCurrentIndex(
                [combo.itemData(i) for i in range(combo.count())].index(int(color)))
            self.table.setCellWidget(row, 2, combo)
            kind = QComboBox()
            from core.layers import LINETYPES

            for name in LINETYPES:
                kind.addItem(tr(name), name)
            if str(linetype) in LINETYPES:
                kind.setCurrentText(tr(str(linetype)))
            self.table.setCellWidget(row, 3, kind)

        renames = _pens.renames(self._scene)
        self.layers.setRowCount(len(_pens.LAYER_KEYS))
        for row, (key, standard) in enumerate(_pens.LAYER_KEYS.items()):
            label = QTableWidgetItem(str(standard))
            label.setData(Qt.UserRole, key)
            label.setFlags(label.flags() & ~Qt.ItemIsEditable)
            self.layers.setItem(row, 0, label)
            self.layers.setItem(
                row, 1, QTableWidgetItem(str(renames.get(standard) or "")))

    def _apply(self) -> None:
        """Write both tables into the document and re-ink what is on screen."""
        table = _pens.pens(self._scene)
        for row in range(self.table.rowCount()):
            key = self.table.item(row, 0).data(Qt.UserRole)
            spin = self.table.cellWidget(row, 1)
            color = self.table.cellWidget(row, 2)
            kind = self.table.cellWidget(row, 3)
            table[str(key)] = (round(float(spin.value()), 2),
                               int(color.currentData()),
                               str(kind.currentData()))
        renames = _pens.renames(self._scene)
        renames.clear()
        for row in range(self.layers.rowCount()):
            key = self.layers.item(row, 0).data(Qt.UserRole)
            standard = _pens.LAYER_KEYS[str(key)]
            name = (self.layers.item(row, 1).text() if self.layers.item(row, 1)
                    else "").strip()
            if name and name != standard:
                renames[standard] = name
        self._window.viewport.update()
        try:
            self._window.viewport.notify_scene_changed()
        except Exception:                          # noqa: BLE001 — best effort
            pass

    def _reset(self) -> None:
        self._scene.pens = {k: tuple(v) for k, v in _pens.PENS.items()}
        self._scene.layer_renames = {}
        self._load()
        self._window.viewport.update()

    def closeEvent(self, event) -> None:            # noqa: N802 — Qt name
        # Leaving without "Áp dụng" changes nothing: the two tables are
        # decisions, and a half-typed one must not reach the document.
        super().closeEvent(event)


def _aci_rgb(index: int) -> tuple:
    """AutoCAD colour index → RGB, near enough for a swatch."""
    table = {1: (255, 0, 0), 2: (255, 255, 0), 3: (0, 255, 0),
             4: (0, 255, 255), 5: (0, 0, 255), 6: (255, 0, 255),
             7: (0, 0, 0), 8: (128, 128, 128), 9: (192, 192, 192),
             30: (255, 128, 0), 40: (128, 64, 0), 250: (51, 51, 51),
             253: (132, 132, 132)}
    return table.get(int(index), (0, 0, 0))


def open_pens(window) -> PensDialog:
    dialog = PensDialog(window)
    dialog.exec()
    return dialog
