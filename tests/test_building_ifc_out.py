# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Marco Sumari Tellez and IngeTrazo contributors.
"""The parametric building through IFC4, read back by a real consumer.

The E2E script proves the file is WRITTEN; these prove a foreign IFC
implementation reads the SAME objects back, with the classes and the
counts the model states. ifcopenshell is a dev-only dependency, so the
module skips when it is missing.
"""
from __future__ import annotations

import collections

import pytest

ifcopenshell = pytest.importorskip("ifcopenshell")
import ifcopenshell.util.element  # noqa: E402
import ifcopenshell.validate  # noqa: E402

from core.building.builder import build  # noqa: E402
from core.building.model import Building  # noqa: E402
from core.scene import Scene  # noqa: E402
from formats.ifc import save_building_ifc  # noqa: E402


def _house() -> Building:
    """One storey holding one of every type with an IFC class."""
    b = Building()
    b.project["name"] = "Nhà mẫu"
    g = b.add_story("Tầng 1", 0.0, 3300.0)
    wall = b.add_element("wall", g["id"], {
        "baseline_start_mm": [0, 0], "baseline_end_mm": [6000, 0],
        "thickness_mm": 200.0, "height_mm": 3300.0})
    b.add_element("wall", g["id"], {
        "baseline_start_mm": [0, 0], "baseline_end_mm": [0, 5000],
        "thickness_mm": 200.0, "height_mm": 3300.0})
    b.add_element("door", g["id"], {
        "host_wall_id": wall["id"], "offset_along_wall_mm": 3000.0,
        "width_mm": 900.0, "height_mm": 2200.0, "name": "D1"})
    b.add_element("window", g["id"], {
        "host_wall_id": wall["id"], "offset_along_wall_mm": 5000.0,
        "width_mm": 1200.0, "height_mm": 1400.0,
        "sill_height_mm": 900.0, "name": "W1"})
    b.add_element("slab", g["id"], {
        "outline_mm": [[0, 0], [6000, 0], [6000, 5000], [0, 5000]],
        "thickness_mm": 150.0})
    b.add_element("column", g["id"], {
        "center_mm": [3000.0, 2500.0], "width_mm": 300.0,
        "depth_mm": 300.0, "height_mm": 3300.0})
    b.add_element("beam", g["id"], {
        "start_mm": [0.0, 0.0], "end_mm": [6000.0, 0.0],
        "width_mm": 220.0, "depth_mm": 300.0, "height_mm": 3000.0})
    b.add_element("roof", g["id"], {
        "outline_mm": [[0, 0], [6000, 0], [6000, 5000], [0, 5000]],
        "thickness_mm": 200.0, "slope_deg": 25.0})
    b.add_element("stair", g["id"], {
        "path_mm": [[500.0, 500.0], [500.0, 3000.0]],
        "width_mm": 1000.0, "tread_mm": 260.0})
    b.add_element("fixture", g["id"], {
        "center_mm": [1000.0, 4000.0], "kind": "wc"})
    zone = b.add_element("zone", g["id"], {
        "outline_mm": [[300, 300], [5700, 300], [5700, 4700], [300, 4700]],
        "name": "Phòng khách"})
    for element in list(b.elements):
        try:
            build(b, element)
        except ValueError:
            pass
    return b


@pytest.fixture(scope="module")
def exported(tmp_path_factory):
    b = _house()
    path = tmp_path_factory.mktemp("bim_ifc") / "nha.ifc"
    count = save_building_ifc(Scene(), str(path), b, "Nhà mẫu")
    return ifcopenshell.open(str(path)), b, count


def test_every_element_reaches_the_file_as_its_own_class(exported):
    """The count is by TYPE, and every type is the class the schema names."""
    model, b, count = exported
    assert count == len(b.elements)
    made = collections.Counter(
        e.is_a() for e in model.by_type("IfcProduct")
        if e.is_a() not in ("IfcBuilding", "IfcSite", "IfcBuildingStorey"))
    assert made["IfcWall"] == 2
    assert made["IfcDoor"] == 1
    assert made["IfcWindow"] == 1
    assert made["IfcSlab"] == 1
    assert made["IfcColumn"] == 1
    assert made["IfcBeam"] == 1
    assert made["IfcRoof"] == 1
    assert made["IfcStair"] == 1
    assert made["IfcSanitaryTerminal"] == 1
    assert made["IfcSpace"] == 1


def test_the_door_cuts_its_wall_through_a_void_the_schema_knows(exported):
    """IfcRelVoidsElement → IfcOpeningElement → IfcRelFillsElement."""
    model, _b, _n = exported
    doors = model.by_type("IfcDoor")
    assert doors
    voids = []
    for door in doors:
        for rel in model.by_type("IfcRelFillsElement"):
            if rel.RelatedBuildingElement == door:
                voids.append(rel.RelatingOpeningElement)
    assert len(voids) == 1, "mỗi cửa phải điền vào một lỗ mở"
    walls = model.by_type("IfcWall")
    hosting = [w for w in walls
               if any(r.RelatingBuildingElement == w
                      for r in model.by_type("IfcRelVoidsElement")
                      if r.RelatedOpeningElement in voids)]
    assert len(hosting) == 1, "lỗ mở phải thuộc đúng một tường"


def test_the_room_survives_with_its_name_and_no_geometry(exported):
    """A zone is an area, not a solid: it must still be in the file."""
    model, _b, _n = exported
    spaces = model.by_type("IfcSpace")
    assert len(spaces) == 1
    assert spaces[0].LongName == "Phòng khách"


def test_the_quantities_a_consumer_reads_are_the_takeoff_numbers(exported):
    """Areas and volumes come from the model, not from the file's author."""
    model, b, _n = exported
    from core.building.takeoff import tables

    walls = model.by_type("IfcWall")
    assert walls
    qsets = []
    for wall in walls:
        for rel in wall.IsDefinedBy:
            if rel.is_a("IfcRelDefinesByProperties"):
                qsets.append(rel.RelatingPropertyDefinition)
    assert qsets, "tường phải có bảng khối lượng"
    # GrossSideArea is the area a priced bill is written from — the same
    # number the takeoff's own column states. NetSideArea is the wall minus
    # its openings; the two must not be confused (summing both doubles it).
    gross = sum(
        q.AreaValue for qs in qsets
        for q in getattr(qs, "Quantities", [])
        if q.Name == "GrossSideArea" and getattr(q, "AreaValue", None))
    metrado = tables(b)["totals"]["wall_area_m2"]
    assert gross == pytest.approx(metrado, rel=0.02), \
        f"IFC {gross:.2f} vs metrado {metrado:.2f}"
    net = sum(
        q.AreaValue for qs in qsets
        for q in getattr(qs, "Quantities", [])
        if q.Name == "NetSideArea" and getattr(q, "AreaValue", None))
    assert net < gross, "diện tích thực phải nhỏ hơn diện tích tính tiền"
