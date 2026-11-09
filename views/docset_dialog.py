# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Marco Sumari Tellez and IngeTrazo contributors.
"""Lập hồ sơ tự động: the screen that issues the whole drawing set.

The office's problem with an automatic drawing set is trust: it has to see
what the run will do BEFORE it runs, watch it happen, and get a line about
what came out. So the dialog has three states in one window — the check
report with the options, the run with its steps ticking past, and the
result — rather than a bar that flashes and a message box after it.

The options are the model's own facts: which storeys are in this issue, the
paper it is printed on, and whether the set carries its elevation, its
section and its dimensions. Everything else follows the model, which is
what keeps 「lập hồ sơ」 one call rather than a session of settings.
"""
from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (QCheckBox, QComboBox, QDialog, QDialogButtonBox,
                               QHBoxLayout, QLabel, QListWidget,
                               QListWidgetItem, QProgressBar, QPushButton,
                               QVBoxLayout)

from core.i18n import tr

#: The papers a Vietnamese drawing set is printed on, in issue order.
PAPERS = ("A4", "A3", "A2", "A1", "A0")


class DocSetDialog(QDialog):
    """The whole run in one window: check, options, steps, result.

    The window is opened NON-modal (``open()``) rather than run in its own
    event loop: the user may leave it open, pan the model, and run again —
    and a modal loop would also mean any headless caller of the menu action
    never gets its turn back. After an accepted run :attr:`docset` holds the
    :class:`~core.building.docset.DocSetResult`.
    """

    def __init__(self, window, building=None, scene=None) -> None:
        super().__init__(window)
        self.setWindowTitle(tr("Lập hồ sơ tự động"))
        self.window = window
        #: The BUILDING IS RESOLVED AT USE, never held: the window is
        #: non-modal, so the user can undo while it stands open, and the
        #: cached Building would then describe a model that no longer
        #: exists — its own docstring invites exactly that workflow.
        self.scene = scene if scene is not None else window.viewport.scene
        del building
        self.docset = None
        self._built_ok = False

        self.issues = self._check()
        self.story_boxes: list = []

        lay = QVBoxLayout(self)
        head = QLabel(tr("Hồ sơ bản vẽ sinh từ mô hình: mặt bằng, mặt đứng, "
                         "mặt cắt, chi tiết, khung tên và bảng liệt kê."))
        head.setWordWrap(True)
        lay.addWidget(head)

        # ---- the check, before anything runs ----------------------------
        if self.issues:
            report = QListWidget()
            report.setMaximumHeight(96)
            for text, severity in self.issues:
                item = QListWidgetItem(
                    ("⚠ " if severity == "warn" else "· ") + tr(text))
                item.setForeground(
                    Qt.GlobalColor.darkYellow if severity == "warn"
                    else Qt.GlobalColor.gray)
                report.addItem(item)
            lay.addWidget(report)

        # ---- the options -------------------------------------------------
        options = QHBoxLayout()
        options.addWidget(QLabel(tr("Khổ giấy:")))
        self.paper_box = QComboBox()
        self.paper_box.addItems(PAPERS)
        self.paper_box.setCurrentText("A3")
        options.addWidget(self.paper_box)
        self.elev_box = QCheckBox(tr("Mặt đứng"))
        self.elev_box.setChecked(True)
        options.addWidget(self.elev_box)
        self.sect_box = QCheckBox(tr("Mặt cắt"))
        self.sect_box.setChecked(True)
        options.addWidget(self.sect_box)
        self.annot_box = QCheckBox(tr("Kích thước & phòng"))
        self.annot_box.setChecked(True)
        options.addWidget(self.annot_box)
        options.addStretch(1)
        lay.addLayout(options)

        # ---- which storeys are in this issue -----------------------------
        lay.addWidget(QLabel(tr("Tầng phát hành:")))
        stories = QHBoxLayout()
        for story in self.building.stories or ():
            box = QCheckBox(str(story.get("name") or story.get("id")))
            box.setChecked(True)
            stories.addWidget(box)
            self.story_boxes.append((str(story["id"]), box))
        stories.addStretch(1)
        lay.addLayout(stories)

        # ---- the run -----------------------------------------------------
        self.step_list = QListWidget()
        self.step_list.setMinimumHeight(120)
        lay.addWidget(self.step_list)
        self.bar = QProgressBar()
        self.bar.setRange(0, 100)
        self.bar.setValue(0)
        lay.addWidget(self.bar)

        self.buttons = QDialogButtonBox()
        self.go = QPushButton(tr("Lập hồ sơ"))
        self.go.setDefault(True)
        self.buttons.addButton(self.go, QDialogButtonBox.AcceptRole)
        self.close_btn = self.buttons.addButton(QDialogButtonBox.Close)
        self.go.clicked.connect(self._generate)
        self.close_btn.clicked.connect(self.accept)

    @property
    def building(self):
        """The live building, asked for at every use (never held)."""
        from core.building.model import building_of

        return building_of(self.scene)

    def _check(self) -> list:
        from core.building import docset as _docset
        try:
            return _docset.check_docset(self.building)
        except Exception as exc:                # noqa: BLE001 — reported
            return [(f"{type(exc).__name__}: {exc}", "warn")]

    def wanted_story_ids(self):
        ids = [sid for sid, box in self.story_boxes if box.isChecked()]
        return ids or None

    def _generate(self) -> None:
        """Run the set, ticking each step into the list as it lands."""
        from PySide6.QtWidgets import QApplication, QMessageBox
        from core.building import docset as _docset

        self.go.setEnabled(False)
        self.step_list.clear()
        self.bar.setValue(0)

        def progress(index, total, label) -> None:
            self.step_list.addItem(f"{index}/{total}  {tr(label)}")
            self.step_list.scrollToBottom()
            self.bar.setValue(int(100.0 * index / max(total, 1)))
            QApplication.processEvents()

        try:
            self.docset = _docset.generate_docset(
                self.scene, self.building,
                paper=self.paper_box.currentText(),
                sections=self.sect_box.isChecked(),
                elevations=self.elev_box.isChecked(),
                annotations=self.annot_box.isChecked(),
                story_ids=self.wanted_story_ids(),
                progress=progress)
        except Exception as exc:                # noqa: BLE001 — reported
            self.bar.setValue(0)
            self.go.setEnabled(True)
            QMessageBox.warning(self, tr("Lập hồ sơ tự động"),
                                f"{type(exc).__name__}: {exc}")
            return
        self.bar.setValue(100)
        made = len(self.docset.sheets)
        drawn = len([s for s in self.docset.sheets if s.frames])
        blank = [s.name for s in self.docset.sheets
                 if not s.frames
                 and not any(str(t.text).strip() for t in s.texts)]
        line = tr("Đã sinh %d tờ, %d tờ có bản vẽ.") % (made, drawn)
        if blank:
            line += "\n" + tr("Tờ chưa có nội dung: %s") % ", ".join(blank)
        self.step_list.addItem("— " + line.replace("\n", " "))
        self.step_list.scrollToBottom()
        self._built_ok = True
        self.go.setText(tr("Lập hồ sơ lại"))

