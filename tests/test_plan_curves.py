# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Marco Sumari Tellez and IngeTrazo contributors.
"""The plan's own line tools: LINE, PLINE, ARC and CIRCLE as DATA.

A plan is not only what the model already says. The office draws the
ridge of a roof nobody modelled, a setback, an arc for a curved
balustrade. Those entities live in ``scene.plan_curves`` beside the
dimensions, save with the document, and print on the sheet of the storey
they were drawn on — nothing here is ink on a screen.

The shapes follow the CAD commands an architect already knows: a 2-point
arc is the half circle on a diameter, a 3-point arc the circumcircle
through three points, and a degenerate shape writes NOTHING (a
zero-length line or a collinear arc is an entity no viewer can read).
"""
from __future__ import annotations

import math
import pathlib
import sys
import tempfile

import pytest  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

if QApplication.instance() is None:
    QApplication(sys.argv[:1])


@pytest.fixture()
def window():
    from views.main_window import MainWindow

    win = MainWindow()
    yield win
    win.hide()


@pytest.fixture()
def plan(window):
    from core.building import samples as _samples

    _samples.build_sample(window.viewport.history, window.viewport.scene,
                          "townhouse")
    window._on_open_plan_window()
    live = window._plan_window
    live.refresh()
    return live


def _draw(plan, tool: str, *points):
    """Arm a tool and click through it, as the user does."""
    assert plan.arm_draft(tool), tool
    for x, y in points:
        plan.draft_click(float(x), float(y))
    return plan


# ---- the shapes ---------------------------------------------------------------

def test_a_line_is_two_clicks_and_continues_as_a_chain(plan):
    """Corners are drawn by clicking through them: a second click after
    the first segment continues the run rather than starting over."""
    scene = plan._scene
    _draw(plan, "line", (0, 0), (5000, 0))
    assert [c.kind for c in scene.plan_curves] == ["line"]
    assert plan._draft is not None, "công cụ vẽ đường phải còn để nối tiếp"
    plan.draft_click(5000.0, 3000.0)                 # the corner continues
    assert len(scene.plan_curves) == 2
    plan.cancel_draft()
    assert [c.points for c in scene.plan_curves] == [
        [(0.0, 0.0), (5000.0, 0.0)], [(5000.0, 0.0), (5000.0, 3000.0)]]


def test_a_polyline_finishes_on_enter(plan):
    scene = plan._scene
    _draw(plan, "polyline", (0, 0), (2000, 0), (2000, 2000))
    assert scene.plan_curves == [], "đa tuyến chưa kết thúc thì chưa ghi"
    plan.finish_draft()
    assert len(scene.plan_curves) == 1
    assert scene.plan_curves[0].kind == "polyline"
    assert len(scene.plan_curves[0].points) == 3


def test_a_circle_is_a_centre_and_a_radius(plan):
    scene = plan._scene
    _draw(plan, "circle", (1000, 1000), (1000, 2500))
    curve = scene.plan_curves[0]
    assert curve.kind == "circle"
    centre, radius = curve.centre_radius()
    assert centre == (1000.0, 1000.0)
    assert radius == pytest.approx(1500.0)


def test_a_two_point_arc_is_the_half_circle_on_its_diameter(plan):
    scene = plan._scene
    _draw(plan, "arc2", (0, 0), (3000, 0))
    curve = scene.plan_curves[0]
    centre, radius = curve.centre_radius()
    assert centre == (1500.0, 0.0)
    assert radius == pytest.approx(1500.0)
    # The half circle, not the whole one: every point is on the +y side.
    assert all(y >= -1e-6 for _x, y in [(seg[1], seg[3])
                                        for seg in curve.segments()])


def test_a_three_point_arc_passes_through_all_three(plan):
    scene = plan._scene
    _draw(plan, "arc3", (0, 0), (1000, 1000), (2000, 0))
    curve = scene.plan_curves[0]
    assert curve.kind == "arc"
    centre, radius = curve.centre_radius()
    assert centre[0] == pytest.approx(1000.0)
    assert radius == pytest.approx(math.hypot(1000.0, centre[1]))
    # Every one of the three clicked points is on the circle.
    for x, y in ((0.0, 0.0), (1000.0, 1000.0), (2000.0, 0.0)):
        assert math.hypot(x - centre[0], y - centre[1]) == \
            pytest.approx(radius)
    # …and the drawing follows the arc THROUGH the middle point.
    ys = [seg[3] for seg in curve.segments()]
    assert max(ys) == pytest.approx(1000.0, abs=1.0)


# ---- degenerate shapes write nothing ------------------------------------------

def test_a_zero_length_line_writes_nothing_and_says_why(plan):
    scene = plan._scene
    before = len(scene.plan_curves)
    state = _draw(plan, "line", (3000, 3000), (3000, 3000))
    assert len(scene.plan_curves) == before, "đoạn dài 0 đã được ghi"
    assert "0" in state.status.text() or "hợp lệ" in state.status.text()


def test_three_collinear_points_write_no_arc(plan):
    scene = plan._scene
    before = len(scene.plan_curves)
    state = _draw(plan, "arc3", (0, 0), (1000, 0), (2000, 0))
    assert len(scene.plan_curves) == before, "cung thẳng hàng đã được ghi"
    assert state.status.text(), "phải nói vì sao không vẽ"


def test_a_zero_radius_circle_writes_nothing(plan):
    scene = plan._scene
    before = len(scene.plan_curves)
    _draw(plan, "circle", (500, 500), (500, 500))
    assert len(scene.plan_curves) == before


# ---- undo, and the document ---------------------------------------------------

def test_one_undo_removes_the_drawn_shape_and_redo_brings_it_back(plan, window):
    scene = plan._scene
    history = window.viewport.history
    _draw(plan, "circle", (1000, 1000), (1000, 2000))
    assert len(scene.plan_curves) == 1

    history.undo()
    assert scene.plan_curves == [], "Ctrl+Z chưa xoá hình vừa vẽ"
    history.redo()
    assert len(scene.plan_curves) == 1
    assert scene.plan_curves[0].kind == "circle"


def test_each_segment_of_a_chain_is_its_own_undo_step(plan, window):
    """The office undoes a bad corner, not the whole run."""
    scene = plan._scene
    history = window.viewport.history
    _draw(plan, "line", (0, 0), (2000, 0), (2000, 2000))
    plan.cancel_draft()
    assert len(scene.plan_curves) == 2
    history.undo()
    assert len(scene.plan_curves) == 1, "một Ctrl+Z phải chỉ bỏ một đoạn"
    assert scene.plan_curves[0].points == [(0.0, 0.0), (2000.0, 0.0)]


def test_a_drawn_entity_is_saved_and_loaded_exactly(plan, window):
    from formats import igz
    from core.scene import Scene

    scene = plan._scene
    _draw(plan, "circle", (1200, 1300), (1200, 2500))
    _draw(plan, "arc2", (-500, -250), (3500, -250))
    _draw(plan, "line", (0, 0), (4000, 0))
    drawn = [c.to_dict() for c in scene.plan_curves]
    assert len(drawn) == 3

    path = pathlib.Path(tempfile.mkdtemp()) / "curves.igz"
    igz.save_scene(scene, path)
    reopened = Scene()
    igz.load_into(reopened, path)
    assert [c.to_dict() for c in reopened.plan_curves] == drawn, \
        "vòng lưu/mở đã đổi hình đã vẽ"


def test_curves_carry_the_storey_they_were_drawn_on(plan):
    """A line drawn on the ground floor is not on the roof's plan."""
    from core.building.model import building_of
    from core.plan_draw import curves_at

    scene = plan._scene
    _draw(plan, "line", (0, 0), (3000, 0))
    building = building_of(scene)
    drawn = scene.plan_curves[0]
    assert drawn.story_id == str(building.stories[0]["id"])
    assert curves_at(scene, drawn.z), "hình không tìm thấy ở cao độ của nó"
    assert not curves_at(scene, drawn.z + 3.3), "hình lại hiện ở tầng khác"


def test_the_plan_window_draws_what_the_office_drew(plan):
    _draw(plan, "line", (0, 0), (6000, 0))
    plan.refresh()
    drawn_segs = [s for s in plan.canvas._segs
                  if len(s) > 4 and int(s[4]) == 1]
    assert drawn_segs, "cửa sổ Plan không vẽ hình vừa tạo"


def test_the_plan_bar_s_own_buttons_arm_these_tools(plan):
    """The bar's keys are not the command id in every case — «arc» was the
    3D toolbar's id and on a plan means the drawing's own 2-point arc, and
    «freehand» has always drawn a RUN of segments. A button that shows
    enabled and arms nothing is the lie the disabled ones exist to avoid."""
    for key, expected in (("line", "LineTool"), ("arc", "Arc2Tool"),
                          ("arc3", "Arc3Tool"), ("circle", "CircleTool"),
                          ("freehand", "LineTool"),
                          ("polyline", "PolylineTool")):
        cmd = plan._cmd_for_tool(key)
        assert cmd, f"«{key}» không ánh xạ tới lệnh vẽ nào"
        assert plan.arm_draft(cmd), f"«{key}» không bật được công cụ"
        assert type(plan._draft).__name__ == expected,             f"«{key}» bật {type(plan._draft).__name__}, không phải {expected}"
        plan.cancel_draft()


def test_the_dxf_export_carries_the_drawn_entities(plan):
    import ezdxf

    from core.building.model import building_of
    from formats.dxf_bim import save_plan_dxf

    scene = plan._scene
    _draw(plan, "line", (0, 0), (5000, 0))
    _draw(plan, "circle", (2000, 2000), (2000, 3200))
    building = building_of(scene)
    out = pathlib.Path(tempfile.mkdtemp()) / "plan.dxf"
    save_plan_dxf(str(out), scene, building, str(building.stories[0]["id"]))

    doc = ezdxf.readfile(str(out))
    net = [e for e in doc.modelspace() if e.dxf.layer == "KT-NET"]
    assert net, "DXF không mang hình đã vẽ"
    # The circle arrives faceted; the 5 m line is one segment among them.
    assert len(net) > 20
