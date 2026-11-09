# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Marco Sumari Tellez and IngeTrazo contributors.
"""The plan's own drafting: dimension, level, text, label, grid — as data."""
from __future__ import annotations

import os
import sys

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

if QApplication.instance() is None:
    QApplication(sys.argv[:1])

ANNOT = "BIM-GHI-CHU"


@pytest.fixture()
def plan():
    from core.building import samples as S
    from views.main_window import MainWindow

    win = MainWindow()
    S.build_sample(win.viewport.history, win.viewport.scene, "townhouse")
    win._on_open_plan_window()
    yield win._plan_window
    win._plan_window.hide()
    win.hide()


def test_a_dimension_drawn_on_the_plan_is_real_data(plan):
    """Not ink on a screen: a Dimension entity on the annotation layer, at
    the plan's own cut, in the document — so it prints and it saves."""
    from core.dimension import Dimension

    scene = plan._window.viewport.scene
    before = len(scene.dimensions)
    assert plan.arm_draft("dim")
    plan.draft_click(1000.0, 1000.0)
    plan.draft_click(4000.0, 1000.0)
    assert len(scene.dimensions) == before + 1
    made = scene.dimensions[-1]
    assert isinstance(made, Dimension)
    assert made.layer == ANNOT
    # The cut, not the ground: a dimension at z=0 lands under the plan.
    z = made.a.z()
    story = plan._building.story(plan._story_id)
    assert z == pytest.approx(
        (float(story["z_mm"]) + 1200.0) / 1000.0, abs=1e-6)
    assert abs((made.b - made.a).length()) == pytest.approx(3.0, abs=1e-6)


def test_the_tool_cancels_and_leaves_nothing_behind(plan):
    scene = plan._window.viewport.scene
    before = len(scene.dimensions)
    plan.arm_draft("dim")
    plan.draft_click(0.0, 0.0)
    plan.cancel_draft()                 # Esc: the one point is dropped
    assert len(scene.dimensions) == before
    assert plan._draft is None


def test_a_grid_is_one_undo_step(plan):
    """The office drew the grid as one gesture; taking it back must take
    all of it — not one axis at a time."""
    scene = plan._window.viewport.scene
    dims, labels = len(scene.dimensions), len(scene.text_labels)
    plan.arm_draft("grid")
    plan.draft_click(0.0, 0.0)
    plan.draft_click(6000.0, 0.0)
    assert len(scene.dimensions) == dims + 1
    assert len(scene.text_labels) == labels + 2, "mỗi trục phải có 2 bong bóng"
    assert plan._window.viewport.history.undo()
    assert len(scene.dimensions) == dims
    assert len(scene.text_labels) == labels, "hoàn tác phải trả lại cả chữ"


def test_a_label_points_at_what_it_names(plan):
    """The anchor is the thing, the offset is where the text floats — that
    is what keeps a leader on its detail after the model moves."""
    scene = plan._window.viewport.scene
    plan.arm_draft("label")
    plan._draft.commit = lambda: _commit_label(plan, "Chi tiết A")
    plan.draft_click(2000.0, 3000.0)
    plan.draft_click(5000.0, 3000.0)
    made = scene.text_labels[-1]
    assert str(made.text) == "Chi tiết A"
    assert made.layer == ANNOT
    assert made.anchor.x() == pytest.approx(2.0) and \
        made.anchor.y() == pytest.approx(3.0)
    assert made.offset.x() == pytest.approx(3.0)


def _commit_label(plan, text):
    from PySide6.QtGui import QVector3D

    from core.history import AddTextLabelCommand
    from core.textlabel import TextLabel

    (x1, y1), (x2, y2) = plan._draft.points
    label = TextLabel(QVector3D(x1 / 1000.0, y1 / 1000.0, 0.0),
                      QVector3D((x2 - x1) / 1000.0, (y2 - y1) / 1000.0, 0.0),
                      text, layer=ANNOT)
    plan._write(AddTextLabelCommand(label))
    plan._draft.points = []


def test_the_bar_enables_the_plan_s_own_tools_and_not_the_missing_ones(plan):
    """A bar that enables a tool this build cannot run is a lie, and so is
    one that greys out a tool the plan CAN run."""
    buttons = plan.bar_buttons
    for cmd_id in ("dim", "level", "text", "label", "grid"):
        assert buttons[cmd_id].isEnabled(), cmd_id
        assert buttons[cmd_id].toolTip(), cmd_id
    # a command with no implementation anywhere stays disabled and says so
    assert not buttons["trim"].isEnabled()
    assert "chưa có" in buttons["trim"].toolTip()


def test_an_armed_tool_takes_the_click_instead_of_the_picker(plan):
    """While one is armed the plan is a drawing board: a press must not
    also select the wall underneath it."""
    scene = plan._window.viewport.scene
    before = len(scene.dimensions)
    plan.arm_draft("dim")
    plan.draft_click(500.0, 500.0)
    # The click went to the tool (its first point), so nothing was measured
    # yet and no element was picked on the way.
    assert len(scene.dimensions) == before
    assert plan._draft is not None, "còn điểm đầu thì công cụ chưa xong"
    assert plan.canvas._selected is None, "cú bấm vừa rồi còn chọn cả cấu kiện"


def test_axis_letters_run_the_trade_s_way():
    from views.draft_tools import _axis_letter

    assert [_axis_letter(i) for i in range(4)] == ["A", "B", "C", "D"]
    assert _axis_letter(25) == "Z"
    assert _axis_letter(26) == "AA"


def test_the_grid_stands_across_the_row_and_letters_the_axes():
    from views.draft_tools import _grid_lines

    lines = _grid_lines((0.0, 0.0), (6000.0, 0.0), 1)
    assert len(lines) == 1
    (a, b), letter = lines[0]
    # The row runs along x; an axis crosses it (y), through its start.
    assert a[0] == pytest.approx(-0.0, abs=1e-6)
    assert abs(b[1] - a[1]) > 0.0
    assert letter == "A"
    many = _grid_lines((0.0, 0.0), (6000.0, 0.0), 3)
    assert [row[1] for row in many] == ["A", "B", "C"]
    xs = [row[0][0][0] for row in many]
    assert xs[0] == pytest.approx(0.0) and xs[-1] == pytest.approx(6000.0)


def test_a_dimension_is_never_drawn_on_its_own_line():
    from views.draft_tools import _offset_for

    dx, dy = _offset_for([(0.0, 0.0), (1000.0, 0.0)])
    assert abs(dx) < 1e-9 and abs(dy) > 100.0, "chữ phải đứng bên cạnh nét"
