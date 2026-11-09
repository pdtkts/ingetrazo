# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Marco Sumari Tellez and IngeTrazo contributors.
"""The Plan window — the storey drawn flat, the way the office reads it.

The 3D viewport answers "what does it look like"; this answers "what does
it measure". It draws the active storey through the SAME rule the issued
sheet uses (:func:`core.building.drawings.view_for` — the +1200 cut, the
floor trim, the storey's own extent) and the SAME hidden-line renderer
(:func:`core.hlr.hlr_drawing`), so what is on screen and what comes out of
the printer cannot drift apart: there is no second projection anywhere in
this file.

It is deliberately read-and-measure first. The tool bar is built from
``registry.PLAN_BAR`` — every command the workspace declares, in its own
order and groups, each with the keys the shortcut table gives it — and a
command this build cannot run yet is shown DISABLED with the reason in its
tooltip. Showing the full bar (rather than only what exists) is what makes
the workspace legible: a hand reaching for "trim" finds out it is not
there yet instead of finding nothing.

Nothing in this module is undoable: it only looks. Its one write is the
selection it hands to the main window, so the existing property panel and
the 3D view follow the click.
"""
from __future__ import annotations

import math

from PySide6.QtCore import QPointF, QRectF, Qt
from PySide6.QtGui import QColor, QFont, QPainter, QPen, QPolygonF
from PySide6.QtWidgets import (QCheckBox, QComboBox, QDialog,
                               QDialogButtonBox, QDoubleSpinBox, QFormLayout,
                               QHBoxLayout, QLabel, QLineEdit, QPushButton,
                               QScrollArea, QSizePolicy, QSpinBox,
                               QTableWidget, QTableWidgetItem, QToolButton,
                               QVBoxLayout, QWidget)

from core.i18n import tr

#: Paper millimetres per screen pixel at zoom 1 — the scale the window
#: opens at before ``fit`` frames the storey.
BASE_MM_PER_PX = 4.0

#: The scales the office uses, as the drawing's own denominators.
STANDARD_SCALES = (1, 2, 5, 10, 20, 25, 50, 100, 200, 500, 1000)

def key_for_command(cmd_id: str) -> str:
    """The keystroke the workspace gives a plan command (``""`` if none).

    ``registry.PLAN_KEYS`` is written the other way round — key → command,
    the way a shortcut handler reads it — so it is inverted here, once,
    rather than at every use (reading it forwards gives every command an
    empty key, which looks like a workspace that has none).
    """
    from core.building import registry

    for key, cmd in registry.PLAN_KEYS.items():
        if str(cmd) == str(cmd_id):
            return str(key)
    return ""


#: Plan command id → the application's own tool key. Only what the tool
#: table actually has: the rest of the bar stays disabled and says so.
COMMAND_TOOLS = {
    "select": "select", "protractor": "protractor", "measure": "tape",
    "move": "move", "rotate": "rotate", "scale": "scale",
    "offset": "offset", "eraser": "eraser", "flip": "flip",
    "line": "line", "polyline": "freehand", "rect": "rectangle",
    "rrect": "rotated_rect", "polygon": "polygon", "circle": "circle",
    "arc2": "arc", "arc3": "arc3", "spline": "freehand",
    "wall": "wall", "curtain_wall": "curtain_wall", "column": "column",
    "beam": "beam", "slab": "slab", "ceiling": "ceiling", "roof": "roof",
    "door": "door", "window": "window", "zone": "zone",
    "fixture": "fixture", "section": "section", "text": "text",
    "dim": "dimension", "pushpull": "pushpull", "paint": "paint",
}


class _Canvas(QWidget):
    """The drawing surface: the plan in model millimetres, painted flat.

    Coordinates are the MODEL's own (millimetres, y up as the plan reads
    it), with one transform to screen pixels — pan and zoom are that
    transform, never a change to the drawing, so picking and painting can
    never disagree about where a wall is.
    """

    def __init__(self, window, plan) -> None:
        super().__init__(window if isinstance(window, QWidget) else plan)
        self._plan = plan
        self.scale_px_per_mm = 1.0 / BASE_MM_PER_PX
        self.offset = QPointF(0.0, 0.0)        # screen position of model 0,0
        self._drag_from = None
        self._segs: list = []
        self._loops: list = []
        self._marks: list = []
        self._bbox = (0.0, 0.0, 1.0, 1.0)
        self._selected = None
        #: ``(kind, element_id, grab)`` while a left drag edits the model:
        #: ``kind`` is "body" or "handle", ``grab`` the model point the
        #: drag started from. ``None`` means a left press is only a pick.
        self._edit = None
        #: Fit on the first real resize, not in the constructor: the widget
        #: has a placeholder size (320x240) until the layout runs, and a
        #: fit against that frames the plan against the wrong box.
        self._needs_fit = True
        self.setMouseTracking(True)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        self.setMinimumSize(320, 240)
        self.setFocusPolicy(Qt.StrongFocus)

    # ---- the drawing -----------------------------------------------------
    def reload(self) -> None:
        """Recompute the drawing from the model (the only source of truth)."""
        self._segs, self._loops, self._marks, self._bbox = \
            self._plan.build_drawing()
        if self._needs_fit:
            self.fit()
        self.update()

    #: How close (in screen pixels) a press must be to an element's own
    #: end to count as its handle rather than its body.
    HANDLE_PX = 7.0

    def to_screen(self, x_mm: float, y_mm: float) -> QPointF:
        k = self.scale_px_per_mm
        return QPointF(self.offset.x() + x_mm * k,
                       self.offset.y() - y_mm * k)   # y up on the plan

    def to_model(self, point: QPointF) -> tuple:
        k = self.scale_px_per_mm or 1.0
        return ((point.x() - self.offset.x()) / k,
                (self.offset.y() - point.y()) / k)

    def resizeEvent(self, event) -> None:           # noqa: N802 — Qt
        super().resizeEvent(event)
        if self._needs_fit and self.width() > 40 and self.height() > 40:
            self._needs_fit = False
            self.fit()

    def fit(self) -> None:
        """Frame the whole storey with a margin, at a standard scale."""
        x0, y0, x1, y1 = self._bbox
        width = max(x1 - x0, 1.0)
        height = max(y1 - y0, 1.0)
        w = max(self.width(), 40)
        h = max(self.height(), 40)
        margin = 0.85
        need = min(w * margin / width, h * margin / height)
        self.scale_px_per_mm = float(need)
        cx, cy = (x0 + x1) / 2.0, (y0 + y1) / 2.0
        self.offset = QPointF(w / 2.0 - cx * need, h / 2.0 + cy * need)
        self.update()

    def zoom_by(self, factor: float, around: QPointF | None = None) -> None:
        """Zoom about a screen point (the cursor, by default the centre)."""
        around = around or QPointF(self.width() / 2.0, self.height() / 2.0)
        before = self.to_model(around)
        self.scale_px_per_mm = max(1e-6, self.scale_px_per_mm * factor)
        after = self.to_model(around)
        k = self.scale_px_per_mm
        self.offset += QPointF((after[0] - before[0]) * k,
                               -(after[1] - before[1]) * k)
        self.update()

    # ---- interaction -----------------------------------------------------
    def wheelEvent(self, event) -> None:            # noqa: N802 — Qt
        steps = event.angleDelta().y() / 120.0
        if steps:
            self.zoom_by(1.2 ** steps, event.position())
        event.accept()

    def mousePressEvent(self, event) -> None:       # noqa: N802 — Qt
        if event.button() in (Qt.MiddleButton, Qt.RightButton):
            self._drag_from = event.position()
            event.accept()
            return
        if event.button() == Qt.LeftButton:
            model = self.to_model(event.position())
            hit = self._plan.element_at(model)
            if hit is not None and hit == self._selected:
                # A second press ON the selected element takes its handle
                # instead of re-picking it: the first click says what to
                # change, the drag from there says how.
                handle = self._plan.handle_hit(
                    hit, model, self.HANDLE_PX / self.scale_px_per_mm)
                self._edit = ("handle" if handle else "body", hit, model)
                event.accept()
                return
            self._selected = hit
            self._edit = None
            self._plan.select(hit)
            self.update()
            event.accept()

    def mouseMoveEvent(self, event) -> None:        # noqa: N802 — Qt
        if self._edit is not None:
            kind, element_id, grab = self._edit
            self._plan.drag_element(element_id, self.to_model(event.position()),
                                    grab, kind)
            self.update()
            event.accept()
            return
        if self._drag_from is not None:
            delta = event.position() - self._drag_from
            self.offset += delta
            self._drag_from = event.position()
            self.update()
            event.accept()
            return
        name = self._plan.element_name_at(self.to_model(event.position()))
        self._plan.report_hover(name)

    def mouseDoubleClickEvent(self, event) -> None:  # noqa: N802 — Qt
        if event.button() == Qt.LeftButton:
            hit = self._plan.element_at(self.to_model(event.position()))
            if hit is not None:
                self._selected = hit
                self._plan.edit_element(hit)
                event.accept()

    def mouseReleaseEvent(self, event) -> None:     # noqa: N802 — Qt
        if event.button() == Qt.LeftButton and self._edit is not None:
            kind, element_id, grab = self._edit
            self._edit = None
            self._plan.finish_drag(element_id, grab, kind)
            event.accept()
            return
        if event.button() in (Qt.MiddleButton, Qt.RightButton):
            self._drag_from = None
            event.accept()

    def _paint_handles(self, painter: QPainter) -> None:
        """The selected element's own ends: where a drag would pull.

        The square is drawn where the handle is actually taken, so the
        affordance and the hit test cannot disagree.
        """
        if self._selected is None:
            return
        ends = self._plan._ends_of(self._selected)
        if ends is None:
            return
        painter.setPen(QPen(QColor("#1e6fd9"), 1.2))
        painter.setBrush(QColor("#FFFFFF"))
        half = self.HANDLE_PX
        for x_mm, y_mm in ends:
            at = self.to_screen(x_mm, y_mm)
            painter.drawRect(QRectF(at.x() - half / 2.0, at.y() - half / 2.0,
                                    half, half))

    def paintEvent(self, _event) -> None:           # noqa: N802 — Qt
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing, True)
        painter.fillRect(self.rect(), QColor("#FFFFFF"))
        self._paint_loops(painter)
        self._paint_segs(painter)
        self._paint_marks(painter)
        self._paint_handles(painter)
        painter.end()

    def _paint_loops(self, painter: QPainter) -> None:
        if not self._loops:
            return
        painter.setBrush(QColor(166, 166, 166))     # #A6A6A6 — the cut fill
        painter.setPen(Qt.NoPen)
        for ring in self._loops:
            if len(ring) < 3:
                continue
            poly = QPolygonF([self.to_screen(float(p[0]), float(p[1]))
                              for p in ring])
            painter.drawPolygon(poly)

    def _paint_segs(self, painter: QPainter) -> None:
        # The same pen table the sheet and the DXF use: the cut heaviest,
        # profiles heavy, plain edges light.
        pens = {
            2: QPen(QColor("#000000"), 1.6),        # cut
            1: QPen(QColor("#000000"), 0.9),        # profile
            0: QPen(QColor("#808080"), 0.5),        # edge
            3: QPen(QColor("#9AA5AE"), 0.5, Qt.DashLine),   # hidden
        }
        for entry in self._segs:
            kind = int(entry[4]) if len(entry) > 4 else 0
            painter.setPen(pens.get(kind, pens[0]))
            painter.drawLine(self.to_screen(float(entry[0]), float(entry[1])),
                             self.to_screen(float(entry[2]), float(entry[3])))

    def _paint_marks(self, painter: QPainter) -> None:
        if not self._marks:
            return
        font = QFont()
        font.setPointSizeF(max(7.0, min(12.0, self.scale_px_per_mm * 300.0)))
        painter.setFont(font)
        painter.setPen(QPen(QColor("#1e242c")))
        for text, x_mm, y_mm in self._marks:
            painter.drawText(self.to_screen(x_mm, y_mm), str(text))


class PlanWindow(QDialog):
    """The storey's plan, its scale, and the workspace's tool bar."""

    def __init__(self, window) -> None:
        parent = window if isinstance(window, QWidget) else None
        super().__init__(parent)
        self.setWindowTitle(tr("Cửa sổ Plan"))
        self.resize(980, 640)
        self._window = window
        self._scene = window.viewport.scene
        self._building = None
        self._story_id = ""
        self._view = None
        #: The drag in progress: the parameters being previewed, and the
        #: payload Undo must return to (captured at the first move).
        self._pending = None
        self._drag_origin = None
        self._drag_base = None
        self._last_moved = None

        lay = QVBoxLayout(self)

        top = QHBoxLayout()
        top.addWidget(QLabel(tr("Tầng:")))
        self.story_box = QComboBox()
        self.story_box.currentIndexChanged.connect(self._on_story)
        top.addWidget(self.story_box)
        top.addWidget(QLabel(tr("Tỷ lệ 1:")))
        self.scale_box = QSpinBox()
        self.scale_box.setRange(1, 2000)
        self.scale_box.setValue(100)
        self.scale_box.valueChanged.connect(self._on_scale)
        top.addWidget(self.scale_box)
        fit = QPushButton(tr("Vừa khung"))
        fit.clicked.connect(self.fit)
        top.addWidget(fit)
        zin = QPushButton(tr("Phóng to"))
        zin.clicked.connect(lambda: self.canvas.zoom_by(1.25))
        top.addWidget(zin)
        zout = QPushButton(tr("Thu nhỏ"))
        zout.clicked.connect(lambda: self.canvas.zoom_by(1 / 1.25))
        top.addWidget(zout)
        keys = QPushButton(tr("Phím tắt…"))
        keys.setToolTip(tr("Xem phím tắt mặc định của cửa sổ Plan"))
        keys.clicked.connect(self.show_shortcuts)
        top.addWidget(keys)
        top.addStretch(1)
        lay.addLayout(top)

        body = QHBoxLayout()
        self.canvas = _Canvas(window, self)
        body.addWidget(self.bar_widget(), 0)
        body.addWidget(self.canvas, 1)
        lay.addLayout(body, 1)

        self.status = QLabel("")
        self.status.setWordWrap(True)
        self.status.setProperty("role", "muted")
        lay.addWidget(self.status)

        self.refresh()

    # ---- the tool bar ----------------------------------------------------
    def bar_widget(self) -> QWidget:
        """The vertical bar, built from the registry's own tables.

        Every command of ``PLAN_BAR`` gets a button in its declared group
        and order. One this build can run is enabled; one it cannot is
        DISABLED with the reason in the tooltip — a bar that silently
        omits a tool teaches the wrong workspace.
        """
        from core.building import registry

        host = QWidget()
        col = QVBoxLayout(host)
        col.setContentsMargins(2, 2, 4, 2)
        col.setSpacing(3)
        self.bar_buttons: dict = {}
        for group, ids in registry.PLAN_BAR:
            for cmd_id in ids:
                found = registry.find(cmd_id)
                label = str(found[1]) if found else str(cmd_id)
                button = QToolButton()
                button.setText(tr(label))
                button.setToolButtonStyle(Qt.ToolButtonTextOnly)
                button.setMinimumWidth(74)
                key = key_for_command(cmd_id)
                tool = self._tool_for(cmd_id)
                if tool is None or not self._tool_available(tool):
                    button.setEnabled(False)
                    button.setToolTip(
                        tr("%s — công cụ này chưa có trong bản dựng.") % label)
                else:
                    button.setToolTip(f"{label} ({key})" if key else label)
                    button.clicked.connect(
                        lambda _checked=False, t=tool: self._run_tool(t))
                col.addWidget(button)
                self.bar_buttons[cmd_id] = button
        col.addStretch(1)
        # A scrollable column: sixty-one buttons must never decide how tall
        # the window is — the drawing does.
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        scroll.setWidget(host)
        scroll.setMaximumWidth(120)
        return scroll

    def _tool_for(self, cmd_id: str):
        """The application's tool key a plan command maps to, or ``None``.

        The plan window implements no tools of its own: it asks the main
        window's own tool table, so a command behaves the same whether it
        starts here or from the toolbar. A command the application does
        not have is shown DISABLED with the reason (see the class
        docstring) rather than faked with a look-alike that would do
        something subtly different.
        """
        return COMMAND_TOOLS.get(str(cmd_id))

    def _run_tool(self, tool_key: str) -> None:
        activate = getattr(self._window, "_activate_tool", None)
        if callable(activate):
            activate(tool_key)

    # ---- reading the model ----------------------------------------------
    def refresh(self) -> None:
        """Re-read the building and the storey list, then redraw."""
        from core.building.model import building_of

        self._building = building_of(self._scene)
        keep = self._story_id
        self.story_box.blockSignals(True)
        self.story_box.clear()
        ordered = sorted(self._building.stories,
                         key=lambda s: float(s.get("z_mm", 0.0)))
        for story in ordered:
            self.story_box.addItem(str(story.get("name") or story["id"]),
                                   str(story["id"]))
        if keep:
            at = self.story_box.findData(keep)
            self.story_box.setCurrentIndex(max(at, 0))
        self.story_box.blockSignals(False)
        self._story_id = str(self.story_box.currentData() or "")
        self._on_story()

    def _tool_available(self, tool_key: str) -> bool:
        """Whether the application actually has this tool loaded."""
        return tool_key in getattr(self._window, "_tools", {})

    def _on_story(self) -> None:
        self._story_id = str(self.story_box.currentData() or "")
        from core.building import drawings as _drawings
        if not self._story_id or self._building is None:
            self._view = None
            self.canvas.reload()
            return
        self._view = _drawings.view_for(
            self._building, {"kind": "story", "story_id": self._story_id})
        self.scale_box.blockSignals(True)
        self.scale_box.setValue(int(self._view.scale_denom))
        self.scale_box.blockSignals(False)
        self.canvas.reload()
        self._say(tr("Tầng %s — cao độ cắt +%d mm, tỷ lệ 1:%d")
                  % (self.story_box.currentText(),
                     int(_drawings.DEFAULT_CUT_MM),
                     int(self._view.scale_denom)))

    def _on_scale(self, value: int) -> None:
        if self._view is None:
            return
        self._view.scale_denom = float(max(int(value), 1))
        self.canvas.reload()

    def fit(self) -> None:
        self.canvas.fit()

    def _say(self, text: str) -> None:
        self.status.setText(str(text))

    def report_hover(self, name: str) -> None:
        if name:
            self._say(tr("Dưới con trỏ: %s") % name)

    # ---- what the canvas asks of the model ------------------------------
    def build_drawing(self):
        """``(segs, loops, marks, bbox)`` for the active storey, in metres.

        The rule is the drawing's and the linework is the same hidden-line
        pass the sheet runs, so this window cannot disagree with the paper.
        """
        from core.building import drawings as _drawings
        from core.hlr import hlr_drawing

        if self._view is None or self._building is None:
            return ([], [], [], (0.0, 0.0, 1000.0, 1000.0))
        try:
            drawing = hlr_drawing(
                self._scene, self._view.camera(), profiles=True,
                fills=True, hidden=True,
                clip_planes=self._view.clip_planes,
                section=(self._view.section_planes[0]
                         if self._view.section_planes else None))
        except Exception as exc:                    # noqa: BLE001 — reported
            self._say(f"{type(exc).__name__}: {exc}")
            return ([], [], [], (0.0, 0.0, 1000.0, 1000.0))
        # The hidden-line pass works in the CAMERA plane, with its origin
        # at the view's target — not at the model's. Adding the target's
        # own plan position puts the linework back in model millimetres,
        # which is the space the marks and the picking already use; without
        # it the drawing slides by half the storey and the pointer picks
        # something the user is not looking at.
        target = self._view.target
        dx = float(target[0]) * 1000.0
        dy = float(target[1]) * 1000.0
        segs = [[float(s[0]) * 1000.0 + dx, float(s[1]) * 1000.0 + dy,
                 float(s[2]) * 1000.0 + dx, float(s[3]) * 1000.0 + dy,
                 int(k)] for s, k in zip(drawing.segs, drawing.kinds)]
        loops = [[(float(p[0]) * 1000.0 + dx, float(p[1]) * 1000.0 + dy)
                  for p in ring] for ring in (drawing.loops or ())]
        marks = self._marks()
        box = _drawings.story_box(self._building,
                                  self._building.story(self._story_id)
                                  or {})
        return (segs, loops, marks, box)

    def _marks(self) -> list:
        """The opening tags and room stamps the plan carries."""
        from core.building import drawings as _drawings

        story = self._building.story(self._story_id) if self._building \
            else None
        if story is None:
            return []
        out: list = []
        for name, x_mm, y_mm in _drawings.opening_tags(self._building,
                                                       story):
            out.append((name, x_mm, y_mm))
        for zone in [e for e in self._building.elements
                     if str(e.get("story_id")) == str(story["id"])
                     and e.get("type") == "zone"]:
            outline = (zone.get("params") or {}).get("outline_mm") or []
            if len(outline) < 3:
                continue
            cx = sum(float(p[0]) for p in outline) / len(outline)
            cy = sum(float(p[1]) for p in outline) / len(outline)
            area = (zone.get("derived") or {}).get("area_m2")
            label = str((zone.get("params") or {}).get("name") or "Phòng")
            out.append((label if area is None else f"{label} {area:.1f} m²",
                        cx, cy))
        return out

    def element_at(self, point_mm) -> str | None:
        """The element whose plan extent contains a model point, or None.

        Picking is by the same extents the drawing frames — walls by their
        baseline (widened to the body) and everything else by its own
        centre or outline — so what the user points at is what they see.
        """
        story = self._building.story(self._story_id) if self._building \
            else None
        if story is None:
            return None
        x, y = float(point_mm[0]), float(point_mm[1])
        best = None
        best_d = 1e18
        for element in self._building.elements:
            if str(element.get("story_id")) != str(story["id"]):
                continue
            params = element.get("params") or {}
            pad = max(float(params.get("thickness_mm", 200.0) or 200.0) / 2.0,
                      float(params.get("width_mm", 0.0) or 0.0) / 2.0,
                      150.0)
            d = _distance_to_element(element, x, y)
            if d is not None and d <= pad and d < best_d:
                best, best_d = str(element["id"]), d
        return best

    def element_name_at(self, point_mm) -> str:
        """The words the panel and the drawing use for the element here."""
        found = self.element_at(point_mm)
        if not found or self._building is None:
            return ""
        element = self._building.element(found)
        if element is None:
            return ""
        from core.building.scene_sync import TR_NAMES

        kind = TR_NAMES.get(str(element.get("type")),
                            str(element.get("type")))
        label = str((element.get("params") or {}).get("name") or "").strip()
        return f"{kind} {label}".strip()

    def select(self, element_id) -> None:
        """Hand the selection to the app, so the panel and the 3D follow."""
        from core.building.scene_sync import group_for

        scene = self._scene
        if element_id is None:
            scene.selection.clear()
        else:
            group = group_for(scene, str(element_id))
            if group is not None:
                scene.select([group])
        notify = getattr(self._window, "on_scene_changed", None)
        if callable(notify):
            notify()
        else:
            self._window.viewport.update()

    # ---- editing the model from the plan --------------------------------
    def handle_hit(self, element_id, point_mm, radius_mm: float):
        """Which end of the element a point grabs — ``"start"``/``"end"``.

        ``None`` when the point is not within ``radius_mm`` of either end.
        An element that is a point rather than a line (a fixture, a zone
        stamp) has no handle: it moves, it does not stretch.
        """
        ends = self._ends_of(element_id)
        if ends is None:
            return None
        (sx, sy), (ex, ey) = ends
        if math.hypot(sx - point_mm[0], sy - point_mm[1]) <= radius_mm:
            return "start"
        if math.hypot(ex - point_mm[0], ey - point_mm[1]) <= radius_mm:
            return "end"
        return None

    def _ends_of(self, element_id):
        """``((x, y), (x, y))`` in model millimetres, or ``None``."""
        element = self._building.element(element_id) if self._building \
            else None
        if element is None:
            return None
        params = element.get("params") or {}
        start = params.get("baseline_start_mm")
        end = params.get("baseline_end_mm")
        if start and end and len(start) >= 2 and len(end) >= 2:
            return ((float(start[0]), float(start[1])),
                    (float(end[0]), float(end[1])))
        outline = params.get("outline_mm") or []
        if len(outline) >= 1 and element.get("type") == "zone":
            xs = [float(p[0]) for p in outline]
            ys = [float(p[1]) for p in outline]
            return ((min(xs), min(ys)), (max(xs), max(ys)))
        return None

    def drag_element(self, element_id, point_mm, grab, kind: str) -> None:
        """Preview one drag step: move the body, or pull one end.

        The preview is the model itself — the element's own parameters
        change and the scene is resynced — so what the user sees while
        dragging IS what the numbers say. Nothing goes through the
        history until the drag ends, because a drag is ONE undo step and
        a hundred steps of one millimetre are not what anybody wants.
        """
        element = self._building.element(element_id) if self._building \
            else None
        if element is None:
            return
        if self._drag_origin is None:
            # First move of the drag: this payload is what Undo must put
            # back, so it is captured before anything changes.
            import copy

            self._drag_origin = (str(element_id),
                                 copy.deepcopy(self._scene.plugin_data))
            # The BASE is the element as it stood when the drag began.
            # Every move recomputes from it: adding the delta to the
            # already-moved parameters drifts by the whole path walked.
            self._drag_base = copy.deepcopy(element.get("params") or {})
        base = self._drag_base or {}
        dx = float(point_mm[0]) - float(grab[0])
        dy = float(point_mm[1]) - float(grab[1])
        if kind == "handle":
            ends = self._ends_of(element_id)
            if ends is None:
                return
            (sx, sy), (ex, ey) = ends
            # The moving end reads its base position; the fixed one is
            # taken from the base too, so the far end cannot creep.
            b_start = base.get("baseline_start_mm") or [sx, sy]
            b_end = base.get("baseline_end_mm") or [ex, ey]
            near_end = self._near_end(element_id, grab)
            if near_end == "end":
                moved = {"baseline_end_mm": [round(float(b_end[0]) + dx),
                                             round(float(b_end[1]) + dy)]}
            else:
                moved = {"baseline_start_mm": [round(float(b_start[0]) + dx),
                                               round(float(b_start[1]) + dy)]}
        else:
            moved = self._moved_params(base, base, dx, dy)
        if not moved:
            return
        self._pending = self._last_moved = moved
        element.setdefault("params", {}).update(moved)
        self._resync_preview()

    def _near_end(self, element_id, point) -> str:
        """Which end a grab point is closer to, of the element's two."""
        ends = self._ends_of(element_id)
        if ends is None:
            return "end"
        (sx, sy), (ex, ey) = ends
        ds = math.hypot(sx - point[0], sy - point[1])
        de = math.hypot(ex - point[0], ey - point[1])
        return "start" if ds <= de else "end"

    def _resync_preview(self) -> None:
        """Redraw from the model as it now stands, without the history."""
        from core.building.scene_sync import sync

        try:
            sync(self._scene)
        except Exception as exc:                    # noqa: BLE001 — reported
            self._say(f"{type(exc).__name__}: {exc}")
        self.canvas.reload()

    def _moved_params(self, element, params: dict, dx: float, dy: float) -> dict:
        """The parameters a body drag of ``(dx, dy)`` millimetres changes."""
        out: dict = {}
        start = params.get("baseline_start_mm")
        end = params.get("baseline_end_mm")
        if start and end and len(start) >= 2 and len(end) >= 2:
            out["baseline_start_mm"] = [round(float(start[0]) + dx),
                                        round(float(start[1]) + dy)]
            out["baseline_end_mm"] = [round(float(end[0]) + dx),
                                      round(float(end[1]) + dy)]
        outline = params.get("outline_mm") or []
        if len(outline) >= 3:
            out["outline_mm"] = [[round(float(p[0]) + dx), round(float(p[1]) + dy)]
                                 for p in outline]
        centre = params.get("center_mm")
        if centre and len(centre) >= 2:
            out["center_mm"] = [round(float(centre[0]) + dx),
                                round(float(centre[1]) + dy)]
        return out

    def finish_drag(self, element_id, grab, kind: str) -> None:
        """A drag ended: put the state back, then make ONE undo step of it."""
        del grab, kind
        moved, self._last_moved = self._last_moved, None
        self._pending = None
        origin, self._drag_origin = self._drag_origin, None
        self._drag_base = None
        if not moved or origin is None or str(origin[0]) != str(element_id):
            return
        from core.building import commands as bim_commands
        from core.building.scene_sync import sync

        element = self._building.element(element_id) if self._building \
            else None
        if element is None:
            return
        # Put the payload back the way it was, then run the change as a
        # real command: the command stores the ORIGINAL as its before
        # state, so one Undo returns the element to where it started.
        self._scene.plugin_data = origin[1]
        if hasattr(self._scene, "_building_cache"):
            del self._scene._building_cache
        command = bim_commands.set_params(str(element_id), moved)
        command._rebuild = lambda s, b: sync(s, b)
        history = getattr(self._window.viewport, "history", None)
        if history is None:
            return
        history.execute(command)
        if history.last_error:
            self._say(str(history.last_error))
        self.refresh()
        self.select(element_id)
        self._say(tr("Đã sửa %s") % (self.element_name_at(
            self._element_centre(element_id)) or str(element_id)))
        notify = getattr(self._window, "on_scene_changed", None)
        if callable(notify):
            notify()

    def _element_centre(self, element_id):
        ends = self._ends_of(element_id)
        if ends is None:
            return (0.0, 0.0)
        (sx, sy), (ex, ey) = ends
        return ((sx + ex) / 2.0, (sy + ey) / 2.0)

    def edit_element(self, element_id) -> None:
        """The properties dialog for one element (double-click on the plan)."""
        dialog = PlanPropertiesDialog(self, element_id)
        dialog.exec()
        self.refresh()

    # ---- the shortcut table ---------------------------------------------
    def show_shortcuts(self) -> None:
        dialog = PlanShortcutsDialog(self)
        dialog.exec()


class PlanShortcutsDialog(QDialog):
    """Every plan command with the key this workspace gives it."""

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        from core.building import registry

        self.setWindowTitle(tr("Phím tắt cửa sổ Plan"))
        lay = QVBoxLayout(self)
        self.filter = QLineEdit()
        self.filter.setPlaceholderText(tr("Tìm lệnh hoặc phím…"))
        self.filter.textChanged.connect(self._apply_filter)
        lay.addWidget(self.filter)
        self.table = QTableWidget(0, 3)
        self.table.setHorizontalHeaderLabels(
            [tr("Lệnh"), tr("Nhóm"), tr("Phím")])
        self.table.verticalHeader().setVisible(False)
        self.table.setEditTriggers(QTableWidget.NoEditTriggers)
        self.table.setSelectionBehavior(QTableWidget.SelectRows)
        groups_of = {cmd_id: group for group, ids in registry.PLAN_BAR
                     for cmd_id in ids}
        for group, ids in registry.PLAN_BAR:
            for cmd_id in ids:
                found = registry.find(cmd_id)
                label = str(found[1]) if found else str(cmd_id)
                row = self.table.rowCount()
                self.table.insertRow(row)
                self.table.setItem(row, 0, QTableWidgetItem(tr(label)))
                self.table.setItem(row, 1, QTableWidgetItem(tr(group)))
                self.table.setItem(
                    row, 2, QTableWidgetItem(key_for_command(cmd_id)))
        del groups_of
        lay.addWidget(self.table, 1)
        buttons = QDialogButtonBox(QDialogButtonBox.Close)
        buttons.rejected.connect(self.reject)
        buttons.accepted.connect(self.accept)
        lay.addWidget(buttons)
        self.table.resizeColumnsToContents()

    def _apply_filter(self, text: str) -> None:
        needle = (text or "").strip().lower()
        for row in range(self.table.rowCount()):
            cells = [self.table.item(row, col) for col in range(3)]
            hay = " ".join(str(c.text() if c else "") for c in cells).lower()
            self.table.setRowHidden(row, bool(needle) and needle not in hay)


class PlanPropertiesDialog(QDialog):
    """One element's own parameters, editable in place.

    The fields are the SCHEMA's — read from ``elements.DEFAULTS`` — so a
    parameter added to a builder appears here without touching this file,
    and a value that is not a number is not offered as one.
    """

    #: Parameters the plan itself sets (they are what a drag changes).
    DRAGGED = ("baseline_start_mm", "baseline_end_mm", "outline_mm",
               "center_mm", "host_wall_id")

    def __init__(self, plan, element_id: str) -> None:
        super().__init__(plan)
        from core.building import elements as schemas

        self._plan = plan
        self._element_id = str(element_id)
        building = plan._building
        element = building.element(self._element_id) if building else None
        kind = str(element.get("type")) if element else ""
        self._kind = kind
        self.setWindowTitle(tr("Thuộc tính %s") % tr(kind))
        self.fields: dict = {}
        lay = QVBoxLayout(self)
        if element is None:
            lay.addWidget(QLabel(tr("Không tìm thấy cấu kiện.")))
            buttons = QDialogButtonBox(QDialogButtonBox.Close)
            buttons.rejected.connect(self.reject)
            lay.addWidget(buttons)
            return

        form = QFormLayout()
        params = element.get("params") or {}
        schema = schemas.defaults_for(kind) or {}
        for key, default in schema.items():
            if key in self.DRAGGED and key not in params:
                continue
            value = params.get(key, default)
            if isinstance(value, bool):
                box = QCheckBox()
                box.setChecked(bool(value))
                form.addRow(tr(key), box)
                self.fields[key] = ("bool", box)
            elif isinstance(value, (int, float)) and not isinstance(value, bool):
                spin = QDoubleSpinBox()
                spin.setRange(-1_000_000.0, 1_000_000.0)
                spin.setDecimals(1)
                spin.setValue(float(value))
                spin.setSuffix(" mm")
                form.addRow(tr(key), spin)
                self.fields[key] = ("number", spin)
            elif isinstance(value, str):
                edit = QLineEdit(str(value))
                form.addRow(tr(key), edit)
                self.fields[key] = ("text", edit)
        name = QLineEdit(str(params.get("name") or ""))
        form.addRow(tr("Tên"), name)
        self.fields["name"] = ("text", name)
        lay.addLayout(form)

        buttons = QDialogButtonBox(QDialogButtonBox.Ok
                                   | QDialogButtonBox.Cancel)
        buttons.accepted.connect(self._accept)
        buttons.rejected.connect(self.reject)
        lay.addWidget(buttons)

    def _accept(self) -> None:
        """Write the fields back as ONE command, then close."""
        from core.building import commands as bim_commands
        from core.building.scene_sync import sync

        params: dict = {}
        for key, (kind, widget) in self.fields.items():
            if kind == "bool":
                params[key] = bool(widget.isChecked())
            elif kind == "number":
                params[key] = float(widget.value())
            else:
                text = widget.text()
                params[key] = text
        command = bim_commands.set_params(self._element_id, params)
        command._rebuild = lambda s, b: sync(s, b)
        history = getattr(self._plan._window.viewport, "history", None)
        if history is not None:
            history.execute(command)
            if history.last_error:
                self._plan._say(str(history.last_error))
        self.accept()


def _distance_to_element(element, x: float, y: float):
    """How far a model point is from an element's own plan extent, in mm.

    ``None`` for an element with no extent to measure (a zone, whose area
    is its outline rather than a place on the plan).
    """
    params = element.get("params") or {}
    kind = str(element.get("type"))
    if kind == "zone":
        outline = params.get("outline_mm") or []
        if len(outline) < 3:
            return None
        return 0.0 if _point_in(outline, x, y) else None
    if kind in ("door", "window", "curtain_wall", "fixture"):
        centre = params.get("center_mm")
        if centre and len(centre) >= 2:
            return math.hypot(float(centre[0]) - x, float(centre[1]) - y)
        return None
    start = params.get("baseline_start_mm")
    end = params.get("baseline_end_mm")
    if start and end:
        return _distance_to_segment((float(start[0]), float(start[1])),
                                    (float(end[0]), float(end[1])), x, y)
    outline = params.get("outline_mm") or []
    if len(outline) >= 3:
        return 0.0 if _point_in(outline, x, y) else None
    centre = params.get("center_mm")
    if centre and len(centre) >= 2:
        return math.hypot(float(centre[0]) - x, float(centre[1]) - y)
    return None


def _distance_to_segment(a, b, x: float, y: float) -> float:
    dx, dy = b[0] - a[0], b[1] - a[1]
    length2 = dx * dx + dy * dy
    if length2 < 1e-9:
        return math.hypot(a[0] - x, a[1] - y)
    t = max(0.0, min(1.0, ((x - a[0]) * dx + (y - a[1]) * dy) / length2))
    return math.hypot(a[0] + t * dx - x, a[1] + t * dy - y)


def _point_in(ring, x: float, y: float) -> bool:
    inside = False
    n = len(ring)
    for i in range(n):
        x0, y0 = float(ring[i][0]), float(ring[i][1])
        x1, y1 = float(ring[(i + 1) % n][0]), float(ring[(i + 1) % n][1])
        if (y0 > y) != (y1 > y):
            at = x0 + (y - y0) * (x1 - x0) / ((y1 - y0) or 1e-12)
            if x < at:
                inside = not inside
    return inside


def open_plan_window(window) -> PlanWindow:
    """The one plan window of ``window`` (made on first use, then reused).

    One window per document is what the workspace promises: pressing the
    command again brings the same plan forward instead of stacking a
    second copy of the same drawing on screen.
    """
    existing = getattr(window, "_plan_window", None)
    if existing is not None:
        existing.refresh()
        existing.show()
        existing.raise_()
        return existing
    plan = PlanWindow(window)
    try:
        window._plan_window = plan
    except Exception:                               # pragma: no cover
        pass
    return plan
