# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Marco Sumari Tellez and IngeTrazo contributors.
"""Văn phòng: the shared folder, chosen and shown.

One window, three questions: where is the folder, what does it hold, and
what goes into it. The last one is the reason the window exists — an
office sets its pens, its layer names, its title-block data and its detail
library ONCE, writes them here, and every machine that points at the same
folder issues the same drawing.

Nothing in here is required, and nothing in here edits the OPEN document:
what is written goes to the folder for the NEXT new document to start
from, and the window says so.
"""
from __future__ import annotations

from pathlib import Path

from PySide6.QtWidgets import (QDialog, QDialogButtonBox, QFileDialog,
                               QFormLayout, QGroupBox, QHBoxLayout, QLabel,
                               QLineEdit, QPushButton, QVBoxLayout)

from core.building import office as _office
from core.i18n import tr


class OfficeDialog(QDialog):
    """Where the office folder is, and what of the document goes into it."""

    def __init__(self, window) -> None:
        super().__init__(window)
        self.setWindowTitle(tr("Văn phòng"))
        self.resize(760, 560)
        self._window = window
        self._office = _office.Office.from_settings()

        lay = QVBoxLayout(self)
        lead = QLabel(tr(
            "Thư mục văn phòng là nơi cả văn phòng dùng chung một bộ quy "
            "định: bảng bút, tên lớp, số liệu khung tên, danh mục chi tiết "
            "và các mẫu nhà. Đặt một lần ở máy chủ (hoặc thư mục chia sẻ), "
            "mọi máy trỏ vào đó là giống nhau."))
        lead.setWordWrap(True)
        lead.setProperty("role", "muted")
        lay.addWidget(lead)

        pick = QHBoxLayout()
        pick.addWidget(QLabel(tr("Thư mục:")))
        self.path_edit = QLineEdit(str(self._office.path or ""))
        pick.addWidget(self.path_edit, 1)
        browse = QPushButton(tr("Chọn…"))
        browse.clicked.connect(self._browse)
        pick.addWidget(browse)
        use = QPushButton(tr("Dùng thư mục này"))
        use.clicked.connect(self._use)
        pick.addWidget(use)
        lay.addLayout(pick)

        # what it holds
        self.holding = QGroupBox(tr("Thư mục đang có gì"))
        hold_lay = QFormLayout(self.holding)
        self.rows = {}
        for key, label in (("project", tr("Số liệu khung tên")),
                           ("pens", tr("Bảng bút")),
                           ("renames", tr("Tên lớp gửi CAD khác")),
                           ("details", tr("Danh mục chi tiết")),
                           ("samples", tr("Mẫu nhà (.igz)"))):
            value = QLabel("")
            self.rows[key] = value
            hold_lay.addRow(label, value)
        lay.addWidget(self.holding)

        # what to write
        write = QGroupBox(tr("Ghi vào thư mục (cho tài liệu MỚI dùng)"))
        write_lay = QVBoxLayout(write)
        note = QLabel(tr(
            "Những gì ghi ở đây KHÔNG đổi tài liệu đang mở — nó là bộ quy "
            "định cho các tài liệu mới. Muốn đổi tài liệu đang mở thì sửa "
            "trực tiếp bằng «Bút vẽ & Lớp bản vẽ…» và «Quản lý chi tiết…»."))
        note.setWordWrap(True)
        note.setProperty("role", "muted")
        write_lay.addWidget(note)
        buttons = QHBoxLayout()
        for key, label in (("project", tr("Ghi số liệu khung tên")),
                           ("pens", tr("Ghi bảng bút & tên lớp")),
                           ("details", tr("Ghi danh mục chi tiết"))):
            button = QPushButton(label)
            button.clicked.connect(
                lambda _on=False, k=key: self._write(k))
            buttons.addWidget(button)
        write_lay.addLayout(buttons)
        lay.addWidget(write)

        self.status = QLabel("")
        self.status.setWordWrap(True)
        self.status.setProperty("role", "muted")
        lay.addWidget(self.status, 1)

        box = QDialogButtonBox(QDialogButtonBox.Close)
        box.rejected.connect(self.reject)
        lay.addWidget(box)
        self._refresh()

    # ---- the folder ------------------------------------------------------
    def _browse(self) -> None:
        chosen = QFileDialog.getExistingDirectory(
            self, tr("Chọn thư mục văn phòng"),
            self.path_edit.text() or str(Path.home()))
        if chosen:
            self.path_edit.setText(chosen)

    def _use(self) -> None:
        """Adopt the folder in the box.

        The office object is built from the PATH THE USER TYPED, not from
        a settings round-trip: ``from_settings`` falls back to the default
        when the stored value cannot be read back, and writing to the
        default folder after the user chose another one is exactly the
        silent surprise this window must not have.
        """
        path = self.path_edit.text().strip()
        _office.Office.remember(path or None)
        self._office = _office.Office(path or _office.default_path())
        self.path_edit.setText(str(self._office.path or ""))
        self._refresh()
        self.status.setText(
            tr("Đã đặt thư mục văn phòng: %s") % (self._office.path or "—"))

    def _refresh(self) -> None:
        office = self._office
        state = {"project": bool(office.project_defaults()),
                 "pens": bool(office.config().get("pens")),
                 "renames": bool(office.config().get("layer_renames")),
                 "details": bool(office.details()),
                 "samples": len(office.samples())}
        for key, label in self.rows.items():
            value = state.get(key)
            if key == "samples":
                label.setText(tr("%d mẫu") % value if value
                              else tr("(không có)"))
            else:
                label.setText(tr("có") if value else tr("(không có)"))
        if not office.exists():
            self.status.setText(
                tr("Thư mục này chưa có (sẽ tạo khi ghi): %s")
                % (office.path or "—"))
        else:
            self.status.setText(tr("Đang dùng: %s") % office.path)

    # ---- what goes in ----------------------------------------------------
    def _write(self, what: str) -> None:
        """Write one section of the office's tables FROM the document."""
        from core.building import pens as _pens
        from core.building.model import building_of

        scene = self._window.viewport.scene
        try:
            if what == "project":
                building = building_of(scene)
                self._office.write_tables(
                    project=dict(building.project or {}))
                self.status.setText(tr("Đã ghi số liệu khung tên."))
            elif what == "pens":
                self._office.write_tables(pens=dict(_pens.pens(scene)),
                                          renames=dict(_pens.renames(scene)))
                self.status.setText(tr("Đã ghi bảng bút và tên lớp."))
            elif what == "details":
                from core.building.detail_lib import overrides

                merged = dict(overrides(scene))
                if not merged:
                    self.status.setText(tr(
                        "Tài liệu này chưa sửa chi tiết nào — mở «Quản lý "
                        "chi tiết…» để sửa trước."))
                    return
                self._office.write_tables(details=merged)
                self.status.setText(tr("Đã ghi danh mục chi tiết."))
        except Exception as exc:                     # noqa: BLE001 — reported
            self.status.setText(f"{type(exc).__name__}: {exc}")
            return
        self._office = _office.Office(self._office.path)
        self._refresh()


def open_office(window) -> OfficeDialog:
    dialog = OfficeDialog(window)
    dialog.exec()
    return dialog
