# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Marco Sumari Tellez and IngeTrazo contributors.
"""Kính lúp — the plan under a lens, at the cursor.

A plan is drawn to a scale, and a scale is a bargain: at 1:100 a 200 mm
wall is two millimetres on paper, which is where two thicknesses, a
dimension's own text and the tick marks around an opening all become a
smudge. The lens is the way a drafter answers that without changing the
scale of the drawing: a small window that shows the SAME plan around the
cursor, magnified, while the sheet itself stays at the scale it is issued
at.

It is deliberately built from the window's own geometry — the same
segments, loops and marks the canvas paints — so the lens can never show
a different drawing from the one under it. No second projection.
"""
from __future__ import annotations

from PySide6.QtCore import QPointF, QRectF, Qt
from PySide6.QtGui import QColor, QFont, QPainter, QPen
from PySide6.QtWidgets import QWidget

from core.i18n import tr

#: How far the lens stands from the cursor, so it never covers the point
#: being examined.
OFFSET_PX = 26


class LensWindow(QWidget):
    """A frameless lens that follows the cursor over the plan."""

    def __init__(self, plan) -> None:
        super().__init__(plan, Qt.ToolTip | Qt.FramelessWindowHint)
        self.setAttribute(Qt.WA_TransparentForMouseEvents, True)
        self._plan = plan
        self._at = (0.0, 0.0)               # model mm, the lens' centre
        self.resize(int(plan.LENS_PX), int(plan.LENS_PX))
        self.setWindowTitle(tr("Kính lúp"))

    # ---- where it looks --------------------------------------------------
    def look_at(self, x_mm: float, y_mm: float, global_pos=None) -> None:
        self._at = (float(x_mm), float(y_mm))
        if global_pos is not None:
            self.move(global_pos.x() + OFFSET_PX, global_pos.y() + OFFSET_PX)
        self.update()

    def paintEvent(self, _event) -> None:           # noqa: N802 — Qt
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing, True)
        painter.fillRect(self.rect(), QColor("#FFFFFF"))
        canvas = getattr(self._plan, "canvas", None)
        if canvas is None:
            return
        # The lens' own transform: the canvas' scale times the factor,
        # centred on the point under the cursor. Using the canvas' own
        # normalized data (segments in model mm) means the lens cannot
        # disagree with the drawing it magnifies.
        factor = float(getattr(self._plan, "LENS_FACTOR", 3.0))
        scale = float(getattr(canvas, "scale_px_per_mm", 1.0)) * factor
        cx, cy = self._at
        def to_screen(x: float, y: float) -> QPointF:
            return QPointF((x - cx) * scale + self.width() / 2.0,
                           (y - cy) * scale + self.height() / 2.0)

        # The plan is clipped to the lens: a wall that runs out of the
        # circle must not be drawn across the whole desktop.
        painter.setClipRect(self.rect())
        painter.setPen(QPen(QColor("#1e6fd9"), 1.2))
        for seg in getattr(canvas, "model_segs", ()) or ():
            painter.drawLine(to_screen(seg[0], seg[1]), to_screen(seg[2], seg[3]))
        painter.setPen(QPen(QColor("#333"), 1.0))
        font = QFont()
        font.setPointSizeF(8.0)
        painter.setFont(font)
        for text, x_mm, y_mm in getattr(canvas, "_marks", ()) or ():
            painter.drawText(to_screen(x_mm, y_mm), str(text))
        # A crosshair on the examined point, and the frame.
        centre = to_screen(cx, cy)
        painter.setPen(QPen(QColor("#d97706"), 1.0))
        painter.drawLine(QPointF(centre.x() - 8.0, centre.y()),
                         QPointF(centre.x() + 8.0, centre.y()))
        painter.drawLine(QPointF(centre.x(), centre.y() - 8.0),
                         QPointF(centre.x(), centre.y() + 8.0))
        painter.setPen(QPen(QColor("#606060"), 1.6))
        painter.setBrush(Qt.NoBrush)
        painter.drawRect(QRectF(0.6, 0.6, self.width() - 1.2,
                                self.height() - 1.2))
        painter.end()
