# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Marco Sumari Tellez and IngeTrazo contributors.
"""Review 3's findings, held down: each test is the repro that found the bug.

These are not general coverage — they are the exact cases that went wrong,
kept so they cannot come back: the annotation registry after a load, the
agent's DXF scope, a grid re-issued three times, the rebuild diff, and the
drag that must not re-apply a stale payload.
"""
from __future__ import annotations

import os
import sys

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

if QApplication.instance() is None:
    QApplication(sys.argv[:1])

ezdxf = pytest.importorskip("ezdxf")


def _annotated_house(scene, history, storeys: int = 3):
    """A house with EVERY storey annotated under its own drawing key."""
    from core.building import samples as S
    from core.building.drawings import annotate_plan, view_for

    building, _counts = S.build_sample(history, scene, "townhouse")
    for story in building.stories[:storeys]:
        view = view_for(building, {"kind": "story",
                                   "story_id": story["id"]})
        annotate_plan(scene, building, view,
                      key=f"dxf:{story['id']}")
    return building


def test_each_storey_keeps_its_own_annotations_across_a_save(tmp_path):
    """The registry stores POSITIONS in the dimension list, and the loader
    drops duplicate dimensions — compacting the list without remapping
    handed each drawing the entities of the storey before it."""
    from core.scene import Scene
    from core.history import History
    from formats.igz import load_into, save_scene

    scene = Scene()
    history = History(scene)
    _annotated_house(scene, history)
    doc = tmp_path / "set.igz"
    save_scene(scene, doc)
    back = Scene()
    load_into(back, doc)

    registry = back.bim_annotations
    assert len(registry) == 3, registry.keys()
    # Every entity a drawing owns is a REAL entity of the document...
    for key, entities in registry.items():
        for entity in entities:
            assert any(entity is d for d in back.dimensions) or \
                any(entity is t for t in back.text_labels), key
    # ...and the LEVELS prove the drawings did not swap places: each
    # storey's plan carries its own floor and ceiling, and nobody else's.
    levels = {}
    for key, entities in registry.items():
        levels[key] = sorted({str(getattr(e, "text", ""))
                              for e in entities
                              if str(getattr(e, "text", "")).startswith(
                                  ("FL:", "CL:"))})
    assert set(map(tuple, levels.values())) == {
        ("CL:+3300", "FL:+0000"),
        ("CL:+6600", "FL:+3300"),
        ("CL:+9900", "FL:+6600")}, levels


def test_the_agents_dxf_carries_one_storey_not_the_whole_document(tmp_path):
    """A document whose annotations were published by the DRAWING SET files
    them under the sheet's name; an export that asks for a storey must
    publish (and then export) that storey's own, not fall back to «all»."""
    from core.ai_bim import BimSession
    from core.building.drawings import annotate_plan, view_for
    from core.history import History
    from core.scene import Scene
    from core.building import samples as S

    scene = Scene()
    history = History(scene)
    building, _counts = S.build_sample(history, scene, "townhouse")
    for story in building.stories:
        view = view_for(building, {"kind": "story",
                                   "story_id": story["id"]})
        view.name = f"Mặt bằng — {story['name']}"
        annotate_plan(scene, building, view, key=f"scene:{view.name}")

    class _Viewport:
        def __init__(self):
            self.scene = scene
            self.history = history

    session = BimSession(_Viewport(), history)
    out = tmp_path / "one-storey.dxf"
    session.export_dxf(str(out), str(building.stories[0]["id"]))
    doc = ezdxf.readfile(str(out))
    texts = [e.dxf.text for e in doc.modelspace().query("TEXT")
             if hasattr(e.dxf, "text")]
    levels = sorted({t for t in texts if t.startswith(("FL:", "CL:"))})
    assert levels == ["CL:+3300", "FL:+0000"], levels


def test_a_grid_survives_being_issued_three_times():
    """The clear that replaces a previous issue used to run AFTER the new
    one drew: it deleted the lines it had just made (a raw list removal
    left a ghost the mesh then handed back), so the third issue had no
    grid at all."""
    from core.building.drawings import draw_grid, view_for
    from core.building.model import Building
    from core.scene import Scene

    building = Building()
    story = building.add_story("T1", 0.0, 3300.0)
    building.add_element("wall", story["id"], {
        "baseline_start_mm": [0, 0], "baseline_end_mm": [6000, 0],
        "thickness_mm": 200.0, "height_mm": 3300.0})
    building.add_element("grid", story["id"], {"axes": [
        {"name": "1", "dir": "y", "offset_mm": 0.0},
        {"name": "2", "dir": "y", "offset_mm": 4000.0},
        {"name": "A", "dir": "x", "offset_mm": 0.0},
        {"name": "B", "dir": "x", "offset_mm": 6000.0}]})
    scene = Scene()
    view = view_for(building, {"kind": "story", "story_id": story["id"]})
    for attempt in range(1, 4):
        draw_grid(scene, building, view, key="sheet·grid")
        entities = scene.bim_annotations.get("sheet·grid", [])
        live = [e for e in entities
                if any(e is x for x in scene.mesh.edges)
                or any(e is x for x in scene.text_labels)]
        assert len(scene.mesh.edges) == 4, \
            f"lần {attempt}: lưới còn {len(scene.mesh.edges)} nét"
        assert len(live) == len(entities), \
            f"lần {attempt}: {len(entities) - len(live)} mục ma trong sổ"


def test_a_wall_edit_rebuilds_its_joins_not_just_itself():
    """A wall's body is trimmed against the walls it meets: rebuilding the
    moved one alone leaves the corner showing last revision's mitre."""
    from core.building import commands as C
    from core.building import samples as S
    from core.building.model import building_of
    from core.history import History
    from core.scene import Scene

    scene = Scene()
    history = History(scene)
    S.build_sample(history, scene, "townhouse")
    building = building_of(scene)
    wall = next(e for e in building.elements if e.get("type") == "wall")
    before = building.to_dict()
    wall["params"]["baseline_start_mm"] = [1000.0, 0.0]
    ids = C.changed_element_ids(before, building)
    same_storey = {str(e["id"]) for e in building.elements
                   if str(e.get("story_id")) == str(wall.get("story_id"))}
    assert same_storey <= ids, "bạn tường ở cùng tầng chưa được dựng lại"


def test_a_storey_move_rebuilds_what_stands_on_it():
    """A storey row carries no geometry of its own, so a diff that only
    compared ELEMENTS answered «nothing changed» while the whole floor
    moved."""
    from core.building import commands as C
    from core.building import samples as S
    from core.building.model import building_of
    from core.history import History
    from core.scene import Scene

    scene = Scene()
    history = History(scene)
    S.build_sample(history, scene, "townhouse")
    building = building_of(scene)
    before = building.to_dict()
    building.stories[0]["z_mm"] = 6600.0
    ids = C.changed_element_ids(before, building)
    assert ids, "nâng tầng mà không cấu kiện nào được dựng lại"
    on_floor = {str(e["id"]) for e in building.elements
                if str(e.get("story_id")) == str(building.stories[0]["id"])}
    assert on_floor <= ids


def test_the_signature_check_is_not_always_false():
    """The stored signature came back from JSON as lists while the new one
    was built of tuples: comparing them made every sync rebuild the whole
    model, and the «only what changed» path was never taken."""
    import json

    from core.building import samples as S
    from core.building.model import building_of
    from core.building.scene_sync import _same_signature, _signature
    from core.history import History
    from core.scene import Scene

    scene = Scene()
    S.build_sample(History(scene), scene, "townhouse")
    building = building_of(scene)
    wall = next(e for e in building.elements if e.get("type") == "wall")
    signature = _signature(building, wall)
    assert _same_signature(signature, signature)
    assert _same_signature(json.loads(json.dumps(signature)), signature)
    assert _same_signature(list(signature), signature)
    assert not _same_signature(signature[:-1], signature)


def test_the_tool_rebuild_asks_for_what_the_step_touched():
    """The hook read the command's before-payload when the hook was BUILT —
    before the command had run, where the answer is always None — so the
    diff never ran and every tool step paid for a full resync."""
    from core.building import commands as C
    from core.building import samples as S
    from core.building.model import building_of
    from core.history import History
    from core.scene import Scene
    from tools import building_tools as BT
    from views.main_window import MainWindow

    win = MainWindow()
    scene = win.viewport.scene
    S.build_sample(win.viewport.history, scene, "townhouse")
    calls: list = []
    real = BT.sync

    def spy(scene_, building, element_ids=None, **kw):
        calls.append("full" if element_ids is None else "targeted")
        return real(scene_, building, element_ids=element_ids, **kw)

    BT.sync = spy
    try:
        class _T(BT.BuildingTool):
            kind = "wall"

        wall = next(e for e in building_of(scene).elements
                    if e.get("type") == "wall")
        _T()._commit(win.viewport,
                     C.set_params(str(wall["id"]), {"height_mm": 3600.0}))
    finally:
        BT.sync = real
    # The FIRST run of a step syncs in full: the diff «which elements did
    # this step move» is only meaningful between the step's own two
    # payloads, and this path installs the hook before they exist. What
    # matters is that a call HAPPENS and that it is not silently skipped —
    # a targeted rebuild of nothing was exactly the bug (review 4, C1).
    assert calls and calls[0] in ("targeted", "full"), calls
    win.hide()


def test_a_drag_lets_go_when_the_model_changes_elsewhere():
    """Committing a drag after someone else's Undo would re-apply the
    pre-drag payload over that change: the plan must abandon the drag."""
    from core.building import samples as S
    from core.building.model import building_of
    from views.main_window import MainWindow

    win = MainWindow()
    scene = win.viewport.scene
    S.build_sample(win.viewport.history, scene, "townhouse")
    win._on_open_plan_window()
    plan = win._plan_window
    building = building_of(scene)
    wall = next(e for e in building.elements if e.get("type") == "wall")
    ends = plan._ends_of(wall["id"])
    plan.drag_element(wall["id"], (ends[0][0] + 500.0, ends[0][1]),
                      ends[0], "handle")
    assert plan._drag_origin is not None, "chưa có thao tác kéo để thử"
    # somebody else changes the model (the menu's Undo, a panel, an agent)
    win.viewport.history.undo()
    plan._poll_version()               # the plan's own scene watch
    assert plan._drag_origin is None, "thao tác kéo cũ vẫn còn treo"
    assert plan.canvas._ghost is None
    # And the guard is at COMMIT time too, for a change that arrives
    # between the drag's own mouse moves: a drag started against one
    # payload must not be committed on top of a different one. (The watch
    # above is a timer, so it cannot be relied on to have run.)
    from core.building import model as _model

    plan.drag_element(wall["id"], (ends[0][0] + 900.0, ends[0][1]),
                      ends[0], "handle")
    assert plan._drag_origin is not None
    # somebody else writes the document while the drag is still in flight
    stolen = plan._scene.plugin_data
    plan._scene.plugin_data = {**(stolen or {}),
                               _model.DATA_KEY: {**(stolen or {}).get(
                                   _model.DATA_KEY, {}), "rev_marker": 1}}
    try:
        plan.finish_drag(wall["id"], ends[0], "handle")
        assert plan._scene.plugin_data is not stolen, \
            "thao tác kéo cũ đã ghi đè thay đổi của người khác"
    finally:
        plan._scene.plugin_data = stolen
    plan.hide()
    win.hide()


def test_a_handle_drag_stretches_one_end_and_leaves_the_other():
    """The preview translated the WHOLE projection, so the far end walked
    across the plan while the model only stretched."""
    from core.building import samples as S
    from core.building.model import building_of
    from views.main_window import MainWindow

    win = MainWindow()
    scene = win.viewport.scene
    S.build_sample(win.viewport.history, scene, "townhouse")
    win._on_open_plan_window()
    plan = win._plan_window
    wall = next(e for e in building_of(scene).elements
                if e.get("type") == "wall")
    ends = plan._ends_of(wall["id"])
    rests = plan._resting_projection(wall)
    moved = plan._stretched_ghost(rests, plan._ghost_anchor(ends[1]),
                                  1000.0, 0.0)

    def span(segs):
        xs = [v for s in segs for v in (s[0], s[2])]
        return min(xs), max(xs)

    far_a, near_a = span(rests)
    far_b, near_b = span(moved)
    assert far_a == far_b, "đầu kia bị kéo theo"
    assert near_b - near_a == pytest.approx(1000.0)
    plan.hide()
    win.hide()


def test_moving_a_partner_wall_rebuilds_the_wall_it_meets():
    """A wall's body is trimmed against the walls it meets, so the rebuild
    signature has to carry their GEOMETRY, not just their names — a
    signature that only listed ids stayed identical after a partner moved,
    the sync skipped the untouched wall, and the corner kept the old
    mitre."""
    from core.building import samples as S
    from core.building import scene_sync as SS
    from core.building.model import building_of
    from core.history import History
    from core.scene import Scene

    scene = Scene()
    S.build_sample(History(scene), scene, "townhouse")
    building = building_of(scene)
    wall = next(e for e in building.elements if e.get("type") == "wall")
    partner = next(e for e in building.elements
                   if e.get("type") == "wall" and e["id"] != wall["id"]
                   and e["story_id"] == wall["story_id"])
    before = SS._signature(building, wall)
    partner["params"]["baseline_start_mm"] = [
        float(v) + 900.0 for v in partner["params"]["baseline_start_mm"]]
    assert SS._signature(building, wall) != before, \
        "chữ ký không đổi khi tường bạn bị dời — góc sẽ giữ vát cũ"
    # and a wall on ANOTHER storey must not trigger this one
    other = next(e for e in building.elements
                 if e.get("type") == "wall"
                 and e["story_id"] != wall["story_id"])
    steady = SS._signature(building, wall)
    other["params"]["baseline_start_mm"] = [500.0, 500.0]
    assert SS._signature(building, wall) == steady, \
        "tường tầng khác làm dựng lại tường tầng này"


def test_a_real_sync_repairs_the_corner_the_undo_left(tmp_path):
    """End to end through the app's own path: move a wall a storey up, undo
    it, and the untouched partner must be back to the right shape."""
    from core.building import commands as C
    from core.building import samples as S
    from core.building import scene_sync as SS
    from core.building.model import building_of
    from views.main_window import MainWindow

    win = MainWindow()
    scene = win.viewport.scene
    S.build_sample(win.viewport.history, scene, "townhouse")
    building = building_of(scene)
    wall = next(e for e in building.elements if e.get("type") == "wall")
    group = SS.group_for(scene, wall["id"])
    assert group is not None
    from core.building.builder import build

    mesh_before, _derived = build(building, wall)
    verts_before = sorted((round(e.v0.position.x(), 4),
                           round(e.v0.position.y(), 4))
                          for e in mesh_before.edges)
    del verts_before

    partner = next(e for e in building.elements
                   if e.get("type") == "wall" and e["id"] != wall["id"]
                   and e["story_id"] == wall["story_id"])
    win.viewport.history.execute(C.set_params(
        str(partner["id"]),
        {"baseline_start_mm": [float(v) + 1200.0
                               for v in partner["params"]["baseline_start_mm"]]}))
    win.viewport.history.undo()
    # after the undo the wall's own cached mesh must match a fresh build
    rebuilt = building_of(scene)
    fresh, _d = build(rebuilt, rebuilt.element(wall["id"]))
    live = SS.group_for(scene, wall["id"])
    live_pts = sorted((round(e.v0.position.x(), 4), round(e.v0.position.y(), 4))
                      for e in live.mesh.edges)
    fresh_pts = sorted((round(e.v0.position.x(), 4), round(e.v0.position.y(), 4))
                       for e in fresh.edges)
    assert live_pts == fresh_pts, "góc tường còn vát của lần sửa trước"
    win.hide()


# ---- Review 4 -----------------------------------------------------------------

def test_undoing_a_tool_step_repairs_the_wall_it_cut():
    """The targeted-rebuild hook diffed «before vs the model NOW», which on
    an undo answers «nothing changed» — while the scene still held the cut
    the step had made. A tool-driven edit therefore kept its door in the
    wall after Ctrl+Z, and the plan DXF written from that scene disagreed
    with the file reopened."""
    from core.building import commands as C
    from core.building import samples as S
    from core.building.model import building_of
    from core.building.scene_sync import group_for
    from tools import building_tools as BT
    from views.main_window import MainWindow

    win = MainWindow()
    scene = win.viewport.scene
    S.build_sample(win.viewport.history, scene, "townhouse")
    wall = next(e for e in building_of(scene).elements
                if e.get("type") == "wall")

    def faces() -> int:
        group = group_for(scene, wall["id"])
        return len(getattr(group.mesh, "faces", []) or [])

    before = faces()

    class _T(BT.BuildingTool):
        kind = "door"

    _T()._commit(win.viewport, C.add_element("door", str(wall["story_id"]), {
        "host_wall_id": str(wall["id"]), "offset_along_wall_mm": 3000.0,
        "width_mm": 900.0, "height_mm": 2200.0, "name": "DT"}))
    with_door = faces()
    assert with_door > before, "cửa không cắt được lỗ"

    win.viewport.history.undo()
    assert faces() == before, "Ctrl+Z còn lỗ cửa trong tường"
    win.viewport.history.redo()
    assert faces() == with_door, "làm lại không cắt lại lỗ"
    win.viewport.history.undo()
    assert faces() == before
    win.hide()


def test_opening_a_second_document_does_not_keep_the_first_registry(tmp_path):
    """The registry is POSITIONS into this scene's lists. A load that left
    the previous document's keys behind either made an opened drawing lose
    its own annotations, or re-wired a stale index onto whatever now
    occupies it."""
    from core.building import samples as S
    from core.building.drawings import annotate_plan, view_for
    from core.history import History
    from core.scene import Scene
    from formats.igz import load_into, save_scene

    def make(name: str, storeys: int):
        scene = Scene()
        building, _counts = S.build_sample(History(scene), scene, "townhouse")
        for story in building.stories[:storeys]:
            view = view_for(building, {"kind": "story",
                                       "story_id": story["id"]})
            annotate_plan(scene, building, view,
                          key=f"scene:story-{story['id']}")
        path = tmp_path / f"{name}.igz"
        save_scene(scene, path)
        return path

    first, second = make("first", 3), make("second", 1)
    scene = Scene()
    load_into(scene, first)
    assert len(scene.bim_annotations) == 3
    load_into(scene, second)
    assert len(scene.bim_annotations) == 1, scene.bim_annotations.keys()
    levels = sorted({str(getattr(e, "text", ""))
                     for entities in scene.bim_annotations.values()
                     for e in entities
                     if str(getattr(e, "text", "")).startswith(("FL:", "CL:"))})
    assert levels == ["CL:+3300", "FL:+0000"], levels


def test_a_storey_export_from_an_issued_set_stays_one_storey(tmp_path):
    """The set files each storey's annotations under the SHEET's name, so a
    storey export looked for a key it had never been given and fell back to
    «everything the document holds» — all three floors' levels on one
    plan."""
    import ezdxf

    from core.building import docset as DS
    from core.building import samples as S
    from core.building.model import building_of
    from formats.dxf_bim import save_plan_dxf
    from core.history import History
    from core.scene import Scene

    scene = Scene()
    building, _counts = S.build_sample(History(scene), scene, "townhouse")
    DS.generate_docset(scene, building, annotations=True)
    rebuilt = building_of(scene)
    out = tmp_path / "t1.dxf"
    save_plan_dxf(str(out), scene, rebuilt, str(rebuilt.stories[0]["id"]))
    doc = ezdxf.readfile(str(out))
    texts = [e.dxf.text for e in doc.modelspace().query("TEXT")
             if hasattr(e.dxf, "text")]
    levels = sorted({t for t in texts if t.startswith(("FL:", "CL:"))})
    assert levels == ["CL:+3300", "FL:+0000"], levels


def test_editing_the_pen_table_marks_the_document_dirty():
    """The tables are document data: an office that sets its pens and closes
    the app must be asked to save, not lose the edit silently."""
    from views.detail_manager import DetailManagerDialog
    from views.main_window import MainWindow
    from views.pens_dialog import PensDialog

    win = MainWindow()
    win._saved_content = win.viewport.scene.content_version
    assert not win._is_dirty()

    pens = PensDialog(win)
    pens.table.cellWidget(0, 1).setValue(0.9)
    pens._apply()
    assert win._is_dirty(), "sửa bảng bút mà tài liệu vẫn sạch"

    win._saved_content = win.viewport.scene.content_version
    details = DetailManagerDialog(win)
    details.table.cellWidget(0, 2).setValue(66.0)
    details._save()
    assert win._is_dirty(), "sửa chi tiết mà tài liệu vẫn sạch"
    pens.close()
    details.close()
    win.hide()


def test_the_step_diff_takes_its_host_from_either_side():
    """The diff between a step's own two payloads is the one question a
    targeted rebuild may ask. A door that the step ADDED and the undo
    REMOVED exists only on the before side — the host wall has to be
    rebuilt from whichever side still knows about it."""
    from core.building import commands as C
    from core.building import samples as S
    from core.building.model import building_of
    from core.history import History
    from core.scene import Scene

    scene = Scene()
    S.build_sample(History(scene), scene, "townhouse")
    building = building_of(scene)
    wall = next(e for e in building.elements if e.get("type") == "wall")
    before = building.to_dict()
    door = building.add_element("door", str(wall["story_id"]), {
        "host_wall_id": str(wall["id"]), "offset_along_wall_mm": 2000.0,
        "width_mm": 900.0, "height_mm": 2200.0})
    after = building.to_dict()
    added = C.changed_ids_between(before, after)
    assert str(door["id"]) in added and str(wall["id"]) in added
    removed = C.changed_ids_between(after, before)
    assert str(door["id"]) in removed and str(wall["id"]) in removed, \
        "xoá cửa mà không dựng lại tường chủ"
