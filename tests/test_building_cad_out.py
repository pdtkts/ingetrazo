# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Marco Sumari Tellez and IngeTrazo contributors.
"""A drawing goes to CAD with what makes it a drawing.

Lines alone are not enough: a section without its hatch reads as a hole, a
dimension that arrives as two dead lines cannot be renumbered, and text
that arrives at the wrong height is unreadable at 1:50. And all of it must
land on the LAYERS the model already uses, or the office renaming its pen
table has nothing to rename.
"""
from __future__ import annotations

import pytest

ezdxf = pytest.importorskip("ezdxf")

from core.building import drawings as D                # noqa: E402
from core.building.builder import build                # noqa: E402
from core.building.model import Building               # noqa: E402
from core.building.scene_sync import sync              # noqa: E402
from core.scene import Scene                           # noqa: E402
from formats import dxf_bim                            # noqa: E402


@pytest.fixture()
def drawn(tmp_path):
    b = Building()
    s1 = b.add_story("Tầng 1", 0.0, 3300.0)
    b.add_story("Tầng 2", 3300.0, 3300.0)
    wall = b.add_element("wall", s1["id"], {
        "baseline_start_mm": [0, 0], "baseline_end_mm": [6000, 0],
        "thickness_mm": 200.0, "height_mm": 3300.0, "top_link": "next"})
    door = b.add_element("door", s1["id"], {
        "host_wall_id": wall["id"], "offset_along_wall_mm": 3000.0,
        "width_mm": 900.0, "height_mm": 2200.0, "name": "D1"})
    build(b, door)
    zone = b.add_element("zone", s1["id"], {
        "outline_mm": [[0, 0], [6000, 0], [6000, 4000], [0, 4000]],
        "name": "Phòng khách"})
    _mesh, derived = build(b, zone)
    zone["derived"] = derived
    scene = Scene()
    sync(scene, b)
    view = D.view_for(b, {"kind": "story", "story_id": s1["id"]})
    D.annotate_plan(scene, b, view)
    return b, scene, view, tmp_path / "plan.dxf"


def test_the_dxf_is_written_with_the_whole_drawing(drawn):
    b, scene, view, path = drawn
    counts = dxf_bim.save_plan_dxf(path, scene, b, b.stories[0]["id"])
    assert path.exists()
    assert counts["lines"] > 0
    assert counts["dimensions"] > 0
    assert counts["text"] > 0
    doc = ezdxf.readfile(str(path))
    types = {e.dxftype() for e in doc.modelspace()}
    assert {"LINE", "TEXT", "DIMENSION"} <= types


def test_the_section_arrives_with_its_hatch(drawn):
    """The cut reaches CAD as real HATCH, not as a bare outline: an
    unhatched wall in section is indistinguishable from a hole in one."""
    b, scene, view, path = drawn
    counts = dxf_bim.save_plan_dxf(path, scene, b, b.stories[0]["id"])
    assert counts["hatch"] > 0
    doc = ezdxf.readfile(str(path))
    hatches = [e for e in doc.modelspace() if e.dxftype() == "HATCH"]
    assert hatches
    for hatch in hatches:
        assert hatch.paths


def test_the_drawing_goes_out_on_the_model_s_own_layers(drawn):
    b, scene, view, path = drawn
    dxf_bim.save_plan_dxf(path, scene, b, b.stories[0]["id"])
    doc = ezdxf.readfile(str(path))
    names = {layer.dxf.name for layer in doc.layers}
    assert {"KT-CUT", "KT-EDGE", "KT-HATCH"} <= names
    # …and the pen table gives the cut more weight than the edges.
    cut = doc.layers.get("KT-CUT")
    edge = doc.layers.get("KT-EDGE")
    assert cut.dxf.lineweight > edge.dxf.lineweight


def test_the_model_mm_is_declared_so_the_cad_scales_it_right(drawn):
    """A DXf whose units are a guess lands at 1:1 in some CADs and 1:25 in
    others; the file states millimetres and the reader believes it."""
    b, scene, view, path = drawn
    dxf_bim.save_plan_dxf(path, scene, b, b.stories[0]["id"])
    doc = ezdxf.readfile(str(path))
    assert doc.header["$INSUNITS"] == 4                # millimetres


def test_a_company_s_layer_table_renames_everything_it_names(drawn):
    b, scene, view, path = drawn
    table = {"KT-CUT": "A-WALL", "KT-EDGE": "A-LINE"}
    dxf_bim.save_plan_dxf(path, scene, b, b.stories[0]["id"],
                          layer_map=table)
    doc = ezdxf.readfile(str(path))
    names = {layer.dxf.name for layer in doc.layers}
    assert "A-WALL" in names and "A-LINE" in names
    assert "KT-CUT" not in names


def test_exporting_never_disturbs_the_live_model(drawn):
    """The export runs while a user is working: it must leave the scene's
    active cut and its section list exactly as it found them."""
    b, scene, view, path = drawn
    before_planes = list(scene.section_planes)
    before_active = scene.active_section()
    dxf_bim.save_plan_dxf(path, scene, b, b.stories[0]["id"])
    assert list(scene.section_planes) == before_planes
    assert scene.active_section() is before_active


def test_an_empty_model_writes_an_empty_dxf_not_an_error(tmp_path):
    b = Building()
    b.add_story("Tầng 1", 0.0, 3300.0)
    scene = Scene()
    view = D.view_for(b, {"kind": "story", "story_id": b.stories[0]["id"]})
    path = tmp_path / "empty.dxf"
    counts = dxf_bim.save_plan_dxf(path, scene, b, b.stories[0]["id"])
    assert path.exists()
    assert counts["lines"] == 0
