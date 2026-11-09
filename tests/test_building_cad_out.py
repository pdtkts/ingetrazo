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


def test_the_plan_reads_back_as_the_layers_cad_expects(tmp_path):
    """The round trip: export the plan, read the file again with ezdxf.

    An office hands the DXF to another office, which opens it in its own
    CAD — so the file must carry geometry on the layers the map names, not
    only claim it in the count summary. Reading it back is the only check
    that catches a writer that lies.
    """
    import ezdxf

    from core.building.builder import build
    from core.building.model import Building
    from core.building.scene_sync import sync
    from core.scene import Scene
    from formats.dxf_bim import save_plan_dxf

    b = Building()
    g = b.add_story("Tầng 1", 0.0, 3300.0)
    for end in ((6000.0, 0.0), (0.0, 4000.0)):
        b.add_element("wall", g["id"], {
            "baseline_start_mm": [0.0, 0.0], "baseline_end_mm": list(end),
            "thickness_mm": 200.0, "height_mm": 3300.0})
    for element in list(b.elements):
        build(b, element)
    scene = Scene()
    sync(scene, b)

    path = tmp_path / "mat-bang.dxf"
    counts = save_plan_dxf(str(path), scene, b, str(g["id"]))
    assert counts["lines"] > 0

    doc = ezdxf.readfile(str(path))
    msp = doc.modelspace()
    kinds = {}
    for entity in msp:
        kinds[entity.dxftype()] = kinds.get(entity.dxftype(), 0) + 1
    assert kinds.get("LINE", 0) == counts["lines"]
    # ``counts["hatch"]`` counts AREAS filled; a HATCH entity carries one
    # path per area it fills, and every area of one material shares a
    # single entity — that is what makes its pattern a single regenerable
    # definition in the receiving CAD rather than one per wall.
    hatch_areas = sum(len(e.paths) for e in msp if e.dxftype() == "HATCH")
    assert hatch_areas == counts["hatch"], (hatch_areas, counts["hatch"])
    layers = {e.dxf.layer for e in msp}
    assert "KT-CUT" in layers
    assert "KT-HATCH" in layers
    # The unit the office set is the unit the file declares.
    assert int(doc.header.get("$INSUNITS", 0)) == 4          # millimetres


def test_the_file_is_in_the_unit_it_declares(tmp_path):
    """A CAD reads the file with the unit the file states.

    The drawing arrives in camera-plane metres and the header says
    millimetres; if the two disagree the receiving office gets a house
    1000 times too small and a dimension that agrees with nothing. The
    wall here is 6000 mm long, so its linework must span 6000 units.
    """
    import ezdxf

    from core.building.builder import build
    from core.building.drawings import view_for
    from core.building.model import Building
    from core.building.scene_sync import sync
    from core.scene import Scene
    from formats.dxf_bim import save_drawing_dxf

    b = Building()
    story = b.add_story("T1", 0.0, 3300.0)
    b.add_element("wall", story["id"], {
        "baseline_start_mm": [0.0, 0.0], "baseline_end_mm": [6000.0, 0.0],
        "thickness_mm": 200.0, "height_mm": 3300.0})
    for element in list(b.elements):
        build(b, element)
    scene = Scene()
    sync(scene, b)
    view = view_for(b, {"kind": "story", "story_id": story["id"]})
    path = tmp_path / "unit.dxf"
    save_drawing_dxf(str(path), view, scene)

    doc = ezdxf.readfile(str(path))
    assert int(doc.header.get("$INSUNITS", 0)) == 4          # millimetres
    xs = [e.dxf.start.x for e in doc.modelspace()
          if e.dxftype() == "LINE"]
    assert xs, "phải có nét"
    span = max(xs) - min(xs)
    assert 5_900.0 < span < 6_100.0, f"tường 6000 mm vẽ thành {span:.0f} đơn vị"


def test_a_dxf_carries_the_drawing_s_annotations_and_no_others(tmp_path):
    """The document holds every storey's levels and stamps at once, and an
    export that wrote them all would print the floor above's numbers on
    the ground floor's plan."""
    import ezdxf
    from core.building import drawings as D
    from core.building.model import Building
    from core.scene import Scene
    from formats.dxf_bim import save_plan_dxf

    b = Building()
    scene = Scene()
    for i in range(2):
        story = b.add_story(f"T{i + 1}", i * 3300.0, 3300.0)
        b.add_element("wall", story["id"], {
            "baseline_start_mm": [0, 0], "baseline_end_mm": [6000, 0],
            "thickness_mm": 200.0, "height_mm": 3300.0})
        view = D.view_for(b, {"kind": "story", "story_id": story["id"]})
        view.annotation_key = f"dxf:{story['id']}"
        D.annotate_plan(scene, b, view, key=view.annotation_key)
    ground = b.stories[0]["id"]
    path = tmp_path / "t1.dxf"
    save_plan_dxf(str(path), scene, b, ground,
                  annotation_key=f"dxf:{ground}")
    texts = [e for e in ezdxf.readfile(str(path)).modelspace()
             if e.dxftype() == "TEXT"]
    assert 0 < len(texts) < len(scene.text_labels), \
        f"DXF mang chú thích của cả hai tầng: {len(texts)}/{len(scene.text_labels)}"


def test_the_cut_hatch_is_a_pattern_the_cad_regenerates(tmp_path):
    """The pattern table (core.building.patterns) is geometry for the
    drawings; writing it as a PATTERN definition rather than thousands of
    anonymous lines is what makes a receiving CAD able to redraw it at any
    zoom — and what makes the table anything but dead code."""
    import ezdxf
    from core.building.commands import add_element, add_story
    from core.building.scene_sync import sync
    from core.history import History
    from formats.dxf_bim import save_plan_dxf

    from core.scene import Scene

    scene = Scene()
    history = History(scene)
    history.execute(add_story("T1", 0.0, 3300.0))
    from core.building.model import building_of

    story = building_of(scene).stories[0]
    history.execute(add_element("wall", story["id"], {
        "baseline_start_mm": [0, 0], "baseline_end_mm": [6000, 0],
        "thickness_mm": 200.0, "height_mm": 3300.0,
        "building_material_id": "gach"}, rebuild=lambda s, b: sync(s, b)))
    path = tmp_path / "cut.dxf"
    save_plan_dxf(str(path), scene, building_of(scene), story["id"])
    hatches = [e for e in ezdxf.readfile(str(path)).modelspace()
               if e.dxftype() == "HATCH"]
    assert hatches, "mặt cắt không có vệt"
    hatch = hatches[0]
    assert hatch.dxf.solid_fill == 0, "vệt cắt bị tô đặc, không phải hatch"
    assert list(hatch.pattern.lines), "hatch không có định nghĩa để CAD vẽ lại"
