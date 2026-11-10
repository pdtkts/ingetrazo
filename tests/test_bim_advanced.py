# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Marco Sumari Tellez and IngeTrazo contributors.
"""Nâng cao: the maintenance a long job needs.

Three of these are about the document (rebuild it, hold off rebuilding it,
say what it costs), and one is about a file that has already LEFT the
application — the only place an export fault is visible at all.
"""
import sys

import pytest  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

if QApplication.instance() is None:
    QApplication(sys.argv[:1])


@pytest.fixture()
def window():
    from views.main_window import MainWindow

    win = MainWindow()
    yield win
    from core.building import scene_sync

    scene_sync.set_paused(False)         # never leak the switch to a test
    win.hide()


def _built(window) -> int:
    from core.building import samples as _samples

    _building, counts = _samples.build_sample(
        window.viewport.history, window.viewport.scene, "townhouse")
    return sum(int(v) for v in counts.values() if isinstance(v, int))


def test_rebuilding_regenerates_every_element_from_its_parameters(window):
    """Dựng lại is the answer to «the corner is not joined» and to «the
    picture disagrees with the numbers»: it must build the geometry again
    from the parameters, changing no parameter."""
    from core.building import scene_sync
    from core.building.model import building_of

    _built(window)
    building = building_of(window.viewport.scene)
    before = building.to_dict()["elements"]

    built = scene_sync.rebuild_all(window.viewport.scene, building)

    assert built > 0
    assert building_of(
        window.viewport.scene).to_dict()["elements"] == before


def test_pausing_holds_the_geometry_and_releasing_catches_up(window):
    """The pause is only honest if the model CANNOT drift: every path that
    rebuilds asks the same switch, so a release rebuilds whatever was
    edited while it was held."""
    from core.building import commands as _commands
    from core.building import scene_sync
    from core.building.model import building_of
    from core.building.scene_sync import group_for

    _built(window)
    scene = window.viewport.scene
    building = building_of(scene)
    story = building.stories[0]
    wall = next(e for e in building.elements if e.get("type") == "wall")

    def span():
        """The wall's own geometry, as its vertex positions. A thickness
        change MOVES vertices — it does not add or remove any — so the
        count would call a rebuild a no-op and the positions cannot."""
        mesh = group_for(scene, wall["id"]).mesh
        return sorted((round(float(v.position.x()), 5),
                       round(float(v.position.y()), 5),
                       round(float(v.position.z()), 5))
                      for v in mesh.vertices)

    scene_sync.set_paused(True)
    try:
        command = _commands.set_params(
            str(wall["id"]), {"thickness_mm": 300.0})
        held = span()
        window.viewport.history.execute(command)
        assert building_of(scene).element(
            str(wall["id"]))["params"]["thickness_mm"] == 300.0
        assert span() == held, "tạm dừng mà hình vẫn dựng lại"
    finally:
        scene_sync.set_paused(False)

    # The release path rebuilds; the wall now shows its new thickness.
    scene_sync.rebuild_all(scene, building_of(scene))
    assert span() != held, "bật lại mà hình không dựng theo tham số mới"
    assert str(story["id"])


def test_the_pause_is_a_session_state_not_document_data(window, tmp_path):
    """A file saved mid-insertion must open working for the next person:
    the switch belongs to this session, never to the .igz."""
    from core.building import scene_sync
    from core.scene import Scene
    from formats.igz import load_into, save_scene

    _built(window)
    path = tmp_path / "paused.igz"
    scene_sync.set_paused(True)
    try:
        save_scene(window.viewport.scene, path)
    finally:
        scene_sync.set_paused(False)

    assert not scene_sync.paused(), "cờ tạm dừng rò rỉ sang phiên khác"
    reopened = Scene()
    load_into(reopened, path)
    assert not scene_sync.paused(), "file mở ra lại đang tạm dừng"


def test_the_lag_measure_reports_numbers_for_the_live_model(window):
    """What the user asks mid-job is «is MY file the problem», so the
    numbers must come from the open document — elements, faces, and the
    time a rebuild costs it."""
    import time

    from core.building import scene_sync
    from core.building.model import building_of

    _built(window)
    scene = window.viewport.scene
    building = building_of(scene)

    t0 = time.perf_counter()
    scene_sync.sync(scene, building, force=True)
    elapsed = time.perf_counter() - t0

    faces = sum(len(getattr(g.mesh, "faces", ()) or ())
                for g in scene.groups)
    assert len(building.elements) > 0
    assert faces > 0
    assert elapsed < 120.0, f"dựng lại quá chậm: {elapsed:.1f}s"


def test_the_dxf_check_passes_a_faithful_export(window, tmp_path):
    """A file the exporter wrote from this model must come back clean —
    otherwise the check cries wolf and the office stops reading it."""
    from core.building import drawings as _drawings
    from core.building import pens as _pens
    from core.building.model import building_of
    from formats.dxf_bim import save_plan_dxf
    from formats.dxf_check import check_dxf_against

    _built(window)
    scene = window.viewport.scene
    building = building_of(scene)
    story = building.stories[0]
    view = _drawings.view_for(
        building, {"kind": "story", "story_id": str(story["id"])})
    view.annotation_key = f"dxf:{story['id']}"
    _drawings.annotate_plan(scene, building, view, key=view.annotation_key)
    pen_table, layer_map = _pens.export_tables(scene)

    out = tmp_path / "faithful.dxf"
    save_plan_dxf(str(out), scene, building, str(story["id"]),
                  annotation_key=view.annotation_key,
                  pens=pen_table, layer_map=layer_map)
    report = check_dxf_against(str(out), scene, building)

    assert report["counts"]["lines"] > 0
    assert report["counts"]["hatch"] > 0, "bản vẽ không có hatch mặt cắt"
    assert report["problems"] == [], report["problems"]


def test_the_dxf_check_catches_a_rename_that_never_reached_the_file(
        window, tmp_path):
    """The failure this exists for: the office renames a layer in the
    dialog, the exporter is called without the map, and the file goes out
    carrying the raw name — invisible until another CAD opens it."""
    from core.building import drawings as _drawings
    from core.building import pens as _pens
    from core.building.model import building_of
    from formats.dxf_bim import save_plan_dxf
    from formats.dxf_check import check_dxf_against

    _built(window)
    scene = window.viewport.scene
    building = building_of(scene)
    story = building.stories[0]
    view = _drawings.view_for(
        building, {"kind": "story", "story_id": str(story["id"])})
    view.annotation_key = f"dxf:{story['id']}"
    _drawings.annotate_plan(scene, building, view, key=view.annotation_key)
    _pens.renames(scene)["KT-CUT"] = "A-WALL"

    out = tmp_path / "stale.dxf"
    save_plan_dxf(str(out), scene, building, str(story["id"]),
                  annotation_key=view.annotation_key)      # no layer_map
    report = check_dxf_against(str(out), scene, building)

    assert any("KT-CUT" in p and "A-WALL" in p for p in report["problems"]), \
        report["problems"]


# ---- Window ▸ Toolbars ---------------------------------------------------

def test_every_toolbar_can_be_hidden_and_found_again(window):
    """A bar that went missing was only recoverable by right-clicking the
    empty space where it used to be — which a user who hid it cannot see.
    The menu lists them all and says the way back."""
    menu = window._toolbars_menu
    window._fill_toolbars_menu(menu)
    labels = {a.text() for a in menu.actions() if a.text()}
    assert "BIM" in labels, labels
    assert any("thanh công cụ" in label for label in labels), labels

    bar = window.toolbars["bim"]
    bar.setVisible(False)
    assert bar.isHidden()
    window._show_all_toolbars()
    assert not bar.isHidden(), "thanh BIM không bật lại được"


def test_the_toolbar_list_is_built_when_it_opens(window):
    """Extensions add bars AFTER the menus are made, so a list frozen at
    start-up would never show them — and those are exactly the bars a user
    has no other way to turn off."""
    menu = window._toolbars_menu
    window._fill_toolbars_menu(menu)
    before = {a.text() for a in menu.actions() if a.text()}

    from PySide6.QtWidgets import QToolBar

    extra = QToolBar("Thanh của tiện ích", window)
    window.addToolBar(extra)
    window.toolbars["plugin_demo"] = extra
    window._fill_toolbars_menu(menu)
    after = {a.text() for a in menu.actions() if a.text()}

    assert "Thanh của tiện ích" in after - before
    extra.setVisible(False)
    window._show_all_toolbars()
    assert not extra.isHidden()


def test_the_softening_angle_smooths_and_sharpens_by_the_dihedral(window):
    """«Góc làm mềm cạnh»: a shallow dihedral reads as ONE surface and its
    edge is not drawn, a real corner is. The angle is the user's own, and
    undo puts every edge back exactly — including the difference between
    «soft on purpose» and «soft because the angle was shallow»."""
    from core.history import SoftenEdgesCommand

    scene, history = window.viewport.scene, window.viewport.history
    from core.building import samples as _samples

    _samples.build_sample(history, scene, "townhouse")
    group = next(g for g in scene.groups
                 if getattr(g, "mesh", None) and len(g.mesh.faces) > 3)
    edges = [e for e in group.mesh.edges
             if len(getattr(e, "faces", ()) or ()) == 2]
    assert edges, "mô hình mẫu không có cạnh nào giữa hai mặt"
    before = [bool(e.soft) for e in edges]

    # 179°: essentially every two-faced edge is within the angle.
    wide = SoftenEdgesCommand(179.0)
    history.execute(wide)
    assert wide._before, "không cạnh nào đổi ở góc 179°"
    assert all(e.soft for e in edges)

    history.undo()
    assert [bool(e.soft) for e in edges] == before, \
        "Ctrl+Z không trả lại đúng trạng thái cạnh"

    # 0°: nothing is shallower than zero, so every edge becomes a crease.
    sharp = SoftenEdgesCommand(0.0)
    history.execute(sharp)
    assert not any(e.soft for e in edges)
    history.undo()
    assert [bool(e.soft) for e in edges] == before

    # …and a redo/undo cycle is stable, so the command is not one-way.
    history.redo()
    assert not any(e.soft for e in edges)
    history.undo()
    assert [bool(e.soft) for e in edges] == before
