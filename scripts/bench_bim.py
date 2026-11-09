# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Marco Sumari Tellez and IngeTrazo contributors.
"""What a BIM model costs: ~3000 elements, timed where the user waits.

The acceptance run asks for a number, not a feeling ("thao tác 3D + mở
cửa sổ Plan dưới ngưỡng giật cảm nhận"). This script builds a house of the
requested size the way the tools do, then times the four operations a user
actually performs on it:

  build     — sync the scene to the parameters (an edit's geometry)
  edit      — one parameter change through the undo stack, rebuilt
  takeoff   — the schedule
  docset    — the whole drawing set
  hlr       — one plan's hidden-line pass (what a sheet redraw costs)

    python scripts/bench_bim.py                 # 3000 elements
    python scripts/bench_bim.py --count 500
    python scripts/bench_bim.py --json
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import time
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

FLOOR_W = 12000.0
FLOOR_D = 9000.0
STOREY_H = 3300.0


def build_model(target: int):
    """A building with roughly ``target`` elements: storeys of walls,
    columns, beams, slabs, rooms and openings."""
    from core.building.builder import build
    from core.building.model import Building

    building = Building()
    building.project["name"] = "Nhà mẫu bench"
    # A storey costs 28 elements (10 walls, 6 columns, a slab, 3 rooms and
    # 2 openings), so the storey count follows from the target — measured,
    # not guessed, because a bench that builds a third of the model it
    # claims to build is worse than no bench.
    per_storey = 28
    storeys = max(1, round(target / per_storey))
    rows = [building.add_story(f"Tầng {i + 1}", i * STOREY_H, STOREY_H)
            for i in range(storeys)]
    for i, story in enumerate(rows):
        top = "next" if i < storeys - 1 else "none"
        _plate(building, story["id"])
        for k in range(6):
            x = FLOOR_W * (k + 1) / 7.0
            _wall(building, story["id"], (x, 0.0), (x, FLOOR_D), top)
        _wall(building, story["id"], (FLOOR_W / 2, 0.0),
              (FLOOR_W / 2, FLOOR_D), top)
        for k in range(6):
            y = FLOOR_D * (k + 1) / 7.0
            _wall(building, story["id"], (0.0, y), (FLOOR_W, y), top)
        for cx in (3000.0, 6000.0, 9000.0):
            for cy in (3000.0, 6000.0):
                column = building.add_element("column", story["id"], {
                    "center_mm": [cx, cy], "shape": "rect",
                    "width_mm": 220.0, "depth_mm": 220.0,
                    "top_link": top})
                build(building, column)
        slab = building.add_element("slab", story["id"], {
            "outline_mm": [[0.0, 0.0], [FLOOR_W, 0.0], [FLOOR_W, FLOOR_D],
                           [0.0, FLOOR_D]],
            "thickness_mm": 120.0, "building_material_id": "btct"})
        _mesh, derived = build(building, slab)
        slab["derived"] = derived
        for k in range(3):
            zone = building.add_element("zone", story["id"], {
                "outline_mm": [[k * 3000.0 + 200.0, 200.0],
                               [(k + 1) * 3000.0 - 200.0, 200.0],
                               [(k + 1) * 3000.0 - 200.0, 4000.0],
                               [k * 3000.0 + 200.0, 4000.0]],
                "name": f"Phòng {k + 1}"})
            _mesh, derived = build(building, zone)
            zone["derived"] = derived
        front = next(e for e in building.elements
                     if e.get("type") == "wall"
                     and str(e.get("story_id")) == str(story["id"]))
        door = building.add_element("door", story["id"], {
            "host_wall_id": front["id"], "offset_along_wall_mm": 2000.0,
            "width_mm": 900.0, "height_mm": 2200.0})
        build(building, door)
        window = building.add_element("window", story["id"], {
            "host_wall_id": front["id"], "offset_along_wall_mm": 5000.0,
            "width_mm": 1200.0, "height_mm": 1200.0,
            "sill_height_mm": 900.0})
        build(building, window)
    return building


def _plate(building, story_id):
    return [_wall(building, story_id, (0.0, 0.0), (FLOOR_W, 0.0), "none"),
            _wall(building, story_id, (FLOOR_W, 0.0), (FLOOR_W, FLOOR_D),
                  "none"),
            _wall(building, story_id, (0.0, FLOOR_D), (0.0, 0.0), "none")]


def _wall(building, story_id, start, end, top_link):
    return building.add_element("wall", story_id, {
        "baseline_start_mm": [start[0], start[1]],
        "baseline_end_mm": [end[0], end[1]],
        "thickness_mm": 200.0, "height_mm": STOREY_H, "top_link": top_link,
        "building_material_id": "gach"})


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--count", type=int, default=3000,
                        help="approximate element count")
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args(argv)

    from core.building import building_of
    from core.building import docset as DS
    from core.building import drawings as D
    from core.building.commands import BuildingEdit
    from core.building.scene_sync import sync
    from core.building.takeoff import tables as takeoff_tables
    from core.history import History
    from core.hlr import hlr_drawing
    from core.scene import Scene

    source = build_model(args.count)
    scene = Scene()
    building = building_of(scene)
    building.stories = source.stories
    building.elements = source.elements
    building.project.update(source.project)
    history = History(scene)

    timings: dict = {}
    t0 = time.perf_counter()
    built, _removed = sync(scene, building)
    timings["build_s"] = time.perf_counter() - t0
    timings["elements"] = len(building.elements)
    timings["groups"] = built

    wall = next(e for e in building.elements if e.get("type") == "wall")
    wall_id = str(wall["id"])

    def nudge(b) -> None:
        params = b.element(wall_id)["params"]
        params["thickness_mm"] = float(params.get("thickness_mm", 200.0)) + 10.0

    t0 = time.perf_counter()
    history.execute(BuildingEdit(
        nudge, rebuild=lambda s, b: sync(s, b, [wall_id], force=True)))
    timings["edit_s"] = time.perf_counter() - t0

    t0 = time.perf_counter()
    history.execute(BuildingEdit(
        nudge, rebuild=lambda s, b: sync(s, b, [wall_id], force=True)))
    timings["edit_full_s"] = time.perf_counter() - t0

    t0 = time.perf_counter()
    takeoff_tables(building)
    timings["takeoff_s"] = time.perf_counter() - t0

    story = building.stories[len(building.stories) // 2]
    view = D.view_for(building, {"kind": "story", "story_id": story["id"]})
    # The line drawing splits into two costs, and a bench that reports one
    # number hides which of them to work on: collecting the geometry (a
    # scene walk) and the hidden-line pass itself.
    from core.hlr import collect_geometry
    t0 = time.perf_counter()
    collect_geometry(scene)
    timings["hlr_collect_s"] = time.perf_counter() - t0
    t0 = time.perf_counter()
    drawing = hlr_drawing(scene, view.camera(), fills=True,
                          clip_planes=view.clip_planes,
                          section=view.section_planes[0])
    timings["hlr_s"] = time.perf_counter() - t0
    timings["hlr_segments"] = int(drawing.segs.shape[0])

    t0 = time.perf_counter()
    DS.generate_docset(scene, building)
    timings["docset_s"] = time.perf_counter() - t0

    t0 = time.perf_counter()
    DS.generate_docset(scene, building)
    timings["docset_reissue_s"] = time.perf_counter() - t0

    if args.json:
        print(json.dumps(timings, ensure_ascii=False, indent=2))
    else:
        print(f"mô hình: {timings['elements']} cấu kiện, "
              f"{timings['groups']} khối")
        for key in ("build_s", "edit_s", "edit_full_s", "takeoff_s",
                    "hlr_collect_s", "hlr_s", "docset_s",
                    "docset_reissue_s"):
            print(f"  {key:18s} {timings[key] * 1000.0:9.1f} ms")
        print(f"  hlr_segments       {timings['hlr_segments']:9d}")
        print(f"  docset sheets      "
              f"{len(scene.compositions):9d}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
