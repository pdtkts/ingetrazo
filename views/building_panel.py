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
                               QScrollArea, QTabWidget, QTreeWidget,
                               QTreeWidgetItem, QVBoxLayout, QWidget)

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

        # The parameters, in the three tabs the trade reads them in:
        # what the element IS (its type and name), what it is MADE of,
        # and how it is SHAPED. One flat list of twenty fields made a
        # user scroll past the width to reach the thickness.
        self.tabs = QTabWidget()
        self._forms: dict = {}
        for key, label in (("element", tr("Cấu kiện")),
                           ("material", tr("Vật liệu")),
                           ("shape", tr("Tạo hình"))):
            host = QWidget()
            form = QFormLayout(host)
            form.setContentsMargins(0, 4, 0, 4)
            scroll = QScrollArea()
            scroll.setWidgetResizable(True)
            scroll.setWidget(host)
            self.tabs.addTab(scroll, label)
            self._forms[key] = form
        self.tabs.setMinimumHeight(150)
        lay.addWidget(self.tabs, 1)
        # Kept as an alias: the element tab is what «the form» means when
        # anything outside this panel reaches for it.
        self.form = self._forms["element"]
        self.form_host = self.form.parentWidget()

        # What the last synchronisation could not build. An element that
        # fails (a door whose host wall was deleted, a wall with no
        # baseline) simply does not appear in a parametric tool, and a
        # silent absence is the worst thing it can do — so the panel says
        # it, in the same place the user is already looking.
        # Applying the same change to every element of the kind on the
        # storey — the office's own gesture («cả tầng này dày 220»), and
        # one undo step whatever it touches.
        bulk_row = QHBoxLayout()
        self._bulk = QPushButton(tr("Áp cho cả tầng này…"))
        self._bulk.setToolTip(tr(
            "Lấy thông số đang sửa của cấu kiện này và áp cho MỌI cấu kiện "
            "cùng loại trên tầng đang vẽ — một bước hoàn tác."))
        self._bulk.clicked.connect(self._on_bulk_apply)
        bulk_row.addWidget(self._bulk)
        bulk_row.addStretch(1)
        lay.addLayout(bulk_row)

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
        """Build the three forms from the selected element's own schema."""
        for form in self._forms.values():
            while form.rowCount():
                form.removeRow(0)
        self._fields = {}
        element = self._current_element()
        self._bulk.setEnabled(element is not None)
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
            if str(key) in _CARRIED_KEYS and value is None:
                continue
            widget = self._widget_for(key, value)
            if widget is None:
                continue
            self._fields[key] = widget
            self._forms[_tab_for(key)].addRow(_field_label(key), widget)
        self._sync_material_name(element)
        self.hint.setText(tr("Edits apply to the whole model: geometry, "
                             "drawings and quantities update together."))

    def _sync_material_name(self, element) -> None:
        """The material tab states WHICH material the id names: an id like
        «gach_nhe» is not a word an office reads off a drawing."""
        material_id = str((element.get("params") or {}).get(
            "building_material_id") or "")
        if not material_id:
            return
        record = schemas.material(material_id)
        label = QLabel(tr("Vật liệu theo mã «%s»: %s (ưu tiên nối %s)")
                       % (material_id, tr(str(record.get("name") or "")),
                          int(record.get("priority", 0))))
        label.setWordWrap(True)
        label.setProperty("role", "muted")
        self._forms["material"].addRow(label)

    def _widget_for(self, key: str, value):
        if key == "steel_section":
            # A rolled section is PICKED from the catalogue, never typed:
            # «H300x150x6.5x9» is four dimensions and a mass, and a text
            # field would let a user invent a section nobody rolls.
            return self._steel_widget(value)
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

    def _steel_widget(self, value):
        """The catalogue as a grouped list, plus the way back to concrete.

        Choosing a name writes the SECTION's own dimensions as well — the
        user asked for the section, not for a 300×150 rectangle with the
        thicknesses left out.
        """
        from core.building import steel as _steel

        box = QComboBox()
        box.addItem(tr("(không dùng thép hình)"), "")
        for letter, names in _steel.families().items():
            for name in names:
                record = _steel.by_name(name) or (0.0, 0.0, 0.0, 0.0, 0.0)
                box.addItem(f"{name}   ·   {record[4]:g} kg/m", name)
        current = str(value or "")
        at = box.findData(current)
        box.setCurrentIndex(max(at, 0))
        box.currentIndexChanged.connect(
            lambda _i, k="steel_section", b=box: self._on_steel(k, b))
        return box

    def _on_steel(self, key: str, box) -> None:
        """A chosen section writes its OWN dimensions, in one undo step."""
        from core.building import commands as _commands
        from core.building import steel as _steel

        # Building the form sets the combo's index, which EMITS the change
        # — the same trap ``_on_field`` guards. Without this, every refresh
        # re-applied whatever the picker happened to be showing, so a
        # second section could never be chosen: the first write was undone
        # by the rebuild's own signal.
        if self._loading:
            return
        element = self._current_element()
        if element is None:
            return
        name = str(box.currentData() or "")
        values = {str(key): name}
        if name:
            values.update(_steel.adopt({}, name))
            values.pop("building_material_id", None)   # not what was asked
        else:
            values.update({"steel_web_mm": None, "steel_flange_mm": None})
        history = self._window.viewport.history
        command = _commands.set_params(str(element["id"]), values)
        command._rebuild = lambda s, b: sync(s, b)
        history.execute(command)
        if history.last_error:
            self.hint.setText(str(history.last_error))
            return
        self.hint.setText(
            tr("Đã lấy tiết diện %s: %g kg/m.") % (name,
                                                 _steel.mass_per_m(name))
            if name else tr("Đã bỏ tiết diện thép hình."))
        self.refresh()
        self._window.viewport.notify_scene_changed()

    def _on_bulk_apply(self) -> None:
        """Apply THIS element's current parameters to every same-kind
        element on the storey, as one undo step.

        The office's own gesture: «cả tầng này tường dày 220». Sent through
        the panel's own read path, so what is applied is what the form
        shows — never a schema default the user never saw.
        """
        from PySide6.QtWidgets import QMessageBox

        from core.history import CompoundCommand

        element = self._current_element()
        if element is None:
            return
        kind = str(element.get("type"))
        story_id = str(element.get("story_id"))
        building = self._building()
        # The element being edited is INCLUDED: the button says «cả tầng
        # này», and a user who types 220 into the thickness and presses it
        # means 220 everywhere — including the element whose form they just
        # typed in, which has not been committed by tabbing away.
        targets = [e for e in building.on_story(story_id)
                   if str(e.get("type")) == kind]
        if len(targets) < 2:
            self.hint.setText(tr(
                "Tầng này không có cấu kiện «%s» nào khác.") % _type_label(kind))
            return
        if QMessageBox.question(
                self, tr("Áp cho cả tầng"),
                tr("Áp thông số đang sửa của «%s» cho %d cấu kiện cùng loại "
                   "trên tầng này?") % (_type_label(kind), len(targets)),
                QMessageBox.Yes | QMessageBox.No,
                QMessageBox.No) != QMessageBox.Yes:
            return

        params = {key: self._read_field(key) for key in self._fields}
        params = {k: v for k, v in params.items() if v is not None}
        if not params:
            self.hint.setText(tr("Không có thông số nào để áp."))
            return
        commands = [bim_commands.set_params(str(e["id"]), params)
                    for e in targets]
        for command in commands:
            command._rebuild = lambda s, b: sync(s, b)
        history = self._window.viewport.history
        history.execute(CompoundCommand(commands))
        if history.last_error:
            self.hint.setText(str(history.last_error))
            return
        self.hint.setText(
            tr("Đã áp cho %d cấu kiện «%s» — một bước hoàn tác.")
            % (len(targets), _type_label(kind)))
        self.refresh()
        self._window.viewport.notify_scene_changed()

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
#: Parameters the panel shows although the type's schema does not carry
#: them: a value the user can set on THIS element (a steel section is
#: chosen per member), which the schema leaves out because it is not what
#: the type is BY DEFAULT.
_EXTRA_KEYS = ("name", "derived", "host_wall_id", "steel_section")

#: Never shown as an editable field.
_HIDDEN_KEYS = ("derived", "host_wall_id")

#: Shown only when the element actually carries the value — the web and
#: flange thicknesses of a chosen section are the table's, not the user's.
_CARRIED_KEYS = ("steel_web_mm", "steel_flange_mm")

#: Extra field labels that are not plain parameter ids.
_EXTRA_LABELS = {"name": "Name"}

#: The tab a parameter belongs in. The MATERIAL keys are named one by one
#: because the schema spells them differently per type (``material_id``,
#: ``frame_material_id`` …), and a substring test on «material» would put a
#: door's leaf type — a shape — in the material tab.
_MATERIAL_KEYS = frozenset({
    "building_material_id", "material_id", "frame_material_id",
    "leaf_material_id", "glass_material_id", "surface_material_id",
})

#: The parameters that describe SHAPE: the trade reads them in «Tạo hình».
_SHAPE_KEYS = frozenset({
    "thickness_mm", "height_mm", "width_mm", "depth_mm", "length_mm",
    "radius_mm", "sill_height_mm", "top_offset_mm", "offset_mm",
    "riser_mm", "tread_mm", "slope_deg", "opening_angle_deg",
    "panels", "layers", "profile", "outline_mm", "axes", "points",
})


def _tab_for(key: str) -> str:
    """Which tab one schema key belongs in."""
    if str(key) in _MATERIAL_KEYS:
        return "material"
    if str(key) in _SHAPE_KEYS:
        return "shape"
    return "element"


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
