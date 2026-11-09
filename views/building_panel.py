# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Marco Sumari Tellez and IngeTrazo contributors.
"""The building panel — storeys, elements and their parameters.

What the user edits here is the **building**, not the drawing: pick a storey,
pick an element, change a number, and the solid, the drawings and the takeoff
all follow — because they were never separate. This is the panel that makes a
parametric model worth having, so it is deliberately plain: a storey list, an
element list, and a form of the parameters the element type actually declares
(``core.building.elements``), never a hand-written field list that can drift
away from the schema.

Editing happens through :class:`~core.building.commands.BuildingEdit`, so every
change here is one undo step with the geometry it rebuilt.
"""
from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (QComboBox, QDoubleSpinBox, QFormLayout,
                               QHBoxLayout, QLabel, QLineEdit, QPushButton,
                               QScrollArea, QTreeWidget, QTreeWidgetItem,
                               QVBoxLayout, QWidget)

from core.building import commands as bim_commands
from core.building import elements as schemas
from core.building import model as building_model
from core.building.scene_sync import sync
from core.i18n import tr


class BuildingPanel(QWidget):
    """Storeys above, elements below, the selected element's fields at the
    bottom — one screen for the whole parametric model."""

    def __init__(self, window) -> None:
        super().__init__()
        self._window = window
        self._story_rows: list = []
        self._element_rows: list = []
        self._fields: dict = {}
        self._loading = False

        lay = QVBoxLayout(self)
        lay.setContentsMargins(8, 6, 8, 8)

        lay.addWidget(_caption(tr("Storeys")))
        self.story_tree = QTreeWidget()
        self.story_tree.setColumnCount(3)
        self.story_tree.setHeaderLabels([tr("Storey"), tr("Z (m)"),
                                         tr("Height (m)")])
        self.story_tree.setRootIsDecorated(False)
        self.story_tree.itemSelectionChanged.connect(self._on_story_pick)
        lay.addWidget(self.story_tree)

        buttons = QHBoxLayout()
        add_story = QPushButton(tr("Add storey"))
        add_story.clicked.connect(self._on_add_story)
        del_story = QPushButton(tr("Remove storey"))
        del_story.clicked.connect(self._on_remove_story)
        buttons.addWidget(add_story)
        buttons.addWidget(del_story)
        lay.addLayout(buttons)

        lay.addWidget(_caption(tr("Elements on the active storey")))
        self.element_tree = QTreeWidget()
        self.element_tree.setColumnCount(2)
        self.element_tree.setHeaderLabels([tr("Type"), tr("Name")])
        self.element_tree.itemSelectionChanged.connect(self._on_element_pick)
        lay.addWidget(self.element_tree)

        self.form_host = QWidget()
        self.form = QFormLayout(self.form_host)
        self.form.setContentsMargins(0, 4, 0, 4)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setWidget(self.form_host)
        scroll.setMinimumHeight(120)
        lay.addWidget(scroll, 1)

        # What the last synchronisation could not build. An element that
        # fails (a door whose host wall was deleted, a wall with no
        # baseline) simply does not appear in a parametric tool, and a
        # silent absence is the worst thing it can do — so the panel says
        # it, in the same place the user is already looking.
        self.warnings = QLabel("")
        self.warnings.setWordWrap(True)
        self.warnings.setProperty("role", "error")
        self.warnings.setVisible(False)
        lay.addWidget(self.warnings)

        self.hint = QLabel("")
        self.hint.setWordWrap(True)
        self.hint.setProperty("role", "muted")
        lay.addWidget(self.hint)

        self.refresh()

    # ---- data access -----------------------------------------------------
    def _scene(self):
        return self._window.viewport.scene

    def _building(self):
        return building_model.building_of(self._scene())

    # ---- refresh ---------------------------------------------------------
    def refresh(self) -> None:
        """Rebuild the lists from the model, keeping the selection if it
        still exists (a refresh after an edit must not move the user's
        cursor to the top of the list)."""
        self._loading = True
        try:
            building = self._building()
            keep_story = self._current_story_id()
            self.story_tree.clear()
            self._story_rows = []
            for story in building.stories:
                row = QTreeWidgetItem([
                    str(story.get("name") or ""),
                    f"{float(story.get('z_mm', 0.0)) / 1000.0:.3f}",
                    f"{float(story.get('height_mm', 0.0)) / 1000.0:.3f}",
                ])
                row.setData(0, Qt.UserRole, str(story["id"]))
                self.story_tree.addTopLevelItem(row)
                self._story_rows.append(row)
            active = building.active_story()
            if active is None and self._story_rows:
                building.set_active_story(str(
                    building.stories[0]["id"]))
                active = building.active_story()
            target = keep_story or (str(active["id"]) if active else None)
            picked = next((row for row in self._story_rows
                           if row.data(0, Qt.UserRole) == target), None)
            if picked is None and self._story_rows:
                picked = self._story_rows[0]
            if picked is not None:
                self.story_tree.setCurrentItem(picked)
            self._fill_elements()
            self._fill_fields()
            self._show_errors()
        finally:
            self._loading = False

    def _show_errors(self) -> None:
        errors = list(getattr(self._scene(), "building_errors", None) or ())
        if not errors:
            self.warnings.setVisible(False)
            self.warnings.setText("")
            return
        # Each entry is ``(element id, the reason)``; the reason is what a
        # reader can act on, so it is what the label shows.
        lines = [str(e[1]) if isinstance(e, (list, tuple)) and len(e) > 1
                 else str(e) for e in errors]
        self.warnings.setText(
            tr("%d cấu kiện không dựng được:") % len(lines) + " "
            + "; ".join(lines[:3])
            + (" …" if len(lines) > 3 else ""))
        self.warnings.setVisible(True)

    def _fill_elements(self) -> None:
        building = self._building()
        self.element_tree.clear()
        self._element_rows = []
        active = building.active_story()
        if active is None:
            return
        keep = self._current_element_id()
        for el in building.on_story(str(active["id"])):
            row = QTreeWidgetItem([
                tr(_type_label(str(el.get("type")))),
                str((el.get("params") or {}).get("name") or ""),
            ])
            row.setData(0, Qt.UserRole, str(el["id"]))
            self.element_tree.addTopLevelItem(row)
            self._element_rows.append(row)
        if self._element_rows:
            # First load (or the previous pick is gone): select the first
            # element, so the form is never empty without a reason.
            target = next((r for r in self._element_rows
                           if r.data(0, Qt.UserRole) == keep),
                          self._element_rows[0])
            self.element_tree.setCurrentItem(target)

    def _fill_fields(self) -> None:
        """Build the form from the selected element's own schema."""
        while self.form.rowCount():
            self.form.removeRow(0)
        self._fields = {}
        element = self._current_element()
        if element is None:
            self.hint.setText(tr("Select an element to edit its parameters."))
            return
        params = element.get("params") or {}
        defaults = schemas.defaults_for(str(element.get("type")))
        keys = list(defaults.keys()) + [k for k in _EXTRA_KEYS
                                        if k in params
                                        and k not in defaults]
        for key in keys:
            if key in _HIDDEN_KEYS:
                continue
            value = params.get(key, defaults.get(key))
            widget = self._widget_for(key, value)
            if widget is None:
                continue
            self._fields[key] = widget
            self.form.addRow(_field_label(key), widget)
        self.hint.setText(tr("Edits apply to the whole model: geometry, "
                             "drawings and quantities update together."))

    def _widget_for(self, key: str, value):
        if isinstance(value, bool):
            box = QComboBox()
            box.addItems([tr("No"), tr("Yes")])
            box.setCurrentIndex(1 if value else 0)
            box.currentIndexChanged.connect(
                lambda _i, k=key: self._on_field(k))
            return box
        if isinstance(value, str) or value is None:
            edit = QLineEdit("" if value is None else str(value))
            edit.editingFinished.connect(lambda k=key: self._on_field(k))
            return edit
        if isinstance(value, (int, float)):
            spin = QDoubleSpinBox()
            spin.setDecimals(1)
            spin.setRange(-1_000_000.0, 1_000_000.0)
            spin.setSingleStep(10.0)
            spin.setValue(float(value))
            spin.editingFinished.connect(lambda k=key: self._on_field(k))
            return spin
        return None                        # lists (outlines, panels) are
        # drawn with the tools, not typed in a form.

    def _read_field(self, key: str):
        widget = self._fields.get(key)
        if isinstance(widget, QComboBox):
            text = widget.currentText()
            return text == tr("Yes")
        if isinstance(widget, QLineEdit):
            text = widget.text().strip()
            return text or None
        if isinstance(widget, QDoubleSpinBox):
            return float(widget.value())
        return None

    # ---- selection -------------------------------------------------------
    def _current_story_id(self):
        row = self.story_tree.currentItem()
        return row.data(0, Qt.UserRole) if row is not None else None

    def _current_element_id(self):
        row = self.element_tree.currentItem()
        return row.data(0, Qt.UserRole) if row is not None else None

    def _current_element(self):
        eid = self._current_element_id()
        return self._building().element(eid) if eid else None

    def _on_story_pick(self) -> None:
        if self._loading:
            return
        eid = self._current_story_id()
        if eid is None:
            return
        self._building().set_active_story(str(eid))
        self._emit(bim_commands.set_story_params(str(eid), {}))
        self._loading = True
        try:
            self._fill_elements()
            self._fill_fields()
        finally:
            self._loading = False

    def _on_element_pick(self) -> None:
        if self._loading:
            return
        self._fill_fields()

    # ---- actions ---------------------------------------------------------
    def _on_add_story(self) -> None:
        building = self._building()
        last = building.stories[-1] if building.stories else None
        z = (float(last.get("z_mm", 0.0))
             + float(last.get("height_mm", 3300.0))) if last else 0.0
        name = tr("Storey {n}").format(n=len(building.stories) + 1)
        self._emit(bim_commands.add_story(name, z, 3300.0))
        self.refresh()

    def _on_remove_story(self) -> None:
        eid = self._current_story_id()
        if eid is None:
            return
        self._emit(bim_commands.remove_story(str(eid)))
        self.refresh()

    def _on_field(self, key: str) -> None:
        if self._loading:
            return
        element = self._current_element()
        if element is None:
            return
        value = self._read_field(key)
        self._emit(bim_commands.set_params(str(element["id"]), {key: value}))
        row = self.element_tree.currentItem()
        if row is not None and key == "name":
            row.setText(1, "" if value is None else str(value))

    def _emit(self, command) -> None:
        """Commit a building edit and let the whole app see the change.

        The geometry rebuild is handed to the COMMAND rather than called
        after it: run inside the step, its result is part of the step's own
        snapshot, so undo and redo restore the picture with the parameters.
        """
        scene = self._scene()
        if getattr(command, "_rebuild", None) is None:
            command._rebuild = lambda s, b: sync(s, b)
        history = getattr(self._window.viewport, "history", None)
        if history is not None:
            history.execute(command)
        else:
            command.do(scene)
        notify = getattr(self._window, "on_scene_changed", None)
        if callable(notify):
            notify()
        else:
            self._window.viewport.update()

    def on_scene_changed(self) -> None:
        """The scene changed under us (undo, a tool, a file load)."""
        self.refresh()


#: Parameters shown in the form even when not part of the type's defaults
#: (they belong to the element's identity once set).
_EXTRA_KEYS = ("name", "derived", "host_wall_id")

#: Never shown as an editable field.
_HIDDEN_KEYS = ("derived", "host_wall_id")

#: Extra field labels that are not plain parameter ids.
_EXTRA_LABELS = {"name": "Name"}


def _type_label(kind: str) -> str:
    from core.building.scene_sync import TR_NAMES
    return TR_NAMES.get(str(kind), str(kind))


def _field_label(key: str) -> str:
    if key in _EXTRA_LABELS:
        return tr(_EXTRA_LABELS[key])
    label = key.replace("_mm", " (mm)").replace("_m2", " (m²)")
    label = label.replace("_m3", " (m³)").replace("_deg", " (°)")
    return tr(label.replace("_", " ").strip().capitalize())


def _caption(text: str) -> QLabel:
    label = QLabel(text)
    label.setProperty("role", "caption")
    return label
