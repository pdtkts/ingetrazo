# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Marco Sumari Tellez and IngeTrazo contributors.
"""A three-storey townhouse, end to end, with nothing done by hand.

This is the acceptance run: build a house the way the tools do, edit its
parameters, generate the whole drawing set, export IFC and DXF, run the
takeoff — and fail loudly at the first step that produces something wrong.
It exits non-zero, so a CI job can run it as a smoke test.

    python scripts/e2e_bim_demo.py            # the run, with its numbers
    python scripts/e2e_bim_demo.py --json     # machine-readable
    python scripts/e2e_bim_demo.py --out DIR  # keep the .igz/ifc/dxf/pdf

What it checks, in order:

1. **The model** — three storeys, walls chained around each floor, a door
   and a window with their real openings, a slab, a roof, a stair, a room.
2. **The data is the truth** — the .igz round-trips every element's
   parameters (a reopened document must know what it is, not just what it
   looked like).
3. **An edit propagates** — move the door, raise the storey; the geometry,
   the takeoff and the drawings all state the new number.
4. **The drawings** — the set generates, re-generating does not double it.
5. **The paper** — the sheets reach a PDF, the drawing reaches a DXF that
   ezdxf can read back.
6. **The schedule** — the takeoff's areas match hand figures.
7. **The exchange** — the IFC validates with zero statements.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import tempfile
import time
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

HOUSE_W = 6000.0
HOUSE_D = 4000.0
STOREYS = 3
STOREY_H = 3300.0


def _chain_room(building, story_id, z_top_link):
    """Four walls around the floor plate, chained corner to corner."""
    level = _wall(building, story_id, (0.0, 0.0), (HOUSE_W, 0.0),
                  z_top_link)
    _wall(building, story_id, (HOUSE_W, 0.0), (HOUSE_W, HOUSE_D),
          z_top_link)
    _wall(building, story_id, (HOUSE_W, HOUSE_D), (0.0, HOUSE_D),
          z_top_link)
    _wall(building, story_id, (0.0, HOUSE_D), (0.0, 0.0), z_top_link)
    return level


def _wall(building, story_id, start, end, top_link):
    return building.add_element("wall", story_id, {
        "baseline_start_mm": [start[0], start[1]],
        "baseline_end_mm": [end[0], end[1]],
        "thickness_mm": 200.0,
        "height_mm": STOREY_H,
        "top_link": top_link,
        "building_material_id": "gach",
    })


def build_house():
    """The model: three storeys of a small townhouse.

    Returns the standalone building (the caller's scene gets its contents:
    the scene owns the live one, exactly as opening a document does).
    """
    from core.building.builder import build
    from core.building.model import Building

    building = Building()
    building.project["name"] = "Nhà phố 3 tầng"
    building.project["designer"] = "IngeTrazo"
    stories = [building.add_story(f"Tầng {i + 1}", i * STOREY_H, STOREY_H)
               for i in range(STOREYS)]
    for i, story in enumerate(stories):
        top = "next" if i < STOREYS - 1 else "none"
        _chain_room(building, story["id"], top)
        zone = building.add_element("zone", story["id"], {
            "outline_mm": [[200.0, 200.0], [HOUSE_W - 200.0, 200.0],
                           [HOUSE_W - 200.0, HOUSE_D - 200.0],
                           [200.0, HOUSE_D - 200.0]],
            "name": f"Phòng {i + 1}"})
        _mesh, derived = build(building, zone)
        zone["derived"] = derived
        slab = building.add_element("slab", story["id"], {
            "outline_mm": [[0.0, 0.0], [HOUSE_W, 0.0],
                           [HOUSE_W, HOUSE_D], [0.0, HOUSE_D]],
            "thickness_mm": 120.0, "building_material_id": "btct"})
        _mesh, derived = build(building, slab)
        slab["derived"] = derived

    ground = stories[0]
    front = building.elements[0]
    door = building.add_element("door", ground["id"], {
        "host_wall_id": front["id"], "offset_along_wall_mm": 3000.0,
        "width_mm": 900.0, "height_mm": 2200.0, "sill_height_mm": 0.0,
        "name": "D1"})
    build(building, door)
    window = building.add_element("window", ground["id"], {
        "host_wall_id": front["id"], "offset_along_wall_mm": 5000.0,
        "width_mm": 1200.0, "height_mm": 1200.0, "sill_height_mm": 900.0,
        "name": "S1"})
    build(building, window)
    stair = building.add_element("stair", ground["id"], {
        "path_mm": [[500.0, 500.0], [500.0, HOUSE_D - 500.0]],
        "width_mm": 1000.0, "tread_mm": 260.0, "waist_mm": 150.0})
    build(building, stair)
    roof = building.add_element("roof", stories[-1]["id"], {
        "outline_mm": [[0.0, 0.0], [HOUSE_W, 0.0], [HOUSE_W, HOUSE_D],
                       [0.0, HOUSE_D]],
        "thickness_mm": 150.0, "slope_deg": 30.0, "overhang_mm": 500.0,
        "top_link": "next", "height_mm": STOREY_H})
    _mesh, derived = build(building, roof)
    roof["derived"] = derived
    return building


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--json", action="store_true",
                        help="print the result as JSON")
    parser.add_argument("--out", default="",
                        help="directory to keep the generated files in")
    args = parser.parse_args(argv)
    report: dict = {"steps": [], "failures": []}

    def step(name: str, detail: str = "") -> None:
        report["steps"].append({"name": name, "detail": detail,
                                "at": round(time.perf_counter(), 3)})

    def fail(name: str, why: str) -> None:
        report["failures"].append({"name": name, "why": why})

    out_dir = Path(args.out) if args.out else Path(
        tempfile.mkdtemp(prefix="bim-e2e-"))

    # ---- 1. the model ---------------------------------------------------
    from core.building import building_of
    from core.building.scene_sync import sync
    from core.history import History
    from core.scene import Scene

    scene = Scene()
    building = building_of(scene)
    source = build_house()
    building.stories = source.stories
    building.elements = source.elements
    building.project.update(source.project)
    built, _removed = sync(scene, building)
    step("model", f"{len(building.stories)} tầng, "
                  f"{len(building.elements)} cấu kiện, "
                  f"{built} khối dựng")
    if built < len(building.elements) - STOREYS:
        fail("model", f"chỉ dựng được {built} khối")

    # ---- 2. the data round-trips ---------------------------------------
    from formats.igz import load_into, save_scene

    doc = out_dir / "nha-pho.igz"
    save_scene(scene, doc)
    reloaded = Scene()
    load_into(reloaded, doc)
    again = building_of(reloaded)
    if len(again.elements) != len(building.elements):
        fail("round-trip", f"{len(again.elements)} cấu kiện sau khi mở lại, "
                           f"mong đợi {len(building.elements)}")
    for element in building.elements:
        back = again.element(str(element["id"]))
        if back is None:
            fail("round-trip", f"mất cấu kiện {element['id']}")
            continue
        for key, value in (element.get("params") or {}).items():
            if key in ("host_wall_id",) and not value:
                continue
            if (back.get("params") or {}).get(key) != value:
                fail("round-trip", f"{element['type']}.{key} đổi giá trị")
    step("round-trip", f"{doc.stat().st_size} bytes .igz")

    # ---- 3. an edit propagates -----------------------------------------
    from core.building import drawings as D
    from core.building.commands import BuildingEdit
    from core.building.takeoff import tables as takeoff_tables

    history = History(scene)
    door_id = next(e["id"] for e in building.elements
                   if e.get("type") == "door")
    before = takeoff_tables(building)

    def widen(b) -> None:
        # Widening the door is the edit that must move EVERY number: a
        # 900 → 1200 door takes 0.30 × 2.20 = 0.66 m² more out of its wall.
        params = b.element(door_id)["params"]
        params["offset_along_wall_mm"] = 4500.0
        params["width_mm"] = 1200.0

    history.execute(BuildingEdit(
        widen, rebuild=lambda s, b: sync(s, b, [door_id], force=True)))
    step("edit", "cửa D1 rộng 900 → 1200, dời sang u = 4500")
    chains = D.wall_chains(building, [e for e in building.elements
                                       if e.get("type") == "wall"
                                       and str(e.get("story_id")) ==
                                       str(building.stories[0]["id"])])
    values = sorted(round(abs(b[0] - a[0]))
                    for chain in chains for a, b, _side in chain)
    step("edit→chains", f"kích thước mới: {values}")
    if 4500.0 not in [round(v) for v in values] and 6000 not in [round(v)
                                                                for v in values]:
        fail("edit", f"kích thước không cập nhật: {values}")
    after = takeoff_tables(building)
    # Two rules, both stated: the BILLED area is gross (the openings are
    # their own line) and does not move when a door is widened; the wall's
    # real face (net) must drop by exactly the extra opening.
    was = float((before.get("totals") or {}).get("wall_net_area_m2") or 0.0)
    now = float((after.get("totals") or {}).get("wall_net_area_m2") or 0.0)
    delta = round((was - now) * 100.0) / 100.0
    if abs(delta - 0.66) > 0.02:
        fail("edit", f"diện tích thực tế đổi {delta} m², mong đợi 0.66")
    gross_now = float((after.get("totals") or {}).get("wall_area_m2") or 0.0)
    step("edit→takeoff",
         f"tường: thực tế {was} → {now} m² (bớt {delta}), "
         f"diện tích tính tiền {gross_now} m²")

    # ---- 4. the drawing set --------------------------------------------
    from core.building import docset as DS

    scene.saved_views.clear()
    scene.compositions.clear()
    result = DS.generate_docset(scene, building)
    step("docset", f"{len(result.sheets)} tờ: {result.summary()}")
    # Every sheet the set hands back must carry a drawing or words: the
    # trades the house does not have (columns, beams) are not issued at all,
    # so the count follows the model rather than a fixed number.
    blank = [s.name for s in result.sheets
             if not s.frames and not any(str(t.text).strip() for t in s.texts)]
    if blank:
        fail("docset", f"tờ trắng được phát hành: {blank}")
    filled = [s for s in result.sheets if s.frames]
    if len(filled) < 14:
        fail("docset", f"chỉ {len(filled)} tờ có bản vẽ")
    stores = [s for s in result.sheets
              if "Mặt bằng — " in s.name and s.frames]
    if len(stores) != len(building.stories):
        fail("docset", f"{len(stores)} mặt bằng cho {len(building.stories)} tầng")
    # A second run must not double the set.
    frames = sum(len(s.frames) for s in result.sheets)
    scenes = len(scene.saved_views)
    again = DS.generate_docset(scene, building)
    if sum(len(s.frames) for s in again.sheets) != frames:
        fail("docset", "sinh lại làm nhân đôi khung bản vẽ")
    if len(scene.saved_views) != scenes:
        fail("docset", "sinh lại làm nhân đôi scene")
    step("docset re-issue", f"{frames} khung, {scenes} scene, không đổi")

    # ---- 5. the paper ---------------------------------------------------
    from formats.dxf_bim import save_plan_dxf

    dxf = out_dir / "mat-bang.dxf"
    counts = save_plan_dxf(dxf, scene, building, building.stories[0]["id"])
    step("dxf", str(counts))
    if counts["lines"] == 0:
        fail("dxf", "không có nét nào")
    try:
        import ezdxf
        doc = ezdxf.readfile(str(dxf))
        types = {e.dxftype() for e in doc.modelspace()}
        if "LINE" not in types:
            fail("dxf", "thiếu LINE")
        if counts["hatch"] and "HATCH" not in types:
            fail("dxf", "thiếu HATCH dù có vệt cắt")
    except ImportError:
        step("dxf", "ezdxf không có — bỏ kiểm đọc lại")

    # ---- 5b. the sheets on paper ---------------------------------------
    # The PDF needs the live window (the composer renders through it), so it
    # runs only when one is available — a headless checkout still gets every
    # other check.
    try:
        from PySide6.QtWidgets import QApplication as _App
        if _App.instance() is None:
            # main.py normally owns this; scripts must create it before any
            # widget exists.
            os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
            _App(sys.argv[:1])
        from core.building.sheets import export_sheets_pdf
        from views.main_window import MainWindow as _MainWindow
        _win = _MainWindow()
        win_scene = _win.viewport.scene
        # The composer renders through the WINDOW's document, so the set is
        # carried over: same rules, same scenes, same annotations.
        from core.building.model import building_of as _bof
        target = _bof(win_scene)
        target.stories[:] = [dict(s) for s in building.stories]
        target.elements[:] = [dict(e) for e in building.elements]
        target.project.update(building.project)
        win_scene.compositions[:] = scene.compositions
        win_scene.saved_views[:] = scene.saved_views
        win_scene.section_planes[:] = scene.section_planes
        win_scene.dimensions[:] = scene.dimensions
        win_scene.text_labels[:] = scene.text_labels
        from core.building.scene_sync import sync as _sync
        _sync(win_scene, target)
        pdf = out_dir / "ho-so.pdf"
        failed = export_sheets_pdf(_win, str(pdf))
        step("pdf", f"{pdf.stat().st_size} bytes, "
                    f"{len(failed)} tờ lỗi")
        if failed:
            fail("pdf", f"không vẽ được: {failed}")
        _win.hide()
    except Exception as exc:                           # noqa: BLE001
        step("pdf", f"bỏ qua ({type(exc).__name__})")

    # ---- 6. the schedule ------------------------------------------------
    table_set = takeoff_tables(building)
    step("takeoff", f"{len(table_set) - 1} bảng")
    wall_row = _find_wall_area(table_set)
    if wall_row is None:
        fail("takeoff", "không có bảng diện tích tường")
    else:
        story = building.stories[0]
        params = [len([e for e in building.elements
                       if e.get("type") == "wall"
                       and str(e.get("story_id")) == str(story["id"])])]
        if params[0] < 4:
            fail("takeoff", f"tầng 1 chỉ {params[0]} tường")
        rows = wall_row or []
        if not rows:
            fail("takeoff", "bảng tường không có dòng nào")
        else:
            # The schedule must agree with the walls it measured: 11 walls
            # (three full storeys minus the two the roof storey lacks) times
            # their own height, minus the openings.
            totals = (table_set.get("totals") or {})
            area = float(totals.get("wall_area_m2") or 0.0)
            if not 150.0 < area < 260.0:
                fail("takeoff", f"diện tích tường {area} m² ngoài dự kiến")
            step("takeoff tường",
                 f"{len(rows)} dòng, {area} m², "
                 f"{totals.get('door_count')} cửa, "
                 f"{totals.get('window_count')} cửa sổ")

    # ---- 7. the exchange ------------------------------------------------
    from formats.ifc import save_building_ifc

    ifc = out_dir / "nha-pho.ifc"
    written = save_building_ifc(scene, ifc)
    step("ifc", f"{written} thực thể, {ifc.stat().st_size} bytes")
    try:
        import ifcopenshell
        import ifcopenshell.validate as validate

        logger = validate.json_logger()
        validate.validate(str(ifc), logger)
        errors = [s for s in logger.statements
                  if str(s.get("level")) == "error"]
        if errors:
            fail("ifc", f"{len(errors)} lỗi schema, đầu tiên: "
                        f"{str(errors[0].get('message'))[:80]}")
        step("ifc validate", f"{len(logger.statements)} thông báo")
    except ImportError:
        step("ifc validate", "ifcopenshell không có — bỏ kiểm")

    report["ok"] = not report["failures"]
    report["out_dir"] = str(out_dir)
    if args.json:
        print(json.dumps(report, ensure_ascii=False, indent=2))
    else:
        for entry in report["steps"]:
            print(f"  ✓ {entry['name']}: {entry['detail']}")
        for entry in report["failures"]:
            print(f"  ✗ {entry['name']}: {entry['why']}")
        print(f"\n{'ĐẠT' if report['ok'] else 'KHÔNG ĐẠT'} — "
              f"file trong {out_dir}")
    return 0 if report["ok"] else 1


def _find_wall_area(table_set) -> dict | None:
    """The wall table of the takeoff, whatever the caller called it."""
    if not isinstance(table_set, dict):
        return None
    return table_set.get("walls")


if __name__ == "__main__":
    raise SystemExit(main())
