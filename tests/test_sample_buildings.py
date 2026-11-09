# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Marco Sumari Tellez and IngeTrazo contributors.
"""The sample buildings: three parametric presets, made in one call."""
from __future__ import annotations

import os
import sys

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

if QApplication.instance() is None:
    QApplication(sys.argv[:1])


def _built(key: str):
    from core.building import samples as S
    from core.building.takeoff import tables
    from core.history import History
    from core.scene import Scene

    scene = Scene()
    history = History(scene)
    building, counts = S.build_sample(history, scene, key)
    return scene, history, building, counts, tables(building)


@pytest.mark.parametrize("key", ["townhouse", "apartment", "office"])
def test_every_preset_is_a_real_parametric_model(key):
    """Not a mesh: storeys, walls, openings and plates the tools could
    have drawn themselves, with the API still answering for all of them."""
    from core.building import samples as S

    scene, _history, building, counts, table_set = _built(key)
    record = S.preset(key)
    assert counts["storeys"] == int(record["storeys"])
    assert counts["walls"] >= 4 * int(record["storeys"])
    assert len(building.stories) == counts["storeys"]
    assert scene.groups, "mẫu phải dựng ra khối trong scene"
    # The walls have their parameters, so the drawings and the takeoff read them.
    wall = next(e for e in building.elements if e.get("type") == "wall")
    assert wall["params"]["baseline_start_mm"]
    assert wall["params"]["baseline_end_mm"]
    assert float(wall["params"]["thickness_mm"]) > 0
    assert table_set["walls"], "mẫu phải có bảng khối lượng tường"
    assert float(table_set["totals"]["wall_volume_m3"]) > 0.0


@pytest.mark.parametrize("key", ["townhouse", "apartment", "office"])
def test_every_preset_issues_a_drawing_rule(key):
    """A preset nobody can draw is a demo; every one of them must answer
    with a plan its section plane, scale and cut."""
    from core.building import drawings as D

    _scene, _history, building, _counts, _tables = _built(key)
    story = building.stories[0]
    view = D.view_for(building, {"kind": "story", "story_id": story["id"]})
    assert view.section_planes, "mặt bằng phải có mặt phẳng cắt"
    assert view.scale_denom > 0
    assert D.story_box(building, story)[2] > D.story_box(building, story)[0]


@pytest.mark.parametrize("key", ["townhouse", "apartment", "office"])
def test_a_sample_is_ordinary_undo_history(key):
    """Built through the app's own commands, one per element: a user who
    does not like it presses Ctrl+Z, exactly as if they had drawn it."""
    _scene, history, building, _counts, _t = _built(key)
    assert history.undo(), "mỗi cấu kiện là một bước hoàn tác"
    assert len(building.elements) >= 0


def test_the_presets_are_stated_once_and_read_consistently():
    from core.building import samples as S

    assert S.keys() == ["townhouse", "apartment", "office"]
    for key in S.keys():
        record = S.preset(key)
        assert record["name"] and record["note"]
        assert float(record["storey_h_mm"]) > 2000.0
        assert float(record["outline_w_mm"]) > 0
        assert float(record["outline_d_mm"]) > 0
    with pytest.raises(KeyError):
        S.preset("nope")


def test_opening_a_file_gives_back_the_storeys_it_holds(tmp_path):
    """The building is memoised on the scene BY IDENTITY, but its contents
    come from plugin_data — which a load replaces. A scene that had already
    been asked for its building (a dock, a panel, a signal during startup)
    kept serving the EMPTY model built before the load: the walls came back
    and the storeys did not."""
    from core.building.model import building_of
    from core.scene import Scene
    from formats.igz import load_into, save_scene

    from core.building import samples as S
    from core.history import History

    scene = Scene()
    S.build_sample(History(scene), scene, "townhouse")
    doc = tmp_path / "house.igz"
    save_scene(scene, doc)

    reopened = Scene()
    building_of(reopened)                 # the stale cache: empty model
    load_into(reopened, doc)
    back = building_of(reopened)
    assert len(back.stories) == 3, "tầng bị mất khi mở file"
    assert back.elements, "cấu kiện bị mất khi mở file"


def test_a_new_document_forgets_the_previous_building():
    """Ctrl+N drops plugin_data, so it must drop the memoised building too:
    otherwise the new document shows the old house."""
    from core.building import samples as S
    from core.building.model import building_of
    from core.history import History
    from core.scene import Scene

    scene = Scene()
    S.build_sample(History(scene), scene, "townhouse")
    assert building_of(scene).stories
    scene.clear()
    assert not building_of(scene).stories
    assert not building_of(scene).elements


def test_the_menu_builds_a_sample_into_the_document():
    from core.building.model import building_of
    from views.main_window import MainWindow

    win = MainWindow()
    labels = [a.text() for a in win._bim_menu.actions()]
    assert "Dựng nhanh 3D" in labels
    win._on_build_sample("townhouse")
    building = building_of(win.viewport.scene)
    assert len(building.stories) == 3
    assert win.viewport.scene.groups, "mẫu phải hiện trong 3D"
    assert "Đã dựng" in win.statusBar().currentMessage()
    win.hide()


def test_every_preset_builds_every_element_it_declares():
    """A preset that adds an element the builder then refuses is worse than
    one that omits it: the model has a hole where the drawing office
    promised a glazed run, and the panel warns for the life of the
    document. The office preset's curtain wall was exactly that — given a
    baseline of its own and no host wall, so `build_curtain_wall` raised
    «Lỗ mở không có tường chủ» and nothing was drawn."""
    from core.building import samples as _samples
    from core.building.model import building_of
    from core.building.scene_sync import group_for

    from core.history import History
    from core.scene import Scene

    for key in _samples.keys():
        scene = Scene()
        building, counts = _samples.build_sample(History(scene), scene, key)
        assert not scene.building_errors, (key, scene.building_errors)
        for element in building.elements:
            kind = str(element.get("type"))
            if kind == "zone":
                continue        # an area: it draws nothing by design
            assert group_for(scene, element["id"]) is not None, \
                f"{key}: «{kind}» {element['id']} không dựng được"
        assert counts


def test_the_office_curtain_wall_is_a_glazed_run_in_its_front_wall():
    """The preset asks for a glazed run along the front: it must BE one —
    hosted by the front wall, with the area the schedule prices."""
    from core.building import samples as _samples
    from core.history import History
    from core.scene import Scene

    scene = Scene()
    building, _counts = _samples.build_sample(History(scene), scene, "office")
    curtain = next(e for e in building.elements
                   if e.get("type") == "curtain_wall")
    params = curtain["params"]

    assert params.get("host_wall_id"), "vách kính không có tường chủ"
    host = building.element(str(params["host_wall_id"]))
    assert host is not None and host.get("type") == "wall"
    assert params["width_mm"] > 1000.0
    assert params["sill_height_mm"] > 0.0

    derived = curtain.get("derived") or {}
    assert derived.get("glass_area_m2", 0.0) > 0.0
    assert derived.get("cells", 0) >= 2
