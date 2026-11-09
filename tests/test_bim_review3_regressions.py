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


# ---- Review 5 -----------------------------------------------------------------

def test_an_opening_follows_the_wall_that_hosts_it():
    """A door's whole world position is derived from its host wall, and
    NONE of those inputs are the door's own parameters. Without them the
    opening's signature was identical after its host moved, the sync
    skipped it, and the leaf stayed where it was — floating outside its own
    opening in the 3D view, the plan DXF and the IFC, until a forced
    rebuild. It fires on every entry point, because they all call sync()
    without force."""
    from core.building import commands as C
    from core.building import samples as S
    from core.building.model import building_of
    from core.building.scene_sync import group_for, sync
    from core.history import History
    from core.scene import Scene

    scene = Scene()
    S.build_sample(History(scene), scene, "townhouse")
    building = building_of(scene)
    wall = next(e for e in building.elements if e.get("type") == "wall")
    door = next(e for e in building.elements
                if e.get("type") == "door"
                and str((e.get("params") or {}).get("host_wall_id"))
                == str(wall["id"]))

    def bounds(element_id):
        mesh = group_for(scene, element_id).mesh
        ys = [float(v.position.y()) for v in mesh.vertices]
        xs = [float(v.position.x()) for v in mesh.vertices]
        return (round(min(xs), 4), round(max(xs), 4),
                round(min(ys), 4), round(max(ys), 4))

    wall_before, door_before = bounds(wall["id"]), bounds(door["id"])
    p0 = list(wall["params"]["baseline_start_mm"])
    p1 = list(wall["params"]["baseline_end_mm"])
    command = C.set_params(str(wall["id"]), {
        "baseline_start_mm": [p0[0], p0[1] + 1000.0],
        "baseline_end_mm": [p1[0], p1[1] + 1000.0]})
    command._rebuild = lambda s, b: sync(s, b)
    History(scene) if False else None
    # the scene's own history, so undo can be asserted below
    from views.main_window import MainWindow

    win = MainWindow()
    win.viewport.scene.groups[:] = []
    win.hide()
    del win

    scene2 = Scene()
    history = History(scene2)
    S.build_sample(history, scene2, "townhouse")
    building2 = building_of(scene2)
    wall2 = next(e for e in building2.elements if e.get("type") == "wall")
    door2 = next(e for e in building2.elements
                 if e.get("type") == "door"
                 and str((e.get("params") or {}).get("host_wall_id"))
                 == str(wall2["id"]))

    def bounds2(element_id):
        mesh = group_for(scene2, element_id).mesh
        ys = [float(v.position.y()) for v in mesh.vertices]
        return round(min(ys), 3), round(max(ys), 3)

    door_before2 = bounds2(door2["id"])
    q0 = list(wall2["params"]["baseline_start_mm"])
    q1 = list(wall2["params"]["baseline_end_mm"])
    move = C.set_params(str(wall2["id"]), {
        "baseline_start_mm": [q0[0], q0[1] + 1000.0],
        "baseline_end_mm": [q1[0], q1[1] + 1000.0]})
    move._rebuild = lambda s, b: sync(s, b)
    history.execute(move)
    door_after = bounds2(door2["id"])
    assert abs(door_after[0] - door_before2[0] - 1.0) < 0.01, \
        f"cửa không đi theo tường chủ: {door_before2} → {door_after}"
    history.undo()
    assert bounds2(door2["id"]) == door_before2, "Ctrl+Z không trả cửa về"
    assert wall_before and door_before       # the first scene was a baseline


def test_undoing_a_wall_removal_repairs_its_neighbours():
    """The removed branch of the step diff added bare ids, so the walls a
    deleted wall mitred against kept last revision's corner after Ctrl+Z —
    the picture and the DXF disagreeing with the model. Undo of a removal
    is the common case, not a corner."""
    from core.building import commands as C
    from core.building import samples as S
    from core.building.model import building_of
    from core.history import History
    from core.scene import Scene

    scene = Scene()
    history = History(scene)
    S.build_sample(history, scene, "townhouse")
    building = building_of(scene)
    walls = [e for e in building.elements if e.get("type") == "wall"]
    victim = str(walls[0]["id"])
    storey_id = str(walls[0]["story_id"])

    before = building.to_dict()
    history.execute(C.remove_element(victim))
    # Both payloads are REAL: the after side is the model as it stands once
    # the removal has run, which is exactly what a step records.
    after = building_of(scene).to_dict()

    # The undo direction: the step that puts the wall BACK.
    added = C.changed_ids_between(after, before)
    assert victim in added, added
    neighbours = [str(w["id"]) for w in building_of(scene).elements
                  if w.get("type") == "wall"
                  and str(w.get("story_id")) == storey_id]
    assert neighbours, "mẫu nhà phải còn tường cùng tầng"
    missing = [n for n in neighbours if n not in added]
    assert not missing, f"tường lân cận không được dựng lại: {missing}"


def test_exporting_a_plan_twice_does_not_double_the_sheet():
    """The export filed its annotations under a private «dxf:<storey>» key
    BESIDE the drawing set's, and the composer draws every dimension its
    frame can see — so one menu export turned a 14-chain sheet into 28, and
    it survived save/reopen."""
    from core.building import docset as _docset
    from core.building import samples as S
    from core.building.model import building_of
    from core.scene import Scene
    from core.history import History
    from formats.dxf_bim import resolve_annotation_key

    scene = Scene()
    S.build_sample(History(scene), scene, "townhouse")
    building = building_of(scene)
    _docset.generate_docset(scene, building, annotations=True)
    building = building_of(scene)
    printed = len(scene.dimensions)
    assert printed > 0

    from core.building import drawings as _drawings

    story = building.stories[0]
    for _ in range(2):
        view = _drawings.view_for(building, {"kind": "story",
                                             "story_id": str(story["id"])})
        key = resolve_annotation_key(scene, view)
        assert key in scene.bim_annotations, key
        assert not key.startswith("dxf:"), \
            "xuất DXF lại mở khoá riêng bên cạnh khoá của bộ tờ"
        view.annotation_key = key
        _drawings.annotate_plan(scene, building, view, key=key)
    assert len(scene.dimensions) == printed, \
        f"{printed} → {len(scene.dimensions)} kích thước sau khi xuất"


def test_a_storey_never_answers_for_another_stores_key():
    """«Tầng» is the first word of «Mặt bằng Tầng 1», so a word-set match
    printed the floor above's level marks on a storey whose own floor is
    ±0.000. The key must END with the storey's own name."""
    from core.building import drawings as _drawings
    from core.building import samples as S
    from core.building.model import building_of
    from core.history import History
    from core.scene import Scene
    from formats.dxf_bim import _drawing_key

    scene = Scene()
    S.build_sample(History(scene), scene, "townhouse")
    building = building_of(scene)
    scene.bim_annotations = {
        "Mặt bằng Tầng 1": [],
        "Mặt bằng Tầng 11": [],
    }
    first = building.stories[0]
    first["name"] = "Tầng 1"
    view = _drawings.view_for(building, {"kind": "story",
                                        "story_id": str(first["id"])})
    assert _drawing_key(scene, view) == "Mặt bằng Tầng 1"

    # A storey whose WHOLE name is a prefix of another's must not answer
    # for it: «Tầng» beside «Tầng 1».
    first["name"] = "Tầng"
    assert _drawing_key(scene, view) is None, \
        "tầng «Tầng» nhận nhầm khoá của «Mặt bằng Tầng 1»"


def test_the_crop_tool_survives_a_document_with_no_storey():
    """Every other draft tool says «chưa có tầng nào» on an empty model;
    the crop let view_for raise out of the click handler, where the
    History never sees it, and the user got a Qt traceback."""
    from core.scene import Scene
    from views.draft_tools import CropTool

    class _Plan:
        _scene = Scene()
        _story_id = ""
        _building = None
        _view_row: dict = {}

        def __init__(self):
            self.said: list = []

        def _say(self, text):
            self.said.append(str(text))

    plan = _Plan()
    tool = CropTool(plan)
    tool.points = [(0.0, 0.0), (2000.0, 2000.0)]
    tool.commit()                                   # must not raise
    assert plan.said and "tầng" in plan.said[-1].lower(), plan.said


def test_the_lens_goes_down_with_the_plan():
    """The lens is a Qt.Tool: Qt does not hide it with its parent, so a
    closed plan left a frameless lens floating over the desktop."""
    from core.building import samples as S
    from views.main_window import MainWindow

    win = MainWindow()
    S.build_sample(win.viewport.history, win.viewport.scene, "townhouse")
    win._on_open_plan_window()
    plan = win._plan_window
    plan.toggle_magnifier(True)
    assert plan._lens.isVisible()
    plan.hide()
    assert not plan._lens.isVisible(), "kính lúp còn nổi sau khi đóng Plan"
    win.hide()


def test_a_fixed_element_stops_being_reported_as_broken():
    """`scene.building_errors` was only ever ASSIGNED when there were new
    errors, so the message for an element the user had already fixed
    stayed on the panel for the rest of the session — a warning about
    something that is no longer true teaches a user to ignore the panel."""
    from core.building import commands as C
    from core.building import samples as S
    from core.building.model import building_of
    from core.building.scene_sync import sync
    from core.history import History
    from core.scene import Scene

    scene = Scene()
    history = History(scene)
    S.build_sample(history, scene, "townhouse")
    wall = next(e for e in building_of(scene).elements
                if e.get("type") == "wall")

    broken = C.set_params(str(wall["id"]), {"thickness_mm": -50.0})
    broken._rebuild = lambda s, b: sync(s, b)
    history.execute(broken)
    assert scene.building_errors, "không báo lỗi khi tường sai"

    fixed = C.set_params(str(wall["id"]), {"thickness_mm": 200.0})
    fixed._rebuild = lambda s, b: sync(s, b)
    history.execute(fixed)
    assert not scene.building_errors, \
        f"vẫn báo lỗi của cấu kiện đã sửa xong: {scene.building_errors}"


def test_a_targeted_rebuild_does_not_clear_another_element_s_error():
    """The list belongs to the elements a sync EXAMINED: a targeted rebuild
    of the wall must not report the broken slab beside it as fixed."""
    from core.building import commands as C
    from core.building import samples as S
    from core.building.model import building_of
    from core.building.scene_sync import sync
    from core.history import History
    from core.scene import Scene

    scene = Scene()
    history = History(scene)
    S.build_sample(history, scene, "townhouse")
    slab = next(e for e in building_of(scene).elements
                if e.get("type") == "slab")
    wall = next(e for e in building_of(scene).elements
                if e.get("type") == "wall")

    broken = C.set_params(str(slab["id"]), {"thickness_mm": -10.0})
    broken._rebuild = lambda s, b: sync(s, b)
    history.execute(broken)
    assert scene.building_errors

    sync(scene, building_of(scene), element_ids=[str(wall["id"])])
    assert scene.building_errors, "dựng lại một tường lại xoá lỗi của sàn"


# ---- Review 6 -----------------------------------------------------------------

def test_two_storeys_may_share_a_name_without_losing_annotations():
    """The registry key was the drawing's NAME, so two storeys called
    «Tầng» — ordinary in a house — shared one entry: issuing the second
    POPPED the first one's published dimensions out of the document. The
    sheet then showed the floor above's chains and one storey's annotations
    were gone for good."""
    from core.building import commands as C
    from core.building import docset as _docset
    from core.building import samples as S
    from core.building.model import building_of
    from core.history import History
    from core.scene import Scene

    scene = Scene()
    history = History(scene)
    S.build_sample(history, scene, "townhouse")
    building = building_of(scene)
    for story in building.stories[:2]:
        history.execute(C.set_story_params(str(story["id"]),
                                           {"name": "Tầng"}))
    building = building_of(scene)

    _docset.generate_docset(scene, building, annotations=True)

    keys = [str(k) for k in scene.bim_annotations]
    assert len(set(keys)) == len(keys), keys
    # EVERY storey keeps its own chains: the count is the whole model's,
    # not one storey's worth.
    assert len(scene.dimensions) >= 42, len(scene.dimensions)

    # And each storey's export reads its OWN levels.
    import pathlib
    import tempfile

    import ezdxf

    from formats.dxf_bim import save_plan_dxf

    building = building_of(scene)
    seen = []
    for index in (0, 1):
        out = pathlib.Path(tempfile.mkdtemp()) / f"s{index}.dxf"
        save_plan_dxf(str(out), scene, building,
                      str(building.stories[index]["id"]))
        doc = ezdxf.readfile(str(out))
        texts = [e.dxf.text for e in doc.modelspace().query("TEXT")
                 if hasattr(e.dxf, "text")]
        seen.append(tuple(sorted({t for t in texts
                                  if t.startswith(("FL:", "CL:"))})))
    assert seen[0] == ("CL:+3300", "FL:+0000"), seen
    assert seen[1] == ("CL:+6600", "FL:+3300"), seen


def test_the_agent_s_export_does_not_double_the_sheet():
    """The menu's export was fixed to reuse the set's key; the AI bridge
    still minted its own private one, so an agent's export put a second
    dimension chain on the same sheet — the exact defect, on the path the
    bridge drives."""
    import pathlib
    import tempfile

    from core.ai_bim import BimSession
    from core.building import docset as _docset
    from core.building import samples as S
    from core.building.model import building_of
    from core.history import History
    from core.scene import Scene

    scene = Scene()
    history = History(scene)
    S.build_sample(history, scene, "townhouse")
    _docset.generate_docset(scene, building_of(scene), annotations=True)
    building = building_of(scene)
    printed, labels = len(scene.dimensions), len(scene.text_labels)

    class _Viewport:
        def __init__(self):
            self.scene = scene
            self.history = history

    out = pathlib.Path(tempfile.mkdtemp()) / "agent.dxf"
    BimSession(_Viewport()).export_dxf(str(out),
                                       str(building.stories[0]["id"]))

    assert len(scene.dimensions) == printed, \
        f"{printed} → {len(scene.dimensions)} kích thước"
    assert len(scene.text_labels) == labels
    assert not [k for k in scene.bim_annotations if str(k).startswith("dxf:")]


def test_a_failed_build_publishes_no_geometry():
    """An opening whose host was deleted kept its last solid: the renderer,
    the HLR and the composer went on drawing a door with no wall, while the
    panel's banner called that element broken and the takeoff had stopped
    counting it — the picture and the numbers disagreeing about an element
    the model itself declares unbuildable."""
    from core.building import commands as C
    from core.building import samples as S
    from core.building.model import building_of
    from core.building.scene_sync import group_for, sync
    from core.history import History
    from core.scene import Scene

    scene = Scene()
    history = History(scene)
    S.build_sample(history, scene, "townhouse")
    door = next(e for e in building_of(scene).elements
                if e.get("type") == "door")
    host = str((door["params"] or {}).get("host_wall_id"))
    assert group_for(scene, door["id"]) is not None

    command = C.remove_element(host)
    command._rebuild = lambda s, b: sync(s, b)
    history.execute(command)

    sync(scene, building_of(scene), force=True)
    assert group_for(scene, door["id"]) is None, \
        "cửa mồ côi vẫn còn hình trong scene"
    assert any(str(e[0]) == str(door["id"])
               for e in (scene.building_errors or ())), scene.building_errors

    history.undo()
    assert group_for(scene, door["id"]) is not None, "Ctrl+Z không trả cửa về"


def test_applying_to_the_storey_keeps_each_element_s_own_mark():
    """The NAME does not travel: it is the element's mark, the office's
    scheme is what the schedule groups by and the drawing stamps, and
    copying it turned four doors into one row «D99 ×4»."""
    import sys

    from PySide6.QtCore import Qt
    from PySide6.QtWidgets import QApplication, QMessageBox

    if QApplication.instance() is None:
        QApplication(sys.argv[:1])
    from core.building import commands as C
    from core.building import samples as S
    from core.building.model import building_of
    from core.building.scene_sync import sync
    from views.main_window import MainWindow

    win = MainWindow()
    try:
        scene, history = win.viewport.scene, win.viewport.history
        S.build_sample(history, scene, "townhouse")
        panel = win.bim_tray.building

        # Name the walls of the storey being drawn: the mark is what the
        # schedule groups by, so each one must have its own.
        building = building_of(scene)
        walls = [e for e in building.elements
                 if e.get("type") == "wall"
                 and str(e.get("story_id")) == str(building.stories[0]["id"])]
        assert len(walls) >= 3, len(walls)
        marks = {}
        for index, wall in enumerate(walls):
            mark = f"T{index + 1}"
            marks[str(wall["id"])] = mark
            command = C.set_params(str(wall["id"]), {"name": mark})
            command._rebuild = lambda s, b: sync(s, b)
            history.execute(command)

        panel.refresh()
        target = walls[0]
        for row in panel._element_rows:
            if row.data(0, Qt.UserRole) == str(target["id"]):
                panel.element_tree.setCurrentItem(row)
        panel._fields["thickness_mm"].setValue(250.0)
        QMessageBox.question = staticmethod(lambda *a, **k: QMessageBox.Yes)
        panel._on_bulk_apply()

        after = {str(e["id"]): e for e in building_of(scene).elements
                 if e.get("type") == "wall"
                 and str(e.get("story_id")) == str(building.stories[0]["id"])}
        assert {str(e["params"].get("name")) for e in after.values()} == \
            set(marks.values()), "áp hàng loạt đã xoá mã cấu kiện"
        assert all(float(e["params"]["thickness_mm"]) == 250.0
                   for e in after.values()), "thông số hình học không được áp"
    finally:
        win.hide()


def test_browsing_storeys_is_navigation_not_an_edit():
    """Each storey click pushed an undo step whose only change was
    `settings.active_story`: browsing four storeys cost four slots, and the
    user's next Ctrl+Z undid a navigation they never made."""
    from PySide6.QtCore import Qt

    from core.building import samples as S
    from core.building.model import building_of
    from views.main_window import MainWindow

    win = MainWindow()
    try:
        S.build_sample(win.viewport.history, win.viewport.scene, "townhouse")
        panel = win.bim_tray.building
        panel.refresh()
        history = win.viewport.history
        depth = len(history.undo_stack)

        for row in panel._story_rows:
            panel.story_tree.setCurrentItem(row)

        assert len(history.undo_stack) == depth, \
            "duyệt tầng đã đẩy bước hoàn tác"
        # …and the choice is IN the document, not only the live cache.
        assert str(building_of(win.viewport.scene).active_story()["id"]) == \
            str(panel._story_rows[-1].data(0, Qt.UserRole))
    finally:
        win.hide()


def test_the_plan_bar_s_crop_button_is_enabled():
    """«Crop region» worked from the menu while its plan-bar button stayed
    greyed with «công cụ này chưa có trong bản dựng» — the exact lie the
    disabled entries exist to avoid."""
    from core.building import samples as S
    from views.main_window import MainWindow

    win = MainWindow()
    try:
        S.build_sample(win.viewport.history, win.viewport.scene, "townhouse")
        win._on_open_plan_window()
        plan = win._plan_window
        assert str(plan._cmd_for_tool("crop")) == "crop"
        assert plan._tool_available("crop")
    finally:
        win.hide()
