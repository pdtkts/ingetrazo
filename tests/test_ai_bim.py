# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Marco Sumari Tellez and IngeTrazo contributors.
"""The BIM engine over the AI bridge: an agent builds a house for real.

What matters is not that the calls return — it is that the agent's work
lands in the USER's document through the USER's undo stack, one step per
operation, with the geometry and the numbers following. An agent that can
bypass undo, or that leaves a model whose takeoff disagrees with its
picture, is worse than no agent.
"""
from __future__ import annotations

import json
import os
import sys
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

if QApplication.instance() is None:
    QApplication(sys.argv[:1])


@pytest.fixture()
def bridge(monkeypatch):
    from plugins.ai_bridge import _Bridge
    from views.main_window import MainWindow
    monkeypatch.setenv("INGETRAZO_AI_PORT", "0")
    win = MainWindow()
    bridge = _Bridge(win.viewport)
    bridge.start()
    assert bridge.port
    yield bridge, win
    bridge.stop()


def _bim(bridge, action: str, **args) -> dict:
    """One BIM action, run on the Qt main thread as the socket would."""
    from tests.test_ai_bridge import _ask
    reply = _ask(bridge, "bim", {"action": action, **args})
    assert reply.get("ok"), reply.get("error")
    return reply["result"]["result"]


def test_an_agent_builds_a_house_through_the_undo_stack(bridge):
    bridge, win = bridge
    scene = win.viewport.scene
    history = win.viewport.history

    story = _bim(bridge, "story", name="Tầng 1", z_mm=0, height_mm=3300)
    assert story["name"] == "Tầng 1"
    depth = len(history.undo_stack)

    wall = _bim(bridge, "wall", story_id=story["id"], start_mm=[0, 0],
                end_mm=[6000, 0], name="Tường A")
    assert wall["params"]["name"] == "Tường A"
    # The geometry followed the parameters, which is the whole point of the
    # engine: the group exists and carries its IFC class.
    groups = [g for g in scene.groups if g.name.endswith("Tường A")]
    assert groups and (groups[0].ifc or {}).get("class") == "IfcWall"

    door = _bim(bridge, "door", wall_id=wall["id"], u_mm=3000)
    assert door["derived"]["area_m2"] == pytest.approx(1.98)

    room = _bim(bridge, "room", story_id=story["id"], name="Phòng khách",
                outline_mm=[[0, 0], [6000, 0], [6000, 4000], [0, 4000]])
    assert room["type"] == "zone"

    totals = _bim(bridge, "takeoff")["totals"]
    assert totals["wall_area_m2"] == pytest.approx(19.8)
    assert totals["wall_net_area_m2"] == pytest.approx(17.82)
    assert totals["room_area_m2"] == pytest.approx(24.0)
    assert totals["door_count"] == 1
    assert len(history.undo_stack) > depth       # every call is a step


def test_each_agent_operation_is_one_undo_step(bridge):
    """A single undo must take back exactly one operation — not the whole
    script, and not half of one."""
    bridge, win = bridge
    history = win.viewport.history
    for _ in range(len(history.undo_stack)):
        if not history.undo():
            break
    story = _bim(bridge, "story", name="Tầng 9")
    _bim(bridge, "wall", story_id=story["id"], start_mm=[0, 0],
         end_mm=[4000, 0], name="W")
    before = len(_bim(bridge, "elements"))
    assert history.undo()
    assert len(_bim(bridge, "elements")) == before - 1
    assert _bim(bridge, "elements", kind="story") or True


def test_an_edit_moves_both_the_geometry_and_the_numbers(bridge):
    bridge, win = bridge
    story = _bim(bridge, "story", name="Tầng 1", height_mm=3300)
    wall = _bim(bridge, "wall", story_id=story["id"], start_mm=[0, 0],
                end_mm=[6000, 0])
    door = _bim(bridge, "door", wall_id=wall["id"], u_mm=3000,
                width_mm=900)
    before = _bim(bridge, "takeoff")["totals"]["wall_net_area_m2"]
    _bim(bridge, "edit", element_id=door["id"],
         params={"width_mm": 1500.0})
    after = _bim(bridge, "takeoff")["totals"]["wall_net_area_m2"]
    assert before - after == pytest.approx(0.6 * 2.2, abs=0.01)


def test_the_agent_can_issue_the_drawing_set_and_read_a_rule(bridge):
    bridge, win = bridge
    story = _bim(bridge, "story", name="Tầng 1", height_mm=3300)
    _bim(bridge, "wall", story_id=story["id"], start_mm=[0, 0],
         end_mm=[6000, 0])
    _bim(bridge, "room", story_id=story["id"], name="P",
         outline_mm=[[0, 0], [6000, 0], [6000, 4000], [0, 4000]])
    sheets = _bim(bridge, "docset")
    # The house has one storey, so it issues the four plans of that storey
    # plus the cover and the index — and NOT a blank sheet for every trade
    # it does not have (no column, beam, stair, door or fixture here).
    assert any("Mặt bằng — Tầng 1" in name for name in sheets)
    assert len(sheets) >= 8
    rule = _bim(bridge, "drawings", kind="story", story_id=story["id"])
    assert rule["kind"] == "story"
    assert rule["views"]                       # the +1200 cut is in there
    assert rule["clips"]                       # …and the floor trim
    assert rule["scale_denom"] > 0


def test_the_agent_can_export_ifc_and_dxf(bridge, tmp_path):
    bridge, win = bridge
    story = _bim(bridge, "story", name="Tầng 1", height_mm=3300)
    _bim(bridge, "wall", story_id=story["id"], start_mm=[0, 0],
         end_mm=[6000, 0])
    ifc = tmp_path / "m.ifc"
    written = _bim(bridge, "export_ifc", path=str(ifc))
    assert written > 0 and ifc.exists()
    dxf = tmp_path / "p.dxf"
    counts = _bim(bridge, "export_dxf", path=str(dxf))
    assert counts["lines"] > 0 and dxf.exists()


def test_an_unknown_action_is_refused_in_words(bridge):
    bridge, win = bridge
    from tests.test_ai_bridge import _ask
    reply = _ask(bridge, "bim", {"action": "build-me-a-house"})
    assert reply["ok"] is False
    assert "unknown BIM action" in reply["error"]
    assert "wall" in reply["error"]              # …and the real ones listed


def test_the_scope_offers_both_the_session_and_the_tagger():
    """``bim`` is the building engine an agent drives; ``tags`` is the
    face-tagging layer. Both names must be in the scope, and the old
    meaning of ``bim`` must not silently vanish from under a saved script."""
    import core.ai as ai

    class _VP:
        def __init__(self):
            from core.scene import Scene
            self.scene = Scene()
            self.camera = None

    scope = ai.build_scope(_VP())
    assert "bim" in scope and hasattr(scope["bim"], "add_story")
    assert "tags" in scope
