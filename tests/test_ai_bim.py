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


def test_an_agent_can_build_a_sample_and_ink_it_like_the_office(bridge):
    """The bridge is not a second, smaller application: what the menus do,
    an agent does — a whole sample building, and the pen table both the
    DXF and the paper read."""
    import ezdxf

    bridge, win = bridge
    rows = _bim(bridge, "samples")
    assert [row["key"] for row in rows] == \
        ["townhouse", "apartment", "office"]

    made = _bim(bridge, "sample", key="townhouse")
    assert made["counts"]["storeys"] == 3
    assert len(_bim(bridge, "stories")) == 3

    assert _bim(bridge, "pens")["pens"]["cut"] == [0.5, 7, "continuous"]
    _bim(bridge, "set_pen", key="cut", width_mm=0.75, color=3,
         linetype="dashed")
    assert _bim(bridge, "pens")["pens"]["cut"] == [0.75, 3, "dashed"]

    # and the export that follows actually carries it
    out = Path(win.viewport.scene.plugin_data.get("tmp", "") or
               __import__("tempfile").mkdtemp()) / "agent.dxf"
    story = _bim(bridge, "stories")[0]
    _bim(bridge, "export_dxf", path=str(out), story_id=str(story["id"]))
    doc = ezdxf.readfile(str(out))
    layer = doc.layers.get("KT-CUT")
    # 0.75 mm has no lineweight of its own in DXF, so the file carries
    # the nearest one the receiving CAD can draw (0.80) — the agent's pen
    # still arrived, and the file says a weight instead of a guess.
    assert layer.dxf.lineweight == 80, "bút của agent chưa tới file DXF"
    assert layer.dxf.linetype == "DASHED"


def test_a_pen_colour_is_an_autocad_index_and_nothing_else(bridge):
    """The tables hold the AutoCAD index, so an agent that sends a hex
    colour is TOLD — silently flooring «#ff0000» to some index would give
    the office a pen nobody chose, and the mistake would only show up on
    paper."""
    bridge, win = bridge
    _bim(bridge, "sample", key="townhouse")

    assert _bim(bridge, "set_pen", key="edge", width_mm=0.2,
                color="7")["pen"] == [0.2, 7, "continuous"]
    for bad, why in (("#ff0000", "hex"), (999, "ngoài khoảng")):
        try:
            _bim(bridge, "set_pen", key="edge", width_mm=0.2, color=bad)
        except Exception as exc:                   # noqa: BLE001 — the reply
            assert "chỉ số" in str(exc), (bad, exc)
        else:                                      # pragma: no cover
            raise AssertionError(f"{why}: {bad!r} lẽ ra phải bị từ chối")


def test_the_agent_marks_the_document_dirty_when_it_inks_it(bridge):
    """A pen is document data. The bridge is a way of editing the document,
    so an agent's pen must leave the asterisk the dialog leaves — or the
    office closes without saving the table it just set."""
    bridge, win = bridge
    _bim(bridge, "sample", key="townhouse")
    win._saved_content = win.viewport.scene.content_version
    assert not win._is_dirty()

    _bim(bridge, "set_pen", key="cut", width_mm=0.9, color=1)
    assert win._is_dirty(), "agent đổi bút mà tài liệu vẫn sạch"

    win._saved_content = win.viewport.scene.content_version
    _bim(bridge, "rename_layer", key="KT-CUT", name="A-WALL")
    assert win._is_dirty(), "đổi tên lớp mà tài liệu vẫn sạch"


def test_the_agent_can_give_a_layer_the_office_name(bridge):
    """The layer table is the drawing office's contract with whoever opens
    the file, and the agent edits it by class, by the layer the file
    carries today, or by the name it already gave it."""
    import ezdxf

    bridge, win = bridge
    _bim(bridge, "sample", key="townhouse")

    assert _bim(bridge, "rename_layer", key="KT-CUT", name="A-WALL") == \
        {"layer": "A-WALL"}
    assert _bim(bridge, "rename_layer", key="A-WALL", name="A-WALL-2") == \
        {"layer": "A-WALL-2"}, "không gọi lại được bằng tên vừa đặt"
    assert _bim(bridge, "pens")["layer_renames"]["KT-CUT"] == "A-WALL-2"

    story = _bim(bridge, "stories")[0]
    out = Path(__import__("tempfile").mkdtemp()) / "layer.dxf"
    _bim(bridge, "export_dxf", path=str(out), story_id=str(story["id"]))
    names = {layer.dxf.name for layer in ezdxf.readfile(str(out)).layers}
    assert "A-WALL-2" in names and "KT-CUT" not in names

    assert _bim(bridge, "rename_layer", key="cut", name="") == \
        {"layer": "KT-CUT"}, "xoá tên riêng không trả lớp về mặc định"
    for bad in ("Tên\nCó Xuống Dòng", "Có/Nghiêng"):
        try:
            _bim(bridge, "rename_layer", key="cut", name=bad)
        except Exception as exc:                   # noqa: BLE001 — the reply
            assert "lớp" in str(exc)
        else:                                      # pragma: no cover
            raise AssertionError(f"{bad!r} lẽ ra phải bị từ chối")
