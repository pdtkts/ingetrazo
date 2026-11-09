# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Marco Sumari Tellez and IngeTrazo contributors.
"""A drawing is a rule, not a picture.

These tests protect the numbers the trade actually reads off a sheet: the
plan cuts at +1200 and is trimmed at its floor, a section looks one way and
is limited in depth, and the dimension chains stand 10 and 18 paper mm off
the outside face — measured in model millimetres, so a 1:50 plan and a 1:25
detail of the same wall agree about where the dimension line is.
"""
from __future__ import annotations

import math

import pytest

from core.building import drawings as D
from core.building.builder import build
from core.building.model import Building
from core.scene import Scene


@pytest.fixture()
def house() -> Building:
    """One 6 × 4 m storey with a door and a room, plus the storey above."""
    b = Building()
    s1 = b.add_story("Tầng 1", 0.0, 3300.0)
    b.add_story("Tầng 2", 3300.0, 3300.0)
    b.add_element("wall", s1["id"], {
        "baseline_start_mm": [0, 0], "baseline_end_mm": [6000, 0],
        "thickness_mm": 200.0, "height_mm": 3300.0, "top_link": "next"})
    b.add_element("door", s1["id"], {
        "host_wall_id": "", "offset_along_wall_mm": 3000.0,
        "width_mm": 900.0, "height_mm": 2200.0})
    zone = b.add_element("zone", s1["id"], {
        "outline_mm": [[0, 0], [6000, 0], [6000, 4000], [0, 4000]],
        "name": "Phòng khách"})
    # What the builder writes back — a room stamp with no area is worse
    # than none, and every document path goes through the builder.
    _mesh, derived = build(b, zone)
    zone["derived"] = derived
    return b


def _story(b):
    return b.stories[0]


def test_a_plan_cuts_at_1200_and_is_trimmed_at_its_floor(house):
    """The cut hides what is above +1200; the trim hides the ground under
    the storey — and the trim must be a CLIP, drawing no chord, or the
    plan would carry a second set of cut lines across its floor."""
    b = house
    row = {"kind": "story", "story_id": _story(b)["id"]}
    view = D.view_for(b, row)
    assert view.is_plan()
    assert len(view.section_planes) == 1
    cut = view.section_planes[0]
    assert cut.clip_only is False
    assert cut.normal.z() == pytest.approx(1.0)
    assert cut.point.z() * 1000.0 == pytest.approx(D.DEFAULT_CUT_MM, abs=1e-3)
    assert len(view.clip_planes) == 1
    trim = view.clip_planes[0]
    assert trim.clip_only is True
    assert trim.normal.z() == pytest.approx(-1.0)
    assert trim.point.z() == pytest.approx(0.0, abs=1e-6)


def test_a_plan_view_looks_straight_down_with_north_up(house):
    b = house
    view = D.view_for(b, {"kind": "story", "story_id": _story(b)["id"]})
    assert view.pitch == pytest.approx(math.pi / 2.0)
    assert view.up == (0.0, 1.0, 0.0)
    cam = view.camera()
    assert cam.perspective is False
    f = cam.forward()
    assert f.z() < -0.99                                   # looking down


def test_a_roof_plan_cuts_low_over_its_storey(house):
    """A roof plan is a plan — cut low (450 mm) so the gable walls read as
    walls do, and trimmed at the roof storey's own floor."""
    b = house
    top = b.stories[1]
    view = D.view_for(b, {"kind": "roof", "story_id": top["id"]})
    assert view.kind == D.KIND_ROOF
    cut = view.section_planes[0]
    assert cut.point.z() * 1000.0 == pytest.approx(3300.0 + D.ROOF_CUT_MM, abs=1e-3)
    assert view.clip_planes[0].point.z() * 1000.0 == pytest.approx(3300.0, abs=1e-3)


def test_a_section_cuts_at_its_line_and_looks_one_way(house):
    b = house
    row = {"kind": "section", "story_id": _story(b)["id"],
           "p1": [0.0, 3000.0], "p2": [6000.0, 3000.0],
           "normal": [0.0, -1.0]}
    view = D.view_for(b, row)
    assert not view.is_plan()
    assert len(view.section_planes) == 1
    assert view.section_planes[0].clip_only is False
    # The cut hides the side the normal points at (the viewer's own side).
    assert view.section_planes[0].normal.y() == pytest.approx(-1.0)
    assert {sp.name for sp in view.clip_planes} == {
        "Độ sâu", "Trước điểm đầu", "Sau điểm cuối"}
    # …and the camera looks the OTHER way, from the side the normal names.
    cam = view.camera()
    f = cam.forward()
    assert f.y() > 0.99                                    # looking +Y


def test_a_section_is_limited_to_its_depth(house):
    b = house
    row = {"kind": "section", "story_id": _story(b)["id"],
           "p1": [0.0, 3000.0], "p2": [6000.0, 3000.0],
           "normal": [0.0, -1.0], "depth_mm": 4000.0}
    view = D.view_for(b, row)
    depth = next(sp for sp in view.clip_planes if sp.name == "Độ sâu")
    # The plane's point sits one depth behind the line, along +Y (far side).
    assert depth.point.y() * 1000.0 == pytest.approx(3000.0 - 4000.0, abs=1e-3)


def test_an_elevation_does_not_cut(house):
    b = house
    row = {"kind": "elevation", "story_id": _story(b)["id"],
           "p1": [0.0, 0.0], "p2": [6000.0, 0.0], "normal": [0.0, -1.0]}
    view = D.view_for(b, row)
    assert view.section_planes == []                       # nothing is cut
    assert len(view.clip_planes) == 3                      # only trimmed


def test_an_interior_elevation_windows_floor_to_ceiling(house):
    b = house
    row = {"kind": "interior", "story_id": _story(b)["id"],
           "p1": [1000.0, 0.0], "p2": [1000.0, 3000.0],
           "normal": [-1.0, 0.0], "z_mm": 0.0, "height_mm": 2400.0}
    view = D.view_for(b, row)
    names = {sp.name for sp in view.clip_planes}
    assert {"Cao độ đỉnh", "Cao độ đáy"} <= names
    top = next(sp for sp in view.clip_planes if sp.name == "Cao độ đỉnh")
    assert top.point.z() * 1000.0 == pytest.approx(2400.0, abs=1e-3)
    bottom = next(sp for sp in view.clip_planes
                  if sp.name == "Cao độ đáy")
    assert bottom.point.z() * 1000.0 == pytest.approx(-D.INTERIOR_BELOW_MM, abs=1e-3)


def test_the_scale_is_the_first_standard_that_fits(house):
    """A 6 m house on a 190 mm frame needs at least 1:32 → the next standard
    scale up is 1:50, never a made-up 1:32."""
    b = house
    view = D.view_for(b, {"kind": "story", "story_id": _story(b)["id"]},
                      frame_h_mm=190.0)
    assert view.scale_denom == 50.0


def test_a_drawing_view_round_trips(house):
    b = house
    view = D.view_for(b, {"kind": "story", "story_id": _story(b)["id"]})
    again = D.DrawingView.from_dict(view.to_dict())
    assert again.kind == view.kind
    assert again.story_id == view.story_id
    assert again.scale_denom == view.scale_denom
    assert len(again.section_planes) == len(view.section_planes)
    assert len(again.clip_planes) == len(view.clip_planes)
    assert again.clip_planes[0].clip_only is True


def test_a_detail_keeps_its_source_rule_and_crops_it(house):
    """A detail is the source drawing, cropped — the model is never copied,
    so it cannot fall out of step with the model the day after."""
    b = house
    source = D.view_for(b, {"kind": "story", "story_id": _story(b)["id"]},
                        scale_denom=50.0)
    detail = D.detail_view(b, {"kind": "detail", "name": "Chi tiết WC"},
                           source, rect=[0.0, 0.0, 2000.0, 1500.0],
                           scale_denom=20.0)
    assert detail.kind == D.KIND_DETAIL
    assert detail.scale_denom == 20.0
    assert len(detail.section_planes) == 1                 # the source's cut
    assert len(detail.clip_planes) == len(source.clip_planes) + 4
    assert detail.crop_u == (0.0, 2000.0)


# ---- the drawing's language -------------------------------------------------

def _annotated(house):
    scene = Scene()
    view = D.view_for(house,
                      {"kind": "story", "story_id": _story(house)["id"]})
    D.annotate_plan(scene, house, view)
    return scene, view


def test_the_chains_stand_10_and_18_paper_mm_off_the_outer_face(house):
    """The stand-off is PAPER millimetres: the model distance must be
    ``face + mm × scale``, which is what makes the two chains read at any
    scale. 18 − 10 = 8 paper mm apart, never 8 model millimetres."""
    b = house
    wall = b.elements[0]
    b.elements[1]["params"]["host_wall_id"] = wall["id"]
    scene, view = _annotated(b)
    denom = view.scale_denom
    offsets = sorted(d.perpendicular_offset().length() * 1000.0
                     for d in scene.dimensions)
    assert len(offsets) == 4                               # 3 detail + 1 total
    detail = {round(o, 6) for o in offsets[:3]}
    total = offsets[-1]
    assert len(detail) == 1
    d0 = detail.pop()
    assert d0 == pytest.approx(100.0 + D.DETAIL_OFFSET_PAPER * denom,
                               abs=0.5)
    assert total == pytest.approx(100.0 + D.TOTAL_OFFSET_PAPER * denom,
                                  abs=0.5)
    assert (total - d0) / denom == pytest.approx(
        D.TOTAL_OFFSET_PAPER - D.DETAIL_OFFSET_PAPER, abs=0.01)


def test_the_detail_chain_measures_each_opening_edge(house):
    """2550 / 900 / 2550 across a 6 m wall with a 900 door at u = 3000."""
    b = house
    b.elements[1]["params"]["host_wall_id"] = b.elements[0]["id"]
    scene, _view = _annotated(b)
    values = sorted(round(d.value() * 1000.0) for d in scene.dimensions)
    assert values == [900, 2550, 2550, 6000]


def test_a_wall_without_openings_gets_one_chain(house):
    b = house
    scene, _view = _annotated(b)          # the door has no host: no openings
    assert len(scene.dimensions) == 1
    assert round(scene.dimensions[0].value() * 1000.0) == 6000


def test_levels_are_written_the_vietnamese_way(house):
    b = house
    b.elements[1]["params"]["host_wall_id"] = b.elements[0]["id"]
    scene, _view = _annotated(b)
    texts = {lab.text for lab in scene.text_labels}
    assert "FL:+0000" in texts             # floor
    assert "CL:+3300" in texts             # ceiling of the same storey
    assert D.level_box_text("FL", -450) == "FL:-0450"
    assert D.level_triangle_text(2700) == "+2.700"


def test_a_room_stamp_carries_its_name_and_area(house):
    """The stamp shows the SAME number the takeoff states — one source for
    an area, or the sheet and the schedule disagree and the office loses a
    day reconciling them."""
    b = house
    area = b.elements[2]["derived"]["area_m2"]
    scene, _view = _annotated(b)
    stamps = [lab for lab in scene.text_labels if "Phòng khách" in lab.text]
    assert len(stamps) == 1
    assert f"{area:.2f} m\u00b2" in stamps[0].text
    assert stamps[0].layer == D.ANNOT_LAYER


def test_a_room_without_an_area_still_gets_its_name(house):
    """A stamp with no area is worse than a stamp with only a name: an
    empty 'm²' line reads as a zero."""
    b = house
    b.elements[2].pop("derived", None)
    scene, _view = _annotated(b)
    stamps = [lab for lab in scene.text_labels if "Phòng khách" in lab.text]
    assert len(stamps) == 1
    assert stamps[0].text == "Phòng khách"


def test_everything_the_drawing_writes_sits_on_one_layer(house):
    """One layer = one switch: an office hides the whole annotation set
    without hunting for the dimension it does not want to issue."""
    b = house
    b.elements[1]["params"]["host_wall_id"] = b.elements[0]["id"]
    scene, _view = _annotated(b)
    assert scene.layer(D.ANNOT_LAYER) is not None
    assert {d.layer for d in scene.dimensions} == {D.ANNOT_LAYER}
    assert {lab.layer for lab in scene.text_labels} == {D.ANNOT_LAYER}


def test_annotation_is_one_undo_step_when_a_history_is_given(house):
    """Passing a history must make the whole drawing one step — and undo
    must take every bit of it back."""
    from core.history import History
    b = house
    b.elements[1]["params"]["host_wall_id"] = b.elements[0]["id"]
    scene = Scene()
    history = History(scene)
    view = D.view_for(b, {"kind": "story", "story_id": _story(b)["id"]})
    D.annotate_plan(scene, b, view, history=history)
    assert scene.dimensions and scene.text_labels
    while history.undo():
        pass
    assert scene.dimensions == [] and scene.text_labels == []


# ---- the drawing on a sheet -------------------------------------------------

def test_placing_a_plan_on_a_sheet_records_the_rule_as_a_scene(house):
    """A frame renders what a SCENE says: the drawing must be captured as
    a saved scene, or the sheet would show whatever the live camera
    happened to be left at — the very dependence on the model's state that
    stating drawings as rules exists to remove."""
    from core.composition import Composicion
    b = house
    scene = Scene()
    view = D.view_for(b, {"kind": "story", "story_id": _story(b)["id"]})
    sheet = Composicion(name="KT00-01", paper="A3")
    frame = D.place_on_sheet(sheet, view, scene, name="Mặt bằng Tầng 1")

    assert frame in sheet.frames
    assert frame.view_key == "scene:Mặt bằng Tầng 1"
    assert frame.scale_n == view.scale_denom
    assert frame.show_title is True

    (saved,) = scene.saved_views
    assert saved.name == "Mặt bằng Tầng 1"
    assert saved.drawing["kind"] == D.KIND_STORY
    clips = saved.drawing["clips"]
    assert len(clips) == 1
    assert clips[0]["clip_only"] is True


def test_re_placing_the_same_drawing_updates_it_in_place(house):
    """Re-issuing is the normal case: the second placement must not leave
    two scenes fighting over one frame key."""
    from core.composition import Composicion
    b = house
    scene = Scene()
    view = D.view_for(b, {"kind": "story", "story_id": _story(b)["id"]})
    sheet = Composicion(name="KT00-01", paper="A3")
    D.place_on_sheet(sheet, view, scene, name="Mặt bằng Tầng 1")
    D.place_on_sheet(sheet, view, scene, name="Mặt bằng Tầng 1")
    assert len(scene.saved_views) == 1


def test_a_frame_renders_with_the_drawing_s_floor_trim(house):
    """The composer publishes the scene's clips around the frame, so the
    HLR pass drops what lies under the floor without a cut chord."""
    from core.hlr import hlr_drawing
    from core.composition import Composicion
    from core.saved_views import SavedView
    b = house
    scene = Scene()
    view = D.view_for(b, {"kind": "story", "story_id": _story(b)[ "id"]})
    D.place_on_sheet(Composicion(name="KT00-01", paper="A3"), view, scene,
                     name="Mặt bằng Tầng 1")
    (saved,) = scene.saved_views
    scene.view_clip_planes = [
        __import__("core.section", fromlist=["SectionPlane"])
        .SectionPlane.from_dict(raw) for raw in saved.drawing["clips"]]
    assert len(scene.view_clip_planes) == 1
    drawing = hlr_drawing(scene, view.camera())
    assert drawing.segs.shape[1] == 4
    # A clip plane never contributes a cut chord.
    assert drawing.kinds is None or not (drawing.kinds == 2).any()


def test_a_storeys_grid_lands_on_the_plan_with_names_both_ends():
    """A grid is how the trade TALKS about a plan («trục B»): each axis
    runs across and carries its own name at both ends."""
    from core.building.drawings import grid_axes, draw_grid, view_for
    from core.building.model import Building
    from core.building.builder import build
    from core.scene import Scene

    b = Building()
    story = b.add_story("Tầng 1", 0.0, 3300.0)
    b.add_element("grid", story["id"], {"axes": [
        {"name": "1", "dir": "y", "offset_mm": 0.0},
        {"name": "2", "dir": "y", "offset_mm": 6000.0},
        {"name": "A", "dir": "x", "offset_mm": 0.0},
        {"name": "B", "dir": "x", "offset_mm": 4000.0}]})
    for element in list(b.elements):
        build(b, element)
    axes = grid_axes(b, story)
    assert len(axes) == 4
    scene = Scene()
    view = D.view_for(b, {"kind": "story", "story_id": story["id"]})
    made = draw_grid(scene, b, view, key="k")
    names = sorted(t.text for t in made if hasattr(t, "text"))
    assert names == ["1", "1", "2", "2", "A", "A", "B", "B"]
    lines = [e for e in made if hasattr(e, "a")]
    assert len(lines) == 4
    assert all(e.layer == "KT-Trục" for e in made)


def test_a_grid_with_a_duplicate_name_is_refused_at_build_time():
    from core.building.builder import build
    from core.building.model import Building

    b = Building()
    story = b.add_story("Tầng 1", 0.0, 3300.0)
    grid = b.add_element("grid", story["id"], {"axes": [
        {"name": "1", "dir": "y", "offset_mm": 0.0},
        {"name": "1", "dir": "x", "offset_mm": 0.0}]})
    with pytest.raises(ValueError):
        build(b, grid)


def test_reissuing_a_plan_replaces_its_grid_instead_of_stacking():
    from core.building.drawings import draw_grid, view_for
    from core.building.model import Building
    from core.building.builder import build
    from core.scene import Scene

    b = Building()
    story = b.add_story("Tầng 1", 0.0, 3300.0)
    b.add_element("grid", story["id"], {"axes": [
        {"name": "1", "dir": "y", "offset_mm": 0.0},
        {"name": "A", "dir": "x", "offset_mm": 0.0}]})
    for element in list(b.elements):
        build(b, element)
    scene = Scene()
    view = D.view_for(b, {"kind": "story", "story_id": story["id"]})
    draw_grid(scene, b, view, key="p")
    first = len(scene.text_labels)
    draw_grid(scene, b, view, key="p")
    assert len(scene.text_labels) == first, "sinh lại không được xếp thêm trục"


def test_a_door_carries_its_mark_on_the_plan():
    """The mark is the name the schedule row is written under: a door
    nobody can point at on the plan is a list, not a drawing."""
    from core.building.drawings import opening_tags
    from core.building.model import Building
    from core.building.builder import build

    b = Building()
    story = b.add_story("Tầng 1", 0.0, 3300.0)
    wall = b.add_element("wall", story["id"], {
        "baseline_start_mm": [0, 0], "baseline_end_mm": [6000, 0],
        "thickness_mm": 200.0, "height_mm": 3300.0})
    b.add_element("door", story["id"], {
        "host_wall_id": wall["id"], "offset_along_wall_mm": 3000.0,
        "width_mm": 900.0, "height_mm": 2200.0, "name": "D1"})
    b.add_element("window", story["id"], {
        "host_wall_id": wall["id"], "offset_along_wall_mm": 5000.0,
        "width_mm": 1200.0, "height_mm": 1400.0, "name": "W1"})
    for element in list(b.elements):
        build(b, element)
    tags = opening_tags(b, story)
    assert sorted(t[0] for t in tags) == ["D1", "W1"]
    # The mark stands at the opening's centre, in model mm.
    assert tags[0][1] == 3000.0
    # An unnamed opening has no mark to draw — the schedule shows it blank.
    b.element(b.elements[1]["id"])["params"].pop("name")
    assert [t[0] for t in opening_tags(b, story)] == ["W1"]


def test_an_opening_whose_wall_is_gone_is_skipped_not_crashed():
    from core.building.drawings import opening_tags
    from core.building.model import Building

    b = Building()
    story = b.add_story("Tầng 1", 0.0, 3300.0)
    b.add_element("door", story["id"], {
        "host_wall_id": "khong-ton-tai", "offset_along_wall_mm": 0.0,
        "width_mm": 900.0, "height_mm": 2200.0, "name": "D9"})
    assert opening_tags(b, story) == []
