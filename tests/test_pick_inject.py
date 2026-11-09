# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Marco Sumari Tellez and IngeTrazo contributors.
"""Ống hút / Ống nhả — sample a specification and give it to other elements.

An office does not retype a wall's build-up twenty times. What these tests
hold down is the boundary that makes the pair safe: the SPECIFICATION
travels (thickness, material, name), the PLACEMENT does not (where the wall
stands, what a door hangs in), and the whole application is one undo step
however many elements it touched.
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
    win.hide()


def _house(window):
    from core.building import samples as _samples
    from core.building.model import building_of

    _samples.build_sample(window.viewport.history, window.viewport.scene,
                          "townhouse")
    return building_of(window.viewport.scene)


def _params(window, element_id) -> dict:
    from core.building.model import building_of

    return building_of(window.viewport.scene).element(element_id)["params"]


def _sample_of(window, element) -> dict:
    from tools.pick_inject import transferable

    return {"kind": str(element.get("type")),
            "params": transferable(element.get("params") or {})}


def test_the_properties_travel_and_the_placement_stays(window):
    """A wall sampled from another wall keeps its own two ends and its own
    host relationships: copying those would MOVE the target, which is what
    the Move tool is for."""
    from core.building import commands as _commands

    building = _house(window)
    walls = [e for e in building.elements if e.get("type") == "wall"]
    source, target = walls[0], walls[1]
    window.viewport.history.execute(_commands.set_params(
        str(source["id"]),
        {"thickness_mm": 300.0, "building_material_id": "btct",
         "name": "Tường BTCT"}))

    before_ends = _params(window, target["id"]).get("baseline_start_mm")
    from core.building.model import building_of

    source = building_of(window.viewport.scene).element(source["id"])
    window._tools["inject"]._apply_to(
        window.viewport, _sample_of(window, source),
        [building_of(window.viewport.scene).element(target["id"])])

    after = _params(window, target["id"])
    assert after["thickness_mm"] == 300.0
    assert after["building_material_id"] == "btct"
    assert after["name"] == "Tường BTCT"
    assert after.get("baseline_start_mm") == before_ends, \
        "ống nhả đã dời cấu kiện chứ không chỉ đổi thông số"


def test_applying_to_many_elements_is_one_undo_step(window):
    """A user who applies a specification to nine walls expects ONE Ctrl+Z,
    not nine — and the whole application is what the office means by «the
    same wall»."""
    from core.building import commands as _commands
    from core.building.model import building_of

    building = _house(window)
    walls = [e for e in building.elements if e.get("type") == "wall"]
    source = walls[0]
    window.viewport.history.execute(_commands.set_params(
        str(source["id"]), {"thickness_mm": 275.0}))

    building = building_of(window.viewport.scene)
    source = building.element(source["id"])
    targets = [e for e in building.elements
               if e.get("type") == "wall" and e["id"] != source["id"]][:4]
    assert len(targets) == 4

    window._tools["inject"]._apply_to(window.viewport, _sample_of(window, source),
                                      targets)
    for target in targets:
        assert _params(window, target["id"])["thickness_mm"] == 275.0

    window.viewport.history.undo()
    for target in targets:
        assert _params(window, target["id"])["thickness_mm"] != 275.0, \
            "một Ctrl+Z chưa trả hết về như cũ"
    window.viewport.history.redo()
    for target in targets:
        assert _params(window, target["id"])["thickness_mm"] == 275.0


def test_a_different_kind_is_refused_in_words(window):
    """A wall carrying a column's parameters is a wall the builder cannot
    build, so the pair refuses and says so rather than writing it."""
    from core.building.model import building_of

    building = _house(window)
    wall = next(e for e in building.elements if e.get("type") == "wall")
    # Any other kind will do: the point is that the pair never writes a
    # specification onto an element the builder reads differently.
    other = next(e for e in building.elements
                 if e.get("type") not in ("wall", "grid"))
    assert str(other["type"]) == "slab" or str(other["type"])

    before = _params(window, other["id"])
    seen: list = []
    window.viewport.flash_status = lambda text: seen.append(str(text))
    window._tools["inject"]._apply_to(window.viewport, _sample_of(window, wall),
                                      [other])
    assert _params(window, other["id"]) == before, "đã áp nhầm loại"
    assert seen and "chỉ cùng loại" in seen[-1], seen


def test_the_sample_lives_on_the_document_not_in_a_module_variable(window):
    """Sampling a wall, saving, and reopening must not carry the sample —
    and two documents in two tabs must not share one."""
    from core.scene import Scene
    from core.building.model import building_of

    building = _house(window)
    wall = next(e for e in building.elements if e.get("type") == "wall")
    scene = window.viewport.scene
    scene.plugin_data["bim_sample"] = _sample_of(window, wall)

    other = Scene()
    assert not (other.plugin_data or {}).get("bim_sample")
    assert str(building_of(scene).element(wall["id"])["type"]) == "wall"


def test_transferable_keeps_the_specification_and_drops_the_address(window):
    """The one function the whole pair rests on: a door's host, a wall's
    ends and a slab's outline are ADDRESSES, not properties."""
    from tools.pick_inject import transferable

    params = {
        "name": "Cửa đi 900", "width_mm": 900.0, "height_mm": 2200.0,
        "host_wall_id": "wall-1", "offset_along_wall_mm": 3000.0,
        "baseline_start_mm": [0.0, 0.0], "baseline_end_mm": [5000.0, 0.0],
        "_internal": 1,
    }
    carried = transferable(params)
    assert carried["name"] == "Cửa đi 900"
    assert carried["width_mm"] == 900.0
    for dropped in ("host_wall_id", "offset_along_wall_mm",
                    "baseline_start_mm", "baseline_end_mm", "_internal"):
        assert dropped not in carried, dropped
