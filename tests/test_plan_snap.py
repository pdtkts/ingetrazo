# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Marco Sumari Tellez and IngeTrazo contributors.
"""Object snap and ortho: the drawing's own gravity."""
from __future__ import annotations

import os
import sys

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest  # noqa: E402
from PySide6.QtCore import Qt  # noqa: E402
from PySide6.QtGui import QKeyEvent  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

if QApplication.instance() is None:
    QApplication(sys.argv[:1])


def _house():
    from core.building import samples as S
    from core.building.model import building_of
    from views.main_window import MainWindow

    win = MainWindow()
    S.build_sample(win.viewport.history, win.viewport.scene, "townhouse")
    return win, building_of(win.viewport.scene)


def test_a_point_near_a_corner_goes_to_the_corner():
    """The whole point of a snap: 2 mm from a corner IS the corner, so a
    dimension between two corners reads the model's own number."""
    from views import plan_snap as PS

    win, building = _house()
    story_id = str(building.stories[0]["id"])
    pool = PS.candidates(building, story_id)
    assert PS.resolve(building, story_id, 2.0, 3.0, radius_mm=200.0,
                      candidates_list=pool).kind == "end"
    found = PS.resolve(building, story_id, 6002.0, 1.0, radius_mm=200.0,
                       candidates_list=pool)
    assert (found.x_mm, found.y_mm) == (6000.0, 0.0), found
    # far from everything: the raw point stands
    far = PS.resolve(building, story_id, 3000.0, 2000.0, radius_mm=50.0,
                     candidates_list=pool)
    assert far.kind == "none"
    win.hide()


def test_a_vertex_beats_a_line_when_both_are_in_reach():
    """The rank is the trade's own: you mean the corner when you point at
    the corner, even if the wall's face runs right through it."""
    from views import plan_snap as PS

    win, building = _house()
    story_id = str(building.stories[0]["id"])
    pool = PS.candidates(building, story_id)
    kinds = {row[4] if len(row) == 6 else row[2] for row in pool}
    assert {"end", "mid", "face"} <= kinds, kinds
    # a point 1 mm from a corner and 1 mm from that wall's face
    snap = PS.resolve(building, story_id, 1.0, 1.0, radius_mm=300.0,
                      candidates_list=pool)
    assert snap.kind == "end", snap


def test_the_wall_s_face_is_a_snap_target_of_its_own():
    """The face is the line the trowel follows and the line a dimension
    measures to, so it has to be grabbable apart from the baseline."""
    from views import plan_snap as PS

    win, building = _house()
    story_id = str(building.stories[0]["id"])
    pool = PS.candidates(building, story_id)
    faces = [row for row in pool if len(row) == 6 and row[4] == "face"]
    assert faces, "không có mặt tường nào"
    # the first wall is 200 thick along y=0, so a face runs at y=±100 —
    # and it answers ALONG ITS WHOLE LENGTH, not only at the two ends
    snap = PS.resolve(building, story_id, 3000.0, 103.0, radius_mm=60.0,
                      candidates_list=pool)
    assert snap.kind in ("face", "mid"), snap
    assert snap.y_mm == pytest.approx(100.0), snap
    assert snap.x_mm == pytest.approx(3000.0, abs=60.0), snap
    win.hide()


def test_the_grid_axes_snap_too():
    from views import plan_snap as PS
    from views.grid_dialog import GridDialog

    win, building = _house()
    story_id = str(building.stories[0]["id"])
    dialog = GridDialog(win, story_id)
    dialog._fill_from_walls()
    dialog._save()
    from core.building.model import building_of

    rebuilt = building_of(win.viewport.scene)
    pool = PS.candidates(rebuilt, story_id)
    grid_points = [(row[0], row[1], row[3]) if len(row) == 4
                   else (row[0], row[1], row[5])
                   for row in pool
                   if (row[4] if len(row) == 6 else row[2]) == "grid"]
    assert grid_points, "trục không có điểm bám nào"
    assert {l for _x, _y, l in grid_points} == {"1", "2", "A", "B"}
    win.hide()


def test_ortho_holds_the_polar_steps_including_45_and_60():
    from views import plan_snap as PS

    step15 = PS.apply_ortho((0.0, 0.0), 1000.0, 40.0, 15.0)
    assert (round(step15.x_mm), round(step15.y_mm)) == (1001, 0)
    run45 = PS.apply_ortho((0.0, 0.0), 1000.0, 990.0, 15.0)
    assert run45.label == "45°", run45
    brace60 = PS.apply_ortho((0.0, 0.0), 1000.0, 1732.0, 15.0)
    assert brace60.label == "60°", brace60
    square = PS.apply_ortho((0.0, 0.0), 30.0, 1000.0, 90.0)
    assert square.label == "90°", square


def test_object_snap_wins_over_ortho():
    """A drafter who points at a corner means the corner; pulling that
    point onto a ray would move it off what they aimed at."""
    from views import plan_snap as PS

    win, building = _house()
    story_id = str(building.stories[0]["id"])
    pool = PS.candidates(building, story_id)
    snap = PS.resolve(building, story_id, 6001.0, 1.0, radius_mm=200.0,
                      from_point=(0.0, 0.0), ortho=True,
                      candidates_list=pool)
    assert snap.kind == "end"
    assert (snap.x_mm, snap.y_mm) == (6000.0, 0.0), snap
    win.hide()


def test_a_dimension_drawn_by_eye_measures_the_model():
    """End to end: two clicks a few millimetres off the corners produce
    the model's own 6000, not 5993."""
    win, _building = _house()
    win._on_open_plan_window()
    plan = win._plan_window
    plan.arm_draft("dim")
    plan.draft_click(4.0, 6.0)
    plan.draft_click(5995.0, 2.0)
    dimension = win.viewport.scene.dimensions[-1]
    measured = abs((dimension.b - dimension.a).length()) * 1000.0
    assert measured == pytest.approx(6000.0, abs=0.5), measured
    plan.hide()
    win.hide()


def test_the_locks_are_on_the_keys_every_cad_uses_and_can_be_switched_off():
    win, _building = _house()
    win._on_open_plan_window()
    plan = win._plan_window
    assert plan.snap_on and not plan.ortho_on
    plan.keyPressEvent(QKeyEvent(QKeyEvent.KeyPress, Qt.Key_F8,
                                 Qt.NoModifier))
    assert plan.ortho_on and plan.ortho_box.isChecked()
    plan.keyPressEvent(QKeyEvent(QKeyEvent.KeyPress, Qt.Key_F3,
                                 Qt.NoModifier))
    assert not plan.snap_on and not plan.snap_box.isChecked()
    # with snap off, a raw point stays raw
    from views import plan_snap as PS

    plan._snap_pool_key = None
    assert plan.snap_pool() == []
    assert PS.resolve(None, "", 1.0, 1.0, radius_mm=100.0,
                      candidates_list=[]).kind == "none"
    plan.hide()
    win.hide()


def test_the_snap_table_is_rebuilt_when_the_model_changes():
    """A snap pool built once and kept would pull points to walls that have
    been deleted or moved since."""
    from core.building import commands as C
    from core.building.model import building_of

    win, _building = _house()
    win._on_open_plan_window()
    plan = win._plan_window
    before = len(plan.snap_pool())
    # the storey the plan is SHOWING (the pool is per storey, as it must be)
    story_id = plan._story_id
    win.viewport.history.execute(C.add_element("wall", story_id, {
        "baseline_start_mm": [0.0, 9000.0],
        "baseline_end_mm": [8000.0, 9000.0],
        "thickness_mm": 200.0, "height_mm": 3300.0}))
    plan._building = building_of(win.viewport.scene)
    after = len(plan.snap_pool())
    assert after > before, f"bảng bám không dựng lại: {before} → {after}"
    # and the new wall's own corner is grabbable
    from views import plan_snap as PS

    snap = PS.resolve(plan._building, story_id, 8002.0, 8998.0,
                      radius_mm=200.0, candidates_list=plan.snap_pool())
    assert (snap.x_mm, snap.y_mm) == (8000.0, 9000.0), snap
    plan.hide()
    win.hide()
