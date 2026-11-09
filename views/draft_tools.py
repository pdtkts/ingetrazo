# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Marco Sumari Tellez and IngeTrazo contributors.
"""Draft tools — the plan's own 2D drawing, as DATA.

The plan window is a view of the model, but a drawing is more than its
model: the office adds dimensions it needs and no one else measured, a
level mark where the section changes, a note, a leader to a detail, and
the grid the whole trade lays out from. Those are not three-dimensional
geometry (a dimension is not a box), so they live where the drawing's
other data lives: ``scene.dimensions``, ``scene.text_labels`` and the
drawing's own annotation registry.

Nothing here is a second drawing engine. Each tool is a small state
machine that collects the points it needs through the plan's own
transform, then writes one undoable command through the SAME History the
3D uses — so a dimension drawn on the plan is real, saved, and printed,
not ink on a screen.
"""
from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtGui import QColor, QPen

from core.i18n import tr

#: The storey's annotation layer, as the issued sheets use it — one name,
#: so a plan drawn here and a plan issued from the composer share it.
ANNOT_LAYER = "BIM-GHI-CHU"

#: Grid: the pitch the office starts from, and how far the bubbles reach.
DEFAULT_GRID_PITCH_MM = 6000.0
GRID_BUBBLE_MM = 700.0


class DraftTool:
    """One 2D tool: gathers points on the plan, then writes ONE command."""

    #: What the status line says while the tool is armed.
    hint = ""
    #: How many points the tool needs (a level mark needs one).
    points_needed = 2

    def __init__(self, plan) -> None:
        self.plan = plan
        self.points: list = []

    # ---- the interaction -------------------------------------------------
    def click(self, x_mm: float, y_mm: float, *, snapping=None) -> bool:
        """Take a click. Returns True when the tool is finished."""
        if snapping is not None:
            snapped = snapping(x_mm, y_mm)
            if snapped is not None:
                x_mm, y_mm = snapped
        self.points.append((float(x_mm), float(y_mm)))
        if len(self.points) >= int(self.points_needed):
            self.commit()
            return True
        return False

    def preview(self, x_mm: float, y_mm: float) -> list:
        """Segments to draw between the points so far and the cursor."""
        if not self.points or self.points_needed < 2:
            return []
        last = self.points[-1]
        return [(last[0], last[1], float(x_mm), float(y_mm))]

    def commit(self) -> None:                       # pragma: no cover
        raise NotImplementedError

    def cancel(self) -> None:
        self.points = []


def _z_cut(plan) -> float:
    """The height the plan's own cut rides at, in model metres.

    A dimension on a plan has to sit ON the plan — at the storey's cut —
    or it is drawn at the wrong floor and the issued sheet shows it in
    the wrong place (or not at all).
    """
    from core.building import drawings as _drawings

    story = plan._building.story(plan._story_id) if plan._building else None
    z_mm = float((story or {}).get("z_mm", 0.0))
    cut = _drawings.DEFAULT_CUT_MM
    row = getattr(plan, "_view_row", None) or {}
    if row.get("cut_mm") is not None:
        cut = float(row["cut_mm"])
    return (z_mm + cut) / 1000.0


class DimensionTool(DraftTool):
    """Two clicks: a dimension measured between them, standing where the
    office drew it."""

    hint = "Kích thước: bấm điểm đầu, rồi điểm cuối"
    points_needed = 2

    def commit(self) -> None:
        from PySide6.QtGui import QVector3D

        from core.dimension import Dimension
        from core.history import AddDimensionCommand

        (x1, y1), (x2, y2) = self.points
        if abs(x2 - x1) < 1e-6 and abs(y2 - y1) < 1e-6:
            self.points = []
            return
        z = _z_cut(self.plan)
        offset = _offset_for(self.points)
        dim = Dimension(QVector3D(x1 / 1000.0, y1 / 1000.0, z),
                        QVector3D(x2 / 1000.0, y2 / 1000.0, z),
                        QVector3D(offset[0], offset[1], 0.0),
                        layer=ANNOT_LAYER)
        self.plan._write(AddDimensionCommand(dim))
        self.points = []


class LevelTool(DraftTool):
    """One click: a level mark (its own height, in the Vietnamese form)."""

    hint = "Cốt cao độ: bấm chỗ đặt ký hiệu"
    points_needed = 1

    #: The heights the office marks most; the dialog asks for the rest.
    PRESETS = (0.0, 600.0, 1200.0, 2200.0, 3300.0)

    def click(self, x_mm: float, y_mm: float, *, snapping=None) -> bool:
        # A level is asked for its height BEFORE it is placed: the height
        # is what the mark says, and the point is only where it stands.
        from PySide6.QtWidgets import QInputDialog

        story = self.plan._building.story(self.plan._story_id) \
            if self.plan._building else None
        base = float((story or {}).get("z_mm", 0.0))
        values = [f"{v:+.0f}" for v in self.PRESETS]
        value, ok = QInputDialog.getItem(
            self.plan, tr("Cốt cao độ"), tr("Cao độ (mm so với ±0.000):"),
            values, 0, True)
        if not ok:
            self.points = []
            return True
        try:
            height_mm = float(str(value).replace("+", ""))
        except ValueError:
            height_mm = 0.0
        self.points = [(float(x_mm), float(y_mm), height_mm)]
        self.commit()
        return True

    def commit(self) -> None:
        from PySide6.QtGui import QVector3D

        from core.building.drawings import level_box_text
        from core.history import AddTextLabelCommand
        from core.textlabel import TextLabel

        (x_mm, y_mm, height_mm) = self.points[0]
        story = self.plan._building.story(self.plan._story_id) \
            if self.plan._building else None
        base = float((story or {}).get("z_mm", 0.0))
        text = level_box_text("FL" if height_mm < 1.0 else "CL",
                              base + float(height_mm))
        label = TextLabel(
            QVector3D(x_mm / 1000.0, y_mm / 1000.0, _z_cut(self.plan)),
            QVector3D(0.0, 0.0, 0.0), text, layer=ANNOT_LAYER)
        self.plan._write(AddTextLabelCommand(label))
        self.points = []


class TextTool(DraftTool):
    """One click, then a line of text on the drawing."""

    hint = "Chữ: bấm chỗ đặt, rồi gõ nội dung"
    points_needed = 1

    def commit(self) -> None:
        from PySide6.QtGui import QVector3D
        from PySide6.QtWidgets import QInputDialog

        from core.history import AddTextLabelCommand
        from core.textlabel import TextLabel

        (x_mm, y_mm) = self.points[0]
        text, ok = QInputDialog.getText(
            self.plan, tr("Chữ"), tr("Nội dung:"))
        if ok and str(text).strip():
            label = TextLabel(
                QVector3D(x_mm / 1000.0, y_mm / 1000.0, _z_cut(self.plan)),
                QVector3D(0.0, 0.0, 0.0), str(text).strip(),
                layer=ANNOT_LAYER)
            self.plan._write(AddTextLabelCommand(label))
        self.points = []


class LabelTool(DraftTool):
    """Two clicks: a leader from the note to the thing it points at."""

    hint = "Chú thích: bấm điểm cần chú, rồi chỗ đặt chữ"
    points_needed = 2

    def commit(self) -> None:
        from PySide6.QtGui import QVector3D
        from PySide6.QtWidgets import QInputDialog

        from core.history import AddTextLabelCommand
        from core.textlabel import TextLabel

        (x1, y1), (x2, y2) = self.points
        text, ok = QInputDialog.getText(
            self.plan, tr("Chú thích"), tr("Nội dung:"))
        if not ok or not str(text).strip():
            self.points = []
            return
        # The label's ANCHOR is what it points at and its OFFSET where the
        # text floats: that is what keeps a leader attached to its detail
        # after the model moves.
        label = TextLabel(QVector3D(x1 / 1000.0, y1 / 1000.0,
                                    _z_cut(self.plan)),
                          QVector3D((x2 - x1) / 1000.0, (y2 - y1) / 1000.0,
                                    0.0),
                          str(text).strip(), layer=ANNOT_LAYER)
        self.plan._write(AddTextLabelCommand(label))
        self.points = []


class GridTool(DraftTool):
    """Two clicks: a row of gridlines across the storey.

    The office lays the building out from its grid, so the grid is drawn
    as the drawing's own annotations: a line per axis, a bubble letter at
    each end, and the axis' own dimension chain. All of it is data, so it
    survives the file and appears on the issued sheet.
    """

    hint = "Trục: bấm điểm đầu, rồi điểm cuối của hàng trục"
    points_needed = 2

    def commit(self) -> None:
        from PySide6.QtGui import QVector3D

        from core.dimension import Dimension
        from core.history import (AddDimensionCommand, AddTextLabelCommand,
                                  CompoundCommand)
        from core.textlabel import TextLabel

        (x1, y1), (x2, y2) = self.points
        length = ((x2 - x1) ** 2 + (y2 - y1) ** 2) ** 0.5
        if length < 1e-6:
            self.points = []
            return
        parallel = getattr(self, "also_marks", None)
        lines = _grid_lines((x1, y1), (x2, y2), int(parallel or 1))
        z = _z_cut(self.plan)
        commands = []
        for index, (run, letter) in enumerate(lines, start=1):
            a, b = run[0], run[1]
            axis = Dimension(QVector3D(a[0] / 1000.0, a[1] / 1000.0, z),
                             QVector3D(b[0] / 1000.0, b[1] / 1000.0, z),
                             QVector3D(0.0, 0.0, 0.0), text="",
                             layer=ANNOT_LAYER)
            commands.append(AddDimensionCommand(axis))
            for end in (a, b):
                label = TextLabel(
                    QVector3D(end[0] / 1000.0, end[1] / 1000.0, z),
                    QVector3D(0.0, 0.0, 0.0), letter, layer=ANNOT_LAYER)
                commands.append(AddTextLabelCommand(label))
            del index
        if commands:
            # ONE undo step for the whole grid: the office drew it as one
            # gesture, and taking it back should take all of it.
            self.plan._write(CompoundCommand(commands))
        self.points = []


class CropTool(DraftTool):
    """Two clicks: a rectangle on the source, issued as a drawing.

    The reference's rule, kept: a detail does NOT copy geometry — it is
    the source drawing's own rule cropped to four trim planes, so it
    keeps agreeing with the model afterwards. What this tool produces is
    therefore a ROW the docset can issue, filed on the storey, not a
    frozen picture of today's walls.
    """

    hint = "Vùng hiển thị: bấm góc thứ nhất, rồi góc đối diện"
    points_needed = 2

    def preview(self, x_mm: float, y_mm: float) -> list:
        if not self.points:
            return []
        x0, y0 = self.points[0]
        # A rectangle, not the diagonal: the corner the user is dragging
        # is what they are aiming at.
        return [(x0, y0, float(x_mm), y0), (float(x_mm), y0,
                                            float(x_mm), float(y_mm)),
                (float(x_mm), float(y_mm), x0, float(y_mm)),
                (x0, float(y_mm), x0, y0)]

    def commit(self) -> None:
        from core.building import commands as bim_commands
        from core.building import drawings as _drawings
        from core.building.model import building_of

        (x0, y0), (x1, y1) = self.points
        u0, u1 = sorted((float(x0), float(x1)))
        v0, v1 = sorted((float(y0), float(y1)))
        if (u1 - u0) < 50.0 or (v1 - v0) < 50.0:
            self.points = []
            return
        scene = self.plan._scene
        building = building_of(scene)
        # The crop is a view OF a storey, so there has to be one: without
        # this guard `view_for` raises out of the click handler — which the
        # History never sees — and the user gets a Qt traceback instead of
        # a sentence. Every other draft tool survives an empty model.
        if not building.stories or not self.plan._story_id:
            self.points = []
            self.plan._say(tr("Chưa có tầng nào — dựng tầng trước đã."))
            return
        row = {"kind": "detail", "story_id": self.plan._story_id,
               "name": tr("Vùng hiển thị"),
               "rect_mm": [u0, v0, u1, v1]}
        # Adding the drawing to the building's own set is what makes it
        # ISSUABLE: the docset reads rows, so a crop nobody can issue
        # would be a rectangle drawn on a screen.
        def mutate(b) -> None:
            settings = b.settings.setdefault("drawings", [])
            settings.append(row)

        source_row = {"kind": "story", "story_id": self.plan._story_id}
        view = _drawings.view_for(building, source_row)
        detail = _drawings.detail_view(building, row, view)
        command = bim_commands.BuildingEdit(mutate)
        command._rebuild = None
        self.plan._write(command)
        made = {
            "name": str(row["name"]),
            "rect_mm": [u0, v0, u1, v1],
            "scale_denom": float(detail.scale_denom),
            "clips": len(detail.clip_planes),
        }
        self.plan._say(tr("Đã tạo vùng hiển thị %s: %.0f×%.0f mm, %d mặt cắt.")
                       % (made["name"], u1 - u0, v1 - v0, made["clips"]))
        self.points = []


#: The plan command ids these tools implement, in the registry's spelling.
DRAFT_TOOLS = {
    "dim": DimensionTool,
    "dimension": DimensionTool,
    "level": LevelTool,
    "text": TextTool,
    "label": LabelTool,
    "grid": GridTool,
    "crop": CropTool,
}


def tool_for(cmd_id: str, plan):
    """The draft tool a plan command id maps to, or ``None``."""
    factory = DRAFT_TOOLS.get(str(cmd_id))
    return factory(plan) if factory is not None else None


def _grid_lines(a, b, axes: int = 1) -> list:
    """``[( (p1, p2), letter ), …]`` for a row of gridlines.

    The row runs along ``a→b``; each axis is one line, the first through
    ``a``, the last through ``b``, evenly spaced between. The letter is
    the axis' own — A, B, C… as the trade names them, never a number, so
    a grid read off the plan sounds like the one called out on site.
    """
    x1, y1 = float(a[0]), float(a[1])
    x2, y2 = float(b[0]), float(b[1])
    dx, dy = x2 - x1, y2 - y1
    length = (dx * dx + dy * dy) ** 0.5 or 1.0
    # The axes stand PERPENDICULAR to the row the user drew: the row is
    # the direction the grid runs, and an axis crosses it.
    nx, ny = -dy / length, dx / length
    out: list = []
    count = max(1, int(axes))
    for i in range(count):
        t = 0.0 if count == 1 else i / (count - 1)
        cx, cy = x1 + dx * t, y1 + dy * t
        out.append((((cx - nx * GRID_BUBBLE_MM, cy - ny * GRID_BUBBLE_MM),
                     (cx + nx * GRID_BUBBLE_MM, cy + ny * GRID_BUBBLE_MM)),
                    _axis_letter(i)))
    return out


def _axis_letter(index: int) -> str:
    """A, B, … Z, then AA: the trade's own naming for an axis."""
    name = ""
    n = int(index)
    while True:
        name = chr(ord("A") + n % 26) + name
        n = n // 26 - 1
        if n < 0:
            return name


def _offset_for(points) -> tuple:
    """Where a dimension's text stands: to one side of the line, never on
    it — a dimension drawn along its own wall is unreadable."""
    (x1, y1), (x2, y2) = points
    dx, dy = x2 - x1, y2 - y1
    length = (dx * dx + dy * dy) ** 0.5 or 1.0
    return (-dy / length * 300.0, dx / length * 300.0)


def paint_preview(painter, canvas, tool) -> None:
    """The rubber band between the points taken and the cursor."""
    if tool is None or not tool.points:
        return
    painter.setPen(QPen(QColor("#1e6fd9"), 1.0, Qt.DashLine))
    preview = getattr(canvas, "_tool_preview", None)
    for x1, y1, x2, y2 in (preview or ()):
        painter.drawLine(canvas.to_screen(x1, y1), canvas.to_screen(x2, y2))
    for point in tool.points[:2]:
        x, y = float(point[0]), float(point[1])
        painter.drawEllipse(canvas.to_screen(x, y), 3.0, 3.0)
