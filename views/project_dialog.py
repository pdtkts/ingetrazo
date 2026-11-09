# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Marco Sumari Tellez and IngeTrazo contributors.
"""Thông tin dự án — what the title block says, written once.

The title block is the sheet's identity: which job this is, what part of
it, who drew it and who is answerable for it. Every sheet of the set
prints it, so it is document data (``building.project``) — edit it here
and the next issue of the set carries the new name on all forty sheets,
rather than being retyped per sheet and drifting.

The office may state its own defaults for these fields
(:mod:`core.building.office`); this dialog is where the JOB corrects them,
and it writes the correction onto the building as one undo step.
"""
from __future__ import annotations

from PySide6.QtWidgets import (QDialog, QDialogButtonBox, QFormLayout,
                               QLabel, QLineEdit, QPushButton,
                               QVBoxLayout)

from core.i18n import tr

#: ``(field key, label, hint)`` in the order the title block reads them.
#: The keys are the ones :func:`core.building.sheets.title_block` reads, so
#: a field that appears here is one the title block actually prints.
FIELDS = (
    ("name", "Công trình", "Tên công trình, như ghi ở khung tên."),
    ("item", "Hạng mục", "Hạng mục hoặc gói thầu của công trình."),
    ("address", "Địa điểm", "Địa chỉ công trình."),
    ("owner", "Chủ đầu tư", "Đơn vị hoặc người đặt hàng."),
    ("designer", "Thiết kế", "Người vẽ chính."),
    ("chief", "Chủ trì", "Người chịu trách nhiệm bộ hồ sơ."),
    ("code", "Số hiệu", "Số hiệu hồ sơ (để trống thì lấy theo bộ tờ)."),
    ("date", "Ngày", "Ngày phát hành, thường là tháng/năm."),
    ("revision", "Lần phát hành", "Ví dụ «0», «A», «Lần 2»."),
)


class ProjectInfoDialog(QDialog):
    """The job's own data: one field per title-block row."""

    def __init__(self, window) -> None:
        super().__init__(window)
        from core.building.model import building_of

        self._window = window
        self.setWindowTitle(tr("Thông tin dự án"))
        self.setMinimumWidth(520)
        self._building = building_of(window.viewport.scene)

        layout = QVBoxLayout(self)
        note = QLabel(tr(
            "Số liệu ở đây in ra khung tên của MỌI tờ khi lập hồ sơ — "
            "sửa một lần, cả bộ tờ theo."))
        note.setWordWrap(True)
        layout.addWidget(note)
        layout.addWidget(QLabel(tr(
            "Để trống thì lấy theo thông tin chung của văn phòng (menu "
            "«Văn phòng…»).")))

        form = QFormLayout()
        self._edits: dict = {}
        for key, label, hint in FIELDS:
            edit = QLineEdit(str(self._building.project.get(key) or ""))
            edit.setPlaceholderText(tr(hint))
            form.addRow(tr(label), edit)
            self._edits[key] = edit
        layout.addLayout(form)

        self.status = QLabel("")
        self.status.setWordWrap(True)
        layout.addWidget(self.status)

        buttons = QDialogButtonBox(QDialogButtonBox.Save
                                  | QDialogButtonBox.Close)
        buttons.button(QDialogButtonBox.Save).setText(tr("Lưu"))
        buttons.button(QDialogButtonBox.Close).setText(tr("Đóng"))
        buttons.button(QDialogButtonBox.Save).setDefault(True)
        buttons.accepted.connect(self._save)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

        restore = QPushButton(tr("Xoá hết (theo văn phòng)"))
        restore.setToolTip(tr(
            "Bỏ số liệu của riêng công trình này: khung tên trở về đúng "
            "thông tin chung của văn phòng."))
        restore.clicked.connect(self._clear)
        layout.addWidget(restore)

        self._refresh_status()

    # ---- the write ------------------------------------------------------
    def values(self) -> dict:
        """What the fields hold, with blank fields left out.

        A blank field is left out rather than written as an empty string,
        because that is the difference between «the office's default» and
        «the designer decided to print nothing here» — and the title block
        falls back to the office for the first.
        """
        out: dict = {}
        for key, _label, _hint in FIELDS:
            text = self._edits[key].text().strip()
            if text:
                out[key] = text
        return out

    def _save(self) -> None:
        """One undo step: the project data merged onto the building."""
        from core.building import commands as bim_commands

        values = self.values()
        history = self._window.viewport.history
        # The merge only ADDS and overwrites; a field the user emptied must
        # actually go, so the removal rides in the same command by writing
        # the full set of keys this dialog owns.
        for key, _label, _hint in FIELDS:
            values.setdefault(key, "")
        command = bim_commands.set_project(values)
        history.execute(command)
        if history.last_error:
            self.status.setText(str(history.last_error))
            return
        # Re-ask: the command swapped the model, and a Building held across
        # an undo step describes a document that no longer exists.
        from core.building.model import building_of

        self._building = building_of(self._window.viewport.scene)
        self.status.setText(tr("Đã ghi thông tin dự án — bộ tờ sau in theo "
                               "số liệu này."))
        self._window.viewport.notify_scene_changed()

    def _clear(self) -> None:
        for _key, _label, _hint in FIELDS:
            self._edits[_key].setText("")
        self._save()

    def _refresh_status(self) -> None:
        held = sum(1 for key, _l, _h in FIELDS
                   if str(self._building.project.get(key) or "").strip())
        self.status.setText(
            tr("Công trình này khai %d/%d ô; ô trống lấy theo văn phòng.")
            % (held, len(FIELDS)))


def open_project_info(window) -> ProjectInfoDialog | None:
    """The project data dialog for the window's own document."""
    dialog = ProjectInfoDialog(window)
    dialog.exec()
    return dialog
