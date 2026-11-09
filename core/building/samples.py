# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Marco Sumari Tellez and IngeTrazo contributors.
"""Sample buildings: three houses, stated as parameters, made in one call.

The first hour with a BIM tool is spent drawing walls before anything can
be looked at. These three presets are that hour saved: a townhouse, an
apartment floor and a small office — each a real parametric model (storeys,
walls, openings, slabs, a roof), not a mesh, so everything the app does
afterwards works on it: the takeoff, the drawings, the IFC, the schedule.

They are stated ONCE, here, in the same terms the tools write, and built
through the same commands, so a preset cannot produce a model the tools
could not have drawn by hand.
"""
from __future__ import annotations

from core.i18n import tr

#: One storey of a preset: ``(name, height_mm, footprint_mm, walls)`` where
#: ``walls`` is a list of ``(start, end, thickness_mm, openings)`` and each
#: opening is ``(kind, position_ratio, width_mm, height_mm, sill_mm)``.
TOWNHOUSE = {
    "key": "townhouse",
    "name": "Nhà phố 3 tầng",
    "note": "Nhà phố 6 × 4 m, ba tầng, mái bằng — kiểu nhà phố Việt Nam.",
    "storey_h_mm": 3300.0,
    "outline_w_mm": 6000.0,
    "outline_d_mm": 4000.0,
    "storeys": 3,
    "front_openings": (("door", 0.5, 900.0, 2200.0, 0.0),
                       ("window", 0.85, 1200.0, 1200.0, 900.0)),
    "side_openings": (("window", 0.35, 900.0, 1200.0, 900.0),
                      ("window", 0.7, 900.0, 1200.0, 900.0)),
    "roof": "flat",
}

APARTMENT = {
    "key": "apartment",
    "name": "Căn hộ 2 phòng ngủ",
    "note": "Một sàn căn hộ 10 × 8 m, hai phòng ngủ, một vệ sinh.",
    "storey_h_mm": 3000.0,
    "outline_w_mm": 10000.0,
    "outline_d_mm": 8000.0,
    "storeys": 1,
    "front_openings": (("door", 0.2, 900.0, 2200.0, 0.0),),
    "side_openings": (("window", 0.3, 1500.0, 1350.0, 900.0),),
    "partitions_mm": ((3000.0, 0.0, 3000.0, 5000.0),
                      (3000.0, 5000.0, 10000.0, 5000.0)),
    "roof": "none",
}

OFFICE = {
    "key": "office",
    "name": "Văn phòng 2 tầng",
    "note": "Văn phòng 12 × 9 m, hai tầng, vách kính mặt tiền.",
    "storey_h_mm": 3600.0,
    "outline_w_mm": 12000.0,
    "outline_d_mm": 9000.0,
    "storeys": 2,
    "front_openings": (("door", 0.15, 1500.0, 2400.0, 0.0),),
    "side_openings": (("window", 0.5, 1800.0, 1500.0, 900.0),),
    "curtain_wall_mm": 8000.0,          # the glazed run along the front
    "roof": "flat",
}

#: The three, in the order the menu shows them.
PRESETS = (TOWNHOUSE, APARTMENT, OFFICE)


def preset(key: str) -> dict:
    """One preset by key; raises ``KeyError`` for an unknown one."""
    for record in PRESETS:
        if str(record["key"]) == str(key):
            return record
    raise KeyError(key)


def keys() -> list:
    return [str(record["key"]) for record in PRESETS]


def name(key: str) -> str:
    return str(preset(key)["name"])


def build_sample(history, scene, key: str, *, material: str = "gach"):
    """Build one preset into ``scene`` through the app's own commands.

    Every step is a real :class:`BuildingEdit`, so the whole sample is
    ordinary undo history — a user who does not like it presses Ctrl+Z
    once per element, exactly as if they had drawn it. Returns
    ``(building, counts)`` with what was made.
    """
    from core.building import commands as bim_commands
    from core.building.model import building_of
    from core.building.scene_sync import sync

    record = preset(key)
    rebuild = lambda s, b: sync(s, b)             # noqa: E731 — one hook
    w = float(record["outline_w_mm"])
    d = float(record["outline_d_mm"])
    counts = {"storeys": 0, "walls": 0, "openings": 0, "counters": 0}

    def run(command):
        history.execute(command)
        return command

    for i in range(int(record["storeys"])):
        height = float(record["storey_h_mm"])
        run(bim_commands.add_story(tr("Tầng {n}").format(n=i + 1),
                                   i * height, height))
        st = building_of(scene).stories[-1]
        counts["storeys"] += 1

        # The room plate: what the drawings trace and the takeoff measures.
        run(bim_commands.add_element("slab", st["id"], {
            "outline_mm": [[0.0, 0.0], [w, 0.0], [w, d], [0.0, d]],
            "thickness_mm": 120.0,
            "building_material_id": "btct"}, rebuild=rebuild))
        counts["counters"] += 1
        run(bim_commands.add_element("zone", st["id"], {
            "outline_mm": [[200.0, 200.0], [w - 200.0, 200.0],
                           [w - 200.0, d - 200.0], [200.0, d - 200.0]],
            "name": tr("Phòng {n}").format(n=i + 1)}, rebuild=rebuild))

        # The four walls, chained corner to corner, as a hand would draw them.
        corners = [(0.0, 0.0), (w, 0.0), (w, d), (0.0, d)]
        wall_ids: list = []
        for j in range(4):
            a = corners[j]
            b = corners[(j + 1) % 4]
            run(bim_commands.add_element("wall", st["id"], {
                "baseline_start_mm": [a[0], a[1]],
                "baseline_end_mm": [b[0], b[1]],
                "thickness_mm": 200.0, "height_mm": height,
                "top_link": "next" if i + 1 < int(record["storeys"])
                else "none",
                "building_material_id": material}, rebuild=rebuild))
            counts["walls"] += 1
            wall_ids.append(str(building_of(scene).elements[-1]["id"]))

        # Openings, placed by RATIO along their wall so a wider house keeps
        # them proportionally where the preset meant them.
        from core.building.model import building_of as _bof

        walls = [_bof(scene).element(one) for one in wall_ids]
        front, back = walls[0], walls[2]
        left, right = walls[3], walls[1]
        for host, spec in ((front, record.get("front_openings") or ()),
                           (left, record.get("side_openings") or ())):
            if host is None:
                continue
            params = host.get("params") or {}
            a = params.get("baseline_start_mm") or [0.0, 0.0]
            b = params.get("baseline_end_mm") or [0.0, 0.0]
            length = ((float(b[0]) - float(a[0])) ** 2
                      + (float(b[1]) - float(a[1])) ** 2) ** 0.5
            for kind, ratio, width, height_mm, sill in spec:
                run(bim_commands.add_element(kind, st["id"], {
                    "host_wall_id": str(host["id"]),
                    "offset_along_wall_mm": round(length * float(ratio), 1),
                    "width_mm": float(width), "height_mm": float(height_mm),
                    "sill_height_mm": float(sill),
                    "name": f"{'D' if kind == 'door' else 'W'}{counts['openings'] + 1}"},
                    rebuild=rebuild))
                counts["openings"] += 1

        for spec in record.get("partitions_mm") or ():
            run(bim_commands.add_element("wall", st["id"], {
                "baseline_start_mm": [float(spec[0]), float(spec[1])],
                "baseline_end_mm": [float(spec[2]), float(spec[3])],
                "thickness_mm": 110.0, "height_mm": height,
                "building_material_id": "gach"}, rebuild=rebuild))
            counts["walls"] += 1
        del back, right

        if record.get("curtain_wall_mm") and i == 0:
            run(bim_commands.add_element("curtain_wall", st["id"], {
                "baseline_start_mm": [2000.0, 0.0],
                "baseline_end_mm": [2000.0 + float(record["curtain_wall_mm"]),
                                    0.0],
                "thickness_mm": 100.0, "height_mm": height - 600.0,
                "frame_depth_mm": 100.0}, rebuild=rebuild))
            counts["curtain"] = counts.get("curtain", 0) + 1

    if str(record.get("roof")) == "flat":
        last = building_of(scene).stories[-1]
        run(bim_commands.add_element("roof", last["id"], {
            "outline_mm": [[-500.0, -500.0], [w + 500.0, -500.0],
                           [w + 500.0, d + 500.0], [-500.0, d + 500.0]],
            "thickness_mm": 150.0, "slope_deg": 0.0, "overhang_mm": 500.0,
            "height_mm": float(record["storey_h_mm"]),
            "top_link": "none", "building_material_id": "btct"},
            rebuild=rebuild))
    return building_of(scene), counts
