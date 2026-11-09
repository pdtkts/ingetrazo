# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Marco Sumari Tellez and IngeTrazo contributors.
"""The Navigator: the project, its views, its sheets and its issues.

A BIM workspace answers four questions all day — what the building IS
(storeys, elements, their numbers), how it is DRAWN (the saved views and
the drawing rules), how it is PRINTED (the sheets of the set) and what
leaves the office (the issues). ArchiCAD's Navigator, Revit's Project
Browser and this dock are the same four tabs for that reason; the order
is the order the work happens in, so a reader can go top to bottom.

Everything here is a VIEW over data that already exists — the building in
``scene.plugin_data``, ``scene.saved_views``, ``scene.compositions``. The
dock owns nothing, so it cannot disagree with the model, and every list
follows the app's own scene-changed signal.
"""
from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (QAbstractItemView, QHBoxLayout, QLabel,
                               QPushButton, QTabWidget, QTreeWidget,
                               QTreeWidgetItem, QVBoxLayout, QWidget)

from core.i18n import tr


class NavigatorDock(QWidget):
    """The four tabs, rebuilt from the live document on every change."""

    def __init__(self, window) -> None:
        super().__init__(window)
        self._window = window
        self._loading = False
        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        self.tabs = QTabWidget()
        self.tabs.setDocumentMode(True)
        lay.addWidget(self.tabs)

        self.project_tree = self._make_tree()
        self.view_tree = self._make_tree()
        self.layout_tree = self._make_tree()
        self.publisher_tree = self._make_tree()
        for tree, title in ((self.project_tree, tr("Dự án")),
                            (self.view_tree, tr("Bản vẽ")),
                            (self.layout_tree, tr("Bộ tờ")),
                            (self.publisher_tree, tr("Phát hành"))):
            self.tabs.addTab(tree, title)
        self.tabs.currentChanged.connect(lambda _i: self._on_tab_shown())
        # Double-click does the obvious thing for the tab it is in: a
        # storey becomes active, a drawing opens, a sheet is shown.
        for tree in (self.project_tree, self.view_tree, self.layout_tree):
            tree.itemDoubleClicked.connect(self._on_activate)
        self.publisher_tree.itemDoubleClicked.connect(
            lambda _item, _col: self._window._on_generate_docset())

        bar = QHBoxLayout()
        bar.setContentsMargins(6, 2, 6, 6)
        self.refresh_button = QPushButton(tr("Cập nhật"))
        self.refresh_button.setToolTip(tr(
            "Đọc lại mô hình, bản vẽ và bộ tờ đang có."))
        self.refresh_button.clicked.connect(self.refresh)
        bar.addWidget(self.refresh_button)
        self.status = QLabel("")
        self.status.setProperty("role", "muted")
        bar.addWidget(self.status, 1)
        lay.addLayout(bar)
        self.refresh()

    # ---- the trees -------------------------------------------------------
    @staticmethod
    def _make_tree() -> QTreeWidget:
        tree = QTreeWidget()
        tree.setHeaderHidden(True)
        tree.setSelectionMode(QAbstractItemView.SingleSelection)
        tree.setEditTriggers(QAbstractItemView.NoEditTriggers)
        tree.setUniformRowHeights(True)
        return tree

    def _scene(self):
        return self._window.viewport.scene

    def refresh(self) -> None:
        """Rebuild every tab from the live document."""
        if self._loading:
            return
        self._loading = True
        try:
            self._fill_project()
            self._fill_views()
            self._fill_layout()
            self._fill_publisher()
        finally:
            self._loading = False
        self._on_tab_shown()

    # ---- Project ---------------------------------------------------------
    def _fill_project(self) -> None:
        """The building as it IS: project, storeys, and the elements each
        storey holds — the tree every other tab refers back to."""
        from core.building import model as building_model
        from core.building.scene_sync import TR_NAMES

        tree = self.project_tree
        tree.clear()
        building = building_model.building_of(self._scene())
        project = tree
        root = QTreeWidgetItem([str(building.project.get("name")
                                    or tr("(chưa đặt tên)"))])
        root.setData(0, Qt.UserRole, ("project", None))
        project.addTopLevelItem(root)
        for storey in sorted(building.stories,
                             key=lambda s: float(s.get("z_mm", 0.0))):
            z = float(storey.get("z_mm", 0.0))
            row = QTreeWidgetItem([f"{storey.get('name') or storey.get('id')}"
                                   f"   {z / 1000.0:+.3f} m"])
            row.setData(0, Qt.UserRole, ("story", str(storey.get("id") or "")))
            root.addChild(row)
            by_kind: dict = {}
            for element in building.elements:
                if str(element.get("story_id")) != str(storey.get("id")):
                    continue
                by_kind.setdefault(str(element.get("type")), []).append(element)
            for kind, rows in sorted(by_kind.items()):
                label = TR_NAMES.get(kind, kind)
                group = QTreeWidgetItem([f"{label}  ({len(rows)})"])
                group.setData(0, Qt.UserRole, ("kind", None))
                row.addChild(group)
                for element in rows[:200]:
                    name = str((element.get("params") or {}).get("name") or "")
                    leaf = QTreeWidgetItem([f"{label} {name}".strip()])
                    leaf.setData(0, Qt.UserRole,
                                 ("element", str(element.get("id") or "")))
                    group.addChild(leaf)
                if len(rows) > 200:
                    group.addChild(QTreeWidgetItem(
                        [tr("… và {n} cấu kiện nữa").format(n=len(rows) - 200)]))
        root.setExpanded(True)
        for i in range(root.childCount()):
            root.child(i).setExpanded(False)

    # ---- View ------------------------------------------------------------
    def _fill_views(self) -> None:
        """What is DRAWN: the saved views, and the drawings the set issues."""
        tree = self.view_tree
        tree.clear()
        scene = self._scene()
        views = list(getattr(scene, "saved_views", None) or ())
        root = QTreeWidgetItem([tr("Cảnh đã lưu") + f"  ({len(views)})"])
        tree.addTopLevelItem(root)
        for view in views:
            row = QTreeWidgetItem([str(getattr(view, "name", "") or "?")])
            row.setData(0, Qt.UserRole, ("view", str(getattr(view, "name", ""))))
            rules = []
            if getattr(view, "drawing", None):
                rules.append(tr("theo quy tắc bản vẽ"))
            if getattr(view, "hidden_layers", None):
                rules.append(tr("ẩn {n} lớp").format(
                    n=len(view.hidden_layers)))
            row.setText(0, f"{row.text(0)}   ({', '.join(rules)})" if rules
                        else row.text(0))
            root.addChild(row)
        root.setExpanded(True)

    # ---- Layout ----------------------------------------------------------
    def _fill_layout(self) -> None:
        """What is PRINTED: the sheets of the document, in issue order."""
        tree = self.layout_tree
        tree.clear()
        sheets = list(getattr(self._scene(), "compositions", None) or ())
        root = QTreeWidgetItem([tr("Bộ tờ") + f"  ({len(sheets)})"])
        tree.addTopLevelItem(root)
        for sheet in sheets:
            name = str(getattr(sheet, "name", "") or "?")
            frames = len(getattr(sheet, "frames", None) or ())
            row = QTreeWidgetItem([f"{name}   ({frames})" if frames else name])
            row.setData(0, Qt.UserRole, ("sheet", name))
            if getattr(sheet, "bim_key", ""):
                row.setToolTip(0, tr("Tờ do máy sinh — phát hành lại sẽ thay"))
            root.addChild(row)
        root.setExpanded(True)

    # ---- Publisher -------------------------------------------------------
    def _fill_publisher(self) -> None:
        """What LEAVES: the runs this session has made, newest first."""
        tree = self.publisher_tree
        tree.clear()
        root = QTreeWidgetItem([tr("Lần phát hành này")])
        tree.addTopLevelItem(root)
        for label, hint in (
                (tr("Lập hồ sơ tự động…"),
                 tr("Sinh bộ bản vẽ từ mô hình")),
                (tr("Xuất bộ tờ PDF…"),
                 tr("In toàn bộ tờ ra một PDF")),
                (tr("Xuất DXF bản vẽ…"),
                 tr("Xuất mặt bằng ra DXF cho CAD khác")),
                (tr("Bảng thống kê (CSV)…"),
                 tr("Khối lượng ra CSV cho Excel"))):
            row = QTreeWidgetItem([label])
            row.setToolTip(0, hint)
            row.setData(0, Qt.UserRole, ("action", label))
            root.addChild(row)
        root.setExpanded(True)
        self.status.setText(tr("Chọn một mục rồi Enter, hoặc bấm đúp."))

    # ---- the actions -----------------------------------------------------
    def _on_tab_shown(self) -> None:
        index = self.tabs.currentIndex()
        titles = (tr("Dự án: tầng và cấu kiện"),
                  tr("Bản vẽ: cảnh đã lưu và quy tắc"),
                  tr("Bộ tờ: những tờ sẽ in"),
                  tr("Phát hành: các lệnh xuất"))
        self.status.setText(titles[index] if 0 <= index < len(titles) else "")

    def _on_activate(self, item: QTreeWidgetItem, _column: int = 0) -> None:
        """Double-click: do the thing the row IS.

        A storey becomes active, an element is selected in the model, a
        drawing is opened for editing, a sheet is shown. Selecting rather
        than mutating keeps the dock a navigator — the only write is the
        active storey, which is what «go to this storey» means for a
        drawing tool.
        """
        data = item.data(0, Qt.UserRole)
        if not data:
            return
        kind, value = data
        if kind == "story" and value:
            from core.building import model as building_model

            building_model.building_of(self._scene()).set_active_story(value)
            self._window.statusBar().showMessage(
                tr("Tầng đang vẽ: %s") % item.text(0).split("   ")[0], 3000)
            self._notify()
        elif kind == "element" and value:
            self._select_element(value)
        elif kind == "view" and value:
            self._open_view(value)
        elif kind == "sheet" and value:
            self._window.statusBar().showMessage(
                tr("Tờ: %s") % value, 3000)
        elif kind == "action":
            self._run_publisher_action(value)

    def _select_element(self, element_id: str) -> None:
        from core.building.scene_sync import group_for

        scene = self._scene()
        group = group_for(scene, str(element_id))
        if group is not None:
            scene.select([group])
            self._notify()

    def _open_view(self, name: str) -> None:
        """Show a saved view: the viewport's camera takes it on."""
        scene = self._scene()
        view = next((v for v in (getattr(scene, "saved_views", None) or ())
                     if str(getattr(v, "name", "")) == str(name)), None)
        if view is None:
            return
        viewport = self._window.viewport
        # The view's own recall: camera, then the layer visibility it
        # recorded — the app's own path, so a saved view behaves the same
        # whether it is recalled here, from the tray or from the sheet.
        view.apply(scene, viewport.camera)
        self._notify()

    def _run_publisher_action(self, label: str) -> None:
        """The publisher rows run the app's own menu actions.

        The commands live in one place (the BIM menu); the dock asks for
        the one whose text matches, so the two can never drift apart and
        a command added to the menu is reachable here without an edit.
        """
        menu = getattr(self._window, "_bim_menu", None)
        if menu is None:
            return
        for action in menu.actions():
            if str(action.text()) == str(label) and action.isEnabled():
                action.trigger()
                return

    def _notify(self) -> None:
        viewport = getattr(self._window, "viewport", None)
        notify = getattr(viewport, "notify_scene_changed", None)
        if callable(notify):
            notify()
        else:                                       # pragma: no cover
            viewport.update()
