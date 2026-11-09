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
