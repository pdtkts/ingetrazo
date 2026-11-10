# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Marco Sumari Tellez and IngeTrazo contributors.
"""Lập hồ sơ: the whole drawing set from the model, in one call.

The invariant that matters to an office is RE-ISSUING: running the set a
second time after editing the model must re-fill the same sheets, not
double them — otherwise every revision leaves a set nobody can trust.
"""
from __future__ import annotations

import pytest

from core.building import docset as DS
from core.building.builder import build
from core.building.model import Building
from core.scene import Scene


def _house(storeys: int = 3) -> Building:
    b = Building()
    b.project["name"] = "Nhà phố 3 tầng"
    rows = []
    for i in range(storeys):
        rows.append(b.add_story(f"Tầng {i + 1}", i * 3300.0, 3300.0))
    for i, s in enumerate(rows):
        top = "next" if i < len(rows) - 1 else "none"
        b.add_element("wall", s["id"], {
            "baseline_start_mm": [0, 0], "baseline_end_mm": [6000, 0],
            "thickness_mm": 200.0, "height_mm": 3300.0, "top_link": top})
        b.add_element("wall", s["id"], {
            "baseline_start_mm": [0, 0], "baseline_end_mm": [0, 4000],
            "thickness_mm": 200.0, "height_mm": 3300.0, "top_link": top})
        zone = b.add_element("zone", s["id"], {
            "outline_mm": [[300, 300], [5700, 300], [5700, 3700], [300, 3700]],
            "name": f"Phòng {i + 1}"})
        _mesh, derived = build(b, zone)
        zone["derived"] = derived
    wall = b.elements[0]
    door = b.add_element("door", rows[0]["id"], {
        "host_wall_id": wall["id"], "offset_along_wall_mm": 3000.0,
        "width_mm": 900.0, "height_mm": 2200.0, "name": "D1"})
    build(b, door)
    stair = b.add_element("stair", rows[0]["id"], {
        "path_mm": [[500.0, 500.0], [500.0, 3000.0]], "width_mm": 1000.0,
        "tread_mm": 260.0})
    build(b, stair)
    return b


def test_the_set_issues_every_storey_and_a_sheet_per_drawing():
    b = _house(3)
    scene = Scene()
    result = DS.generate_docset(scene, b)
    names = [str(s.name) for s in result.sheets]
    for i in (1, 2, 3):
        for trade in ("Mặt bằng — ", "Mặt bằng tường — ",
                      "Mặt bằng lát sàn — ", "Mặt bằng trần — "):
            assert any(f"{trade}Tầng {i}" in n for n in names), (trade, i)
    assert any("Trang bìa" in n for n in names)
    assert any("Bảng liệt kê" in n for n in names)
    assert any("Mặt cắt" in n for n in names)
    assert any("Mặt đứng" in n for n in names)
    assert any("Định vị cửa" in n for n in names)         # the house has one
    assert any("Cầu thang" in n for n in names)
    # …and the house that would need them gets them (issue order is fixed).
    codes = [s.split(" ")[0] for s in names]
    assert codes == sorted(codes, key=lambda c: names[codes.index(c)])


def test_re_issuing_fills_the_same_sheets_without_doubling():
    b = _house(2)
    scene = Scene()
    first = DS.generate_docset(scene, b)
    frames = sum(len(s.frames) for s in first.sheets)
    texts = sum(len(s.texts) for s in first.sheets)
    scenes = len(scene.saved_views)
    second = DS.generate_docset(scene, b)
    assert len(second.sheets) == len(first.sheets)
    assert sum(len(s.frames) for s in second.sheets) == frames
    assert sum(len(s.texts) for s in second.sheets) == texts
    assert len(scene.saved_views) == scenes


def test_a_plan_sheet_is_actually_drawn_not_left_blank():
    """A sheet with no frame is the failure mode that looks like success:
    the set exists, the pages are empty."""
    b = _house(2)
    scene = Scene()
    result = DS.generate_docset(scene, b)
    plans = [s for s in result.sheets if "Mặt bằng —" in str(s.name)]
    assert len(plans) == 2
    for sheet in plans:
        assert len(sheet.frames) == 1
        frame = sheet.frames[0]
        assert frame.view_key.startswith("scene:")
        assert frame.render_px()[0] > 100          # a real frame, not a stub
    # …and the plan carries the drawing's language.
    assert len(scene.dimensions) > 0
    stamps = [lab for lab in scene.text_labels if "Phòng 1" in lab.text]
    assert len(stamps) == 1
    assert "m²" in stamps[0].text


def test_the_cover_states_the_building_it_belongs_to():
    b = _house(3)
    scene = Scene()
    result = DS.generate_docset(scene, b)
    cover = next(s for s in result.sheets if "Trang bìa" in str(s.name))
    (block,) = [t for t in cover.texts if t.list_name == "__cover__"]
    assert "Nhà phố 3 tầng" in block.text
    assert "Số tầng: 3" in block.text
    assert "9.90 m" in block.text                 # three storeys of 3300


def test_the_sheet_list_names_every_sheet_in_issue_order():
    b = _house(2)
    scene = Scene()
    result = DS.generate_docset(scene, b)
    index = next(s for s in result.sheets
                 if "Bảng liệt kê" in str(s.name))
    (block,) = [t for t in index.texts if t.list_name == "__index__"]
    codes = [str(s.name).split(" ")[0] for s in result.sheets]
    for code in codes:
        assert code in block.text
    assert block.text.index(codes[0]) < block.text.index(codes[-1])


def test_the_check_says_what_is_missing_before_generating():
    """A warning is worth more before the run than after: an empty plan
    looks exactly like a plan until it is printed."""
    b = Building()
    b.add_story("Tầng 1", 0.0, 3300.0)          # a storey with nothing on it
    issues = DS.check_docset(b)
    texts = [i for i, _severity in issues]
    assert any("không có tường" in t for t in texts)
    assert any("chưa có phòng" in t for t in texts)

    full = _house(1)
    issues = DS.check_docset(full)
    assert not [t for t, sev in issues
                if sev == "warn"
                and ("không có tường" in t or "chưa có phòng" in t)]


def test_an_empty_building_is_reported_not_crashed():
    b = Building()
    issues = DS.check_docset(b)
    assert issues and issues[0][1] == "warn"
    scene = Scene()
    result = DS.generate_docset(scene, b)
    assert result.sheets == []


def test_the_progress_callback_walks_the_whole_run():
    b = _house(2)
    scene = Scene()
    seen: list = []
    DS.generate_docset(scene, b, progress=lambda i, t, label:
                       seen.append((i, t, label)))
    assert seen
    assert seen[-1][0] <= seen[-1][1]
    assert all(total >= index for index, total, _ in seen)
    assert any("Trang bìa" in label for _i, _t, label in seen)


def test_generating_after_an_edit_updates_the_drawing():
    """The revised model must reach the sheet: an office re-issues, it does
    not start over."""
    b = _house(1)
    scene = Scene()
    DS.generate_docset(scene, b)
    before = len(scene.dimensions)
    b.elements[0]["params"]["baseline_end_mm"] = [9000.0, 0.0]
    build(b, b.elements[0])
    scene2 = Scene()
    DS.generate_docset(scene2, b)
    assert scene2.dimensions
    values = sorted(round(d.value() * 1000.0) for d in scene2.dimensions)
    assert max(values) == 9000                # the longer wall is measured
    assert before > 0


def test_no_sheet_leaves_the_office_blank():
    """A sheet that is issued but never drawn is bound and printed anyway.

    So the set must satisfy one invariant: every sheet it hands back has
    either a drawing on it or words on it. The cover and the sheet list are
    words-only by design; a trades' sheet with neither is the failure this
    test exists to catch — an empty column layout, an empty stair sheet and
    an empty detail sheet all shipped once.
    """
    b = _house(2)
    scene = Scene()
    result = DS.generate_docset(scene, b)
    assert result.sheets
    offenders = [s.name for s in result.sheets
                 if not s.frames
                 and not any(str(t.text).strip() for t in s.texts)]
    assert offenders == [], f"tờ phát hành nhưng trắng: {offenders}"


def test_a_trade_the_model_does_not_have_gets_no_sheet():
    """An empty column layout is worse than no column layout."""
    b = _house(1)
    names = [s.title for s in DS._sheets.sheet_plan(b)]
    assert not any("Định vị cột" in t for t in names)
    assert not any("Định vị dầm" in t for t in names)
    # …while a trade the house HAS keeps its sheet.
    assert any("Cầu thang" in t for t in names)


def test_the_door_sheet_states_the_schedule_the_takeoff_bills():
    """Where the door is AND what it is, from one set of numbers."""
    b = _house(1)
    scene = Scene()
    result = DS.generate_docset(scene, b)
    sheet = next((s for s in result.sheets if "Định vị cửa" in s.name), None)
    assert sheet is not None and sheet.frames, "tờ định vị cửa phải có bản vẽ"
    block = next((t for t in sheet.texts
                  if t.list_name == "__schedule_openings__"), None)
    assert block is not None, "tờ định vị cửa phải có bảng thống kê"
    assert "Cửa đi" in block.text and "D1" in block.text
    # The count in the schedule is the model's count, not a copy that ages.
    assert "1" in block.text
    result2 = DS.generate_docset(scene, b)
    sheet2 = next((s for s in result2.sheets if "Định vị cửa" in s.name), None)
    schemas = [t for t in sheet2.texts
               if t.list_name == "__schedule_openings__"]
    assert len(schemas) == 1, "sinh lại không được xếp thêm bảng thứ hai"


def test_a_reissue_prints_the_new_cut_not_yesterdays():
    """The storey rises; the sheet must show the cut at the new height.

    Re-issuing reuses the frame (a second frame would double the drawing
    on the page) — and that reuse is exactly where a stale cut hides: the
    frame renders what its SCENE says, so the scene's rule has to be
    rewritten with the model. This failed silently: the sheet kept the
    old cut and nobody could see it until it was printed.
    """
    b = _house(1)
    scene = Scene()
    DS.generate_docset(scene, b)
    plan = next(x for x in scene.saved_views if x.name == "Mặt bằng Tầng 1")
    before = float(plan.target[2])
    frames = sum(len(s.frames) for s in scene.compositions)

    b.story(b.stories[0]["id"])["z_mm"] = 900.0
    DS.generate_docset(scene, b)
    again = next(x for x in scene.saved_views if x.name == "Mặt bằng Tầng 1")
    assert float(again.target[2]) > before, "cao độ cắt phải đi theo tầng"
    assert sum(len(s.frames) for s in scene.compositions) == frames, \
        "sinh lại không được thêm khung"


def test_inserting_a_storey_reissues_the_set_without_orphans():
    """Sheet codes are POSITIONAL: inserting a storey renumbers everything
    below it, so the previous issue's sheets would linger beside the new
    set and the document would carry both drawings of the same floor."""
    b = _house(2)
    scene = Scene()
    DS.generate_docset(scene, b)
    first = len(scene.compositions)
    b.stories.insert(1, {"id": "mid", "name": "Tầng 1.5", "z_mm": 1650.0,
                         "height_mm": 1650.0})
    result = DS.generate_docset(scene, b)
    assert len(scene.compositions) == len(result.sheets), \
        "không được để lại tờ của lần phát hành trước"
    assert len(scene.compositions) > first
    codes = [s.name.split(" ")[0] for s in scene.compositions]
    assert len(set(codes)) == len(codes), f"mã tờ trùng: {codes}"


def test_a_sheet_the_user_drew_by_hand_is_never_deleted():
    """The generator owns its KT-coded set and nothing else."""
    from core.composition import Composicion

    b = _house(1)
    scene = Scene()
    DS.generate_docset(scene, b)
    mine = Composicion(name="Bản vẽ tay")
    scene.compositions.append(mine)
    DS.generate_docset(scene, b)
    assert mine in scene.compositions


def test_reissuing_does_not_pile_up_cut_planes():
    """A scene refers to its cut by uid, so the planes a drawing
    publishes must be REPLACED on re-issue, not added beside the old
    ones — three issues used to leave three cuts for one plan, and a
    plane the office made by hand must never be swept up with them."""
    from PySide6.QtGui import QVector3D
    from core.section import SectionPlane

    b = _house(2)
    scene = Scene()
    hand = SectionPlane(QVector3D(0.0, 0.0, 5.0), QVector3D(0.0, 0.0, 1.0),
                        name="Mặt cắt của tôi")
    scene.section_planes.append(hand)
    DS.generate_docset(scene, b)
    first = len(scene.section_planes)
    DS.generate_docset(scene, b)
    assert len(scene.section_planes) == first, "sinh lại không được thêm mặt phẳng"
    b.stories.insert(1, {"id": "mid", "name": "Tầng 1.5", "z_mm": 1650.0,
                         "height_mm": 1650.0})
    DS.generate_docset(scene, b)
    assert hand in scene.section_planes, "mặt phẳng tự tay tạo phải còn nguyên"
    assert len(scene.section_planes) <= first + 4, \
        "tầng mới chỉ thêm mặt phẳng cho chính nó"


def test_the_generator_deletes_its_own_sheets_by_identity_not_by_name():
    """A sheet is the generator's only if the generator made it.

    Ownership used to be read from the name's ``KT`` prefix, so a note
    sheet the user named after the project's own numbering was deleted on
    the next issue. It is now the sheet's own ``bim_key``: an identity the
    generator writes and nothing else has.
    """
    from core.composition import Composicion

    b = _house(1)
    scene = Scene()
    DS.generate_docset(scene, b)
    mine = Composicion(name="KT-ghi chú của tôi")
    scene.compositions.append(mine)
    DS.generate_docset(scene, b)
    assert mine in scene.compositions, "tờ do người dùng đặt tên bị xoá"
    assert all(getattr(s, "bim_key", "") for s in scene.compositions
               if s is not mine), "tờ sinh ra phải mang danh tính của nó"


def test_a_subset_issue_does_not_delete_the_other_storeys_sheets():
    """Issuing one storey's sheets must not take the set apart.

    A subset is a re-issue OF those sheets: the others are not part of the
    request, which is not the same as being superseded. Deleting them
    would take hand edits with them and renumber the survivors.
    """
    from core.building import sheets as _sheets

    b = _house(2)
    scene = Scene()
    first = DS.generate_docset(scene, b)
    assert len(first.sheets) > 4
    one = b.stories[0]["id"]
    before = {getattr(s, "bim_key", "") for s in scene.compositions}
    _sheets.ensure_sheets(scene, b, story_ids=[one],
                          elevations=False, sections=False)
    after = {getattr(s, "bim_key", "") for s in scene.compositions}
    assert before <= after, f"mất tờ của tầng khác: {before - after}"


def test_a_drawing_scene_carries_the_drawing_s_own_layers_not_the_live_ones():
    """A layer the user happened to hide in the 3D must not be baked into
    the sheet: the scene records the VIEW's own filter, always."""
    from core.building import sheets as _sheets
    from core.layers import Layer

    b = _house(1)
    scene = Scene()
    _sheets.ensure_sheets(scene, b)
    layer = next((ly for ly in scene.layers
                  if str(getattr(ly, "name", "")).startswith("BIM")), None)
    if layer is None:
        layer = Layer("BIM Tường")
        scene.layers.append(layer)
    layer.visible = False
    DS.generate_docset(scene, b)
    view = next(v for v in scene.saved_views if v.name.startswith("Mặt bằng"))
    assert layer.name not in view.hidden_layers, \
        "lớp người dùng ẩn trong 3D bị đóng vào bản vẽ"


def test_a_same_named_scene_the_user_saved_is_not_hijacked():
    """The generator reuses ITS OWN scenes; a scene the user saved under
    the same name keeps its camera and its layers."""
    from core.building import sheets as _sheets
    from core.saved_views import SavedView

    b = _house(1)
    scene = Scene()
    mine = SavedView("Mặt bằng Tầng 1", target=(99.0, 99.0, 99.0),
                     distance=7.0, yaw=0.3, pitch=0.4)
    mine.hidden_layers = ["Lớp của tôi"]
    scene.saved_views.append(mine)
    DS.generate_docset(scene, b)
    assert mine.target == (99.0, 99.0, 99.0), "cảnh của người dùng bị ghi đè"
    assert mine.hidden_layers == ["Lớp của tôi"]
    assert len([v for v in scene.saved_views
                if v.name == "Mặt bằng Tầng 1"]) == 2, \
        "bản vẽ phải có cảnh riêng của nó"
    del _sheets


def test_reopening_the_file_does_not_stack_the_plan_annotations(tmp_path):
    """A re-issue REPLACES a drawing's dimensions and stamps, and it can
    only do that if it recognises them — after a save and a load too. The
    registry used to be in memory alone, so a reissued plan carried two
    dimension chains and two sets of room stamps."""
    from formats.igz import load_into, save_scene
    from core.building import drawings as _drawings

    b = _house(1)
    scene = Scene()
    DS.generate_docset(scene, b)
    before = (len(scene.dimensions), len(scene.text_labels))
    doc = tmp_path / "nha.igz"
    save_scene(scene, doc)
    back = Scene()
    load_into(back, doc)
    DS.generate_docset(back, b)
    after = (len(back.dimensions), len(back.text_labels))
    assert after == before, f"chú thích bị chồng sau khi mở lại: {before} → {after}"
    del _drawings


def test_reopening_the_file_does_not_stack_the_cut_planes(tmp_path):
    """A re-issue REPLACES its own cut planes; the registry that says
    which are its own is per session, so a reopened file indexes them by
    the tag their names carry."""
    from formats.igz import load_into, save_scene

    b = _house(1)
    scene = Scene()
    DS.generate_docset(scene, b)
    before = len(scene.section_planes)
    doc = tmp_path / "plans.igz"
    save_scene(scene, doc)
    back = Scene()
    load_into(back, doc)
    DS.generate_docset(back, b)
    assert len(back.section_planes) <= before + 2, \
        f"mặt phẳng cắt bị chồng: {before} → {len(back.section_planes)}"


def test_everything_bim_survives_a_save_and_reopen(tmp_path):
    """L149: between them, the BIM features write to a dozen places on the
    document — storeys and elements, the materials a wall is made of, the
    steel a column is ordered as, the pens and the layer names the office
    set, the drawn entities, the drawing set's own annotations. A save and
    reopen must bring back ALL of it: a feature whose data does not travel
    is a feature the colleague does not see.
    """
    from core.building import commands as C
    from core.building import samples as _samples
    from core.building.model import building_of
    from core.history import History
    from core.plan_draw import PlanCurve
    from core.scene import Scene
    from formats import igz

    scene = Scene()
    history = History(scene)
    _samples.build_sample(history, scene, "townhouse")
    building = building_of(scene)
    story_id = str(building.stories[0]["id"])

    # A little of every kind of BIM data, through the app's own commands.
    wall = next(e for e in building.elements if e.get("type") == "wall")
    for command in (
            C.set_params(str(wall["id"]), {"thickness_mm": 275.0,
                                           "building_material_id": "btct"}),
            C.add_element("column", story_id, {
                "x_mm": 2500.0, "y_mm": 1500.0, "width_mm": 300.0,
                "depth_mm": 300.0, "height_mm": 3300.0}),
            C.set_story_params(story_id, {"name": "Tầng trệt"})):
        history.execute(command)

    scene.plan_curves.append(PlanCurve("line", [(0.0, 0.0), (5000.0, 0.0)],
                                       z=1.2, story_id=story_id))
    scene.pens = dict(scene.pens or {})
    scene.pens["cut"] = (0.5, 4, "continuous")
    # A published drawing's own annotation. The registry records POSITIONS
    # of the entities themselves, so a drawing with no annotations is
    # correctly not recorded at all — the mark has to be a real one.
    from PySide6.QtGui import QVector3D

    from core.dimension import Dimension

    mark = Dimension(QVector3D(0.0, 0.0, 1.2), QVector3D(5.0, 0.0, 1.2),
                     QVector3D(0.0, 0.5, 0.0))
    scene.dimensions.append(mark)
    scene.bim_annotations["Mặt bằng thử"] = [mark]

    before = {
        "wall_thickness": next(e["params"]["thickness_mm"]
                               for e in building_of(scene).elements
                               if e.get("type") == "wall"
                               and str(e["id"]) == str(wall["id"])),
        "wall_material": next(e["params"].get("building_material_id")
                              for e in building_of(scene).elements
                              if str(e["id"]) == str(wall["id"])),
        "columns": len([e for e in building_of(scene).elements
                        if e.get("type") == "column"]),
        "story_name": (building_of(scene).story(story_id) or {}).get("name"),
        "curves": [c.to_dict() for c in scene.plan_curves],
        "pens": dict(scene.pens),
        "annotations": sorted(scene.bim_annotations),
        "annotation_marks": len(next(iter(scene.bim_annotations.values()))),
    }

    path = tmp_path / "all.igz"
    igz.save_scene(scene, path)
    reopened = Scene()
    igz.load_into(reopened, path)
    after_building = building_of(reopened)

    assert next(e["params"]["thickness_mm"]
                for e in after_building.elements
                if str(e["id"]) == str(wall["id"])) == \
        before["wall_thickness"]
    assert next(e["params"].get("building_material_id")
                for e in after_building.elements
                if str(e["id"]) == str(wall["id"])) == before["wall_material"]
    assert len([e for e in after_building.elements
                if e.get("type") == "column"]) == before["columns"]
    assert (after_building.story(story_id) or {}).get("name") == \
        before["story_name"]
    assert [c.to_dict() for c in reopened.plan_curves] == before["curves"]
    assert dict(reopened.pens) == before["pens"]
    assert sorted(reopened.bim_annotations) == before["annotations"]
    # …and the mark itself came back, not just the key: the registry points
    # at entities the loader rebuilt, which is what makes a re-issue
    # replace rather than stack.
    assert sum(len(v) for v in reopened.bim_annotations.values()) == \
        before["annotation_marks"]
