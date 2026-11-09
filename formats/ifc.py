# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Marco Sumari Tellez and IngeTrazo contributors.
"""IFC4 export — tagged BIM objects to a STEP Physical File, by hand.

Only what the thesis needs, written without dependencies: IFC4 is a text
format (ISO 10303-21) and our export scope is narrow — the spatial skeleton
(project → site → building → storey), one element per tagged BIM object with
its REAL IFC class, faceted-BRep geometry in world metres, and BaseQuantities
(area, and volume when the object is watertight) so downstream takeoff tools
read the numbers straight from the file. Untagged geometry is not exported —
the tag IS the opt-in, per the project's freeform-first principle.

ifcopenshell stays out deliberately: heavy native wheels lag Python releases
(the ARM/3.14 risk noted in CLAUDE.md), and import can be added later without
it constraining the writer.
"""
from __future__ import annotations

import datetime
import math
import uuid
from pathlib import Path

from core.bim import class_quantities, collect_objects, face_set_volume

_GUID_CHARS = ("0123456789ABCDEFGHIJKLMNOPQRSTUVWXYZ"
               "abcdefghijklmnopqrstuvwxyz_$")

#: IFC4 total attribute counts per element class (the first 8 are the common
#: GlobalId..Tag layout; the rest are padded with ``$``). Classes with quirky
#: layouts (doors/windows carry OverallHeight/Width…, IfcSpace has LongName
#: where others have Tag) just get the right pad width.
_ATTR_COUNT = {"IfcPile": 10, "IfcDoor": 13, "IfcWindow": 13, "IfcSpace": 11,
               "IfcReinforcingBar": 14}
_DEFAULT_ATTRS = 9


def ifc_guid() -> str:
    """A 22-character IFC compressed GUID (base-64 over the IFC alphabet)."""
    n = uuid.uuid4().int
    return "".join(_GUID_CHARS[(n >> (6 * i)) & 63] for i in range(21, -1, -1))


def _s(text: str) -> str:
    """IFC string literal: apostrophes doubled, non-ASCII as \\X2\\…\\X0\\."""
    out = []
    run: list[str] = []

    def flush():
        if run:
            out.append("\\X2\\" + "".join(f"{ord(c):04X}" for c in run)
                       + "\\X0\\")
            run.clear()

    for ch in text or "":
        if ord(ch) < 128:
            flush()
            out.append("''" if ch == "'" else ch)
        else:
            run.append(ch)
    flush()
    return "'" + "".join(out) + "'"


def _f(v: float) -> str:
    return f"{v:.6f}"


class _Writer:
    def __init__(self) -> None:
        self.lines: list[str] = []
        self._next = 1

    def add(self, entity: str, *attrs) -> int:
        eid = self._next
        self._next += 1
        self.lines.append(f"#{eid}={entity}({','.join(attrs)});")
        return eid


def _brep(w: _Writer, faces, context_id: int) -> int:
    """Faceted geometry for a face set → IfcShapeRepresentation id. Closed
    sets become an IfcFacetedBrep; open ones an IfcShellBasedSurfaceModel."""
    point_ids: dict = {}

    def pt(v) -> int:
        key = (round(v.x(), 6), round(v.y(), 6), round(v.z(), 6))
        pid = point_ids.get(key)
        if pid is None:
            pid = w.add("IFCCARTESIANPOINT",
                        f"({_f(key[0])},{_f(key[1])},{_f(key[2])})")
            point_ids[key] = pid
        return pid

    face_ids = []
    for f in faces:
        bounds = []
        outer = w.add("IFCPOLYLOOP",
                      "(" + ",".join(f"#{pt(v.position)}" for v in f.loop)
                      + ")")
        bounds.append(f"#{w.add('IFCFACEOUTERBOUND', f'#{outer}', '.T.')}")
        for h in f.hole_loops:
            loop = w.add("IFCPOLYLOOP",
                         "(" + ",".join(f"#{pt(v.position)}" for v in h) + ")")
            bounds.append(f"#{w.add('IFCFACEBOUND', f'#{loop}', '.T.')}")
        face_ids.append(w.add("IFCFACE", "(" + ",".join(bounds) + ")"))

    face_list = "(" + ",".join(f"#{i}" for i in face_ids) + ")"
    closed = face_set_volume(faces) is not None
    if closed:
        shell = w.add("IFCCLOSEDSHELL", face_list)
        item = w.add("IFCFACETEDBREP", f"#{shell}")
        rep_type = "'Brep'"
    else:
        shell = w.add("IFCOPENSHELL", face_list)
        item = w.add("IFCSHELLBASEDSURFACEMODEL", f"(#{shell})")
        rep_type = "'SurfaceModel'"
    return w.add("IFCSHAPEREPRESENTATION", f"#{context_id}", "'Body'",
                 rep_type, f"(#{item})")


def save_ifc(scene, path, project_name: str = "IngeTrazo project") -> int:
    """Write every tagged BIM object to ``path`` as IFC4. Returns how many
    elements were exported; raises ``ValueError`` when nothing is tagged."""
    objects = collect_objects(scene)
    if not objects:
        raise ValueError("No tagged BIM objects to export")

    w = _Writer()
    origin = w.add("IFCCARTESIANPOINT", "(0.,0.,0.)")
    axis = w.add("IFCAXIS2PLACEMENT3D", f"#{origin}", "$", "$")
    context = w.add("IFCGEOMETRICREPRESENTATIONCONTEXT",
                    "$", "'Model'", "3", "1.E-5", f"#{axis}", "$")
    units = [
        w.add("IFCSIUNIT", "*", ".LENGTHUNIT.", "$", ".METRE."),
        w.add("IFCSIUNIT", "*", ".AREAUNIT.", "$", ".SQUARE_METRE."),
        w.add("IFCSIUNIT", "*", ".VOLUMEUNIT.", "$", ".CUBIC_METRE."),
    ]
    unit_assign = w.add("IFCUNITASSIGNMENT",
                        "(" + ",".join(f"#{u}" for u in units) + ")")
    project = w.add("IFCPROJECT", _s(ifc_guid()), "$", _s(project_name),
                    "$", "$", "$", "$", f"(#{context})", f"#{unit_assign}")
    placement = w.add("IFCLOCALPLACEMENT", "$", f"#{axis}")
    site = w.add("IFCSITE", _s(ifc_guid()), "$", "'Site'", "$", "$",
                 f"#{placement}", "$", "$", ".ELEMENT.",
                 "$", "$", "$", "$", "$")
    building = w.add("IFCBUILDING", _s(ifc_guid()), "$", "'Building'", "$",
                     "$", f"#{placement}", "$", "$", ".ELEMENT.",
                     "$", "$", "$")
    storey = w.add("IFCBUILDINGSTOREY", _s(ifc_guid()), "$", "'Storey'", "$",
                   "$", f"#{placement}", "$", "$", ".ELEMENT.", "0.")
    w.add("IFCRELAGGREGATES", _s(ifc_guid()), "$", "$", "$",
          f"#{project}", f"(#{site})")
    w.add("IFCRELAGGREGATES", _s(ifc_guid()), "$", "$", "$",
          f"#{site}", f"(#{building})")
    w.add("IFCRELAGGREGATES", _s(ifc_guid()), "$", "$", "$",
          f"#{building}", f"(#{storey})")

    element_ids = []
    for obj in objects:
        faces = obj.get("faces") or list(obj["group"].mesh.faces)
        if not faces:
            continue
        rep = _brep(w, faces, context)
        pds = w.add("IFCPRODUCTDEFINITIONSHAPE", "$", "$", f"(#{rep})")
        from core.bim import IFC_CLASSES
        cls = obj["class"] if obj["class"] in IFC_CLASSES \
            else "IfcBuildingElementProxy"
        qset_name, qentries, _metrado = class_quantities(obj["class"], faces)
        total = _ATTR_COUNT.get(cls, _DEFAULT_ATTRS)
        attrs = [_s(ifc_guid()), "$", _s(obj["name"] or cls), "$", "$",
                 f"#{placement}", f"#{pds}", "'IngeTrazo'"]
        if cls in ("IfcDoor", "IfcWindow"):
            # Attributes 9/10 are OverallHeight/OverallWidth — viewers and
            # schedules read the leaf dimensions from here.
            dims = {name: val for kind, name, val in qentries
                    if kind == "length"}
            attrs.append(_f(dims["Height"]) if "Height" in dims else "$")
            attrs.append(_f(dims["Width"]) if "Width" in dims else "$")
        if cls == "IfcReinforcingBar":
            # Tag, SteelGrade, then NominalDiameter, CrossSectionArea and
            # BarLength: what a bar schedule reads (#495).
            dims = {name: val for kind, name, val in qentries
                    if kind == "length"}
            d = dims.get("NominalDiameter")
            attrs += ["$",
                      _f(d) if d is not None else "$",
                      _f(math.pi * d * d / 4.0) if d is not None else "$",
                      _f(dims["Length"]) if "Length" in dims else "$",
                      ".NOTDEFINED."]
        attrs += ["$"] * (total - len(attrs))
        elem = w.add(cls.upper(), *attrs)
        element_ids.append(elem)

        # Per-class BaseQuantities (Qto_* naming): the takeoff numbers in
        # the budget's own measures, straight in the file.
        _Q_ENTITY = {"area": "IFCQUANTITYAREA", "volume": "IFCQUANTITYVOLUME",
                     "length": "IFCQUANTITYLENGTH",
                     "weight": "IFCQUANTITYWEIGHT"}
        quantities = [
            f"#{w.add(_Q_ENTITY[kind], _s(name), '$', '$', _f(val), '$')}"
            for kind, name, val in qentries
        ]
        if quantities:
            eq = w.add("IFCELEMENTQUANTITY", _s(ifc_guid()), "$",
                       _s(qset_name), "$", "$",
                       "(" + ",".join(quantities) + ")")
            w.add("IFCRELDEFINESBYPROPERTIES", _s(ifc_guid()), "$", "$", "$",
                  f"(#{elem})", f"#{eq}")

    if not element_ids:
        raise ValueError("No tagged BIM objects to export")
    w.add("IFCRELCONTAINEDINSPATIALSTRUCTURE", _s(ifc_guid()), "$", "$", "$",
          "(" + ",".join(f"#{e}" for e in element_ids) + ")", f"#{storey}")

    stamp = datetime.datetime.now().strftime("%Y-%m-%dT%H:%M:%S")
    name = Path(path).name.replace("'", "''")
    header = (
        "ISO-10303-21;\n"
        "HEADER;\n"
        "FILE_DESCRIPTION((''),'2;1');\n"
        f"FILE_NAME('{name}','{stamp}',('IngeTrazo'),('IngeTrazo'),"
        "'IngeTrazo','IngeTrazo','');\n"
        "FILE_SCHEMA(('IFC4'));\n"
        "ENDSEC;\n"
        "DATA;\n"
    )
    footer = "ENDSEC;\nEND-ISO-10303-21;\n"
    Path(path).write_text(header + "\n".join(w.lines) + "\n" + footer,
                          encoding="ascii")
    return len(element_ids)

# ---- the parametric building -------------------------------------------------
# ``save_ifc`` above exports TAGGED freeform geometry: the tag is the opt-in.
# A parametric building is different — every element is already a BIM object,
# so the writer reads the model itself: one storey per level (not one hardcoded
# storey at 0), one product per element in ITS storey, openings tied to their
# host wall with IfcRelVoidsElement, rooms as IfcSpace, and the quantities the
# element builders computed (``derived``) written straight in.

#: Quantity key -> (IFC entity, unit name). Keyed on the suffix the builders
#: write, so ``net_area_m2`` bills as an area and ``volume_m3`` as a volume
#: without a per-class table here.
_Q_OF_KEY = (
    ("_area_m2", "IFCQUANTITYAREA", "Area"),
    ("_volume_m3", "IFCQUANTITYVOLUME", "Volume"),
    ("_length_mm", "IFCQUANTITYLENGTH", "Length"),
    ("_height_mm", "IFCQUANTITYLENGTH", "Height"),
    ("_top_mm", "IFCQUANTITYLENGTH", "Height"),
    ("_count", "IFCQUANTITYCOUNT", "Count"),
)

#: The named quantity each built key bills under, in the reader's vocabulary.
_Q_NAMES = {
    "net_area_m2": ("IFCQUANTITYAREA", "NetSideArea"),
    "gross_area_m2": ("IFCQUANTITYAREA", "GrossSideArea"),
    "area_m2": ("IFCQUANTITYAREA", "GrossArea"),
    "volume_m3": ("IFCQUANTITYVOLUME", "NetVolume"),
    "length_mm": ("IFCQUANTITYLENGTH", "Length"),
    "effective_height_mm": ("IFCQUANTITYLENGTH", "Height"),
    "effective_top_mm": ("IFCQUANTITYLENGTH", "Height"),
}

#: Element kinds whose product is a void-forming opening inside a host.
_OPENING_KINDS = ("door", "window", "curtain_wall")


def _qset_name(ifc_class: str) -> str:
    """The Qto_* set the quantities belong to, per class."""
    base = ifc_class[3:] if ifc_class.startswith("Ifc") else ifc_class
    return f"Qto_{base}BaseQuantities"


def _quantity_entities(w, derived) -> list:
    """``[#id, ...]`` — the IFCQUANTITY* for the element's built numbers."""
    out = []
    for key, (entity, name) in _Q_NAMES.items():
        value = (derived or {}).get(key)
        try:
            number = float(value)
        except (TypeError, ValueError):
            continue
        out.append(w.add(entity, _s(name), "$", "$", _f(number), "$"))
    return out


def save_building_ifc(scene, path, building=None, project_name: str = "") -> int:
    """Write the parametric building to ``path`` as IFC4. Returns the element
    count; raises ``ValueError`` when the building has nothing to export."""
    from core.building import builder as builders
    from core.building import elements as schemas
    from core.building import model as building_model
    from core.building.scene_sync import group_for

    building = building or building_model.building_of(scene)
    if not building.elements and not building.stories:
        raise ValueError("Không có cấu kiện BIM nào để xuất.")

    name = str(project_name or building.project.get("name")
               or "IngeTrazo project")
    w = _Writer()
    origin = w.add("IFCCARTESIANPOINT", "(0.,0.,0.)")
    axis = w.add("IFCAXIS2PLACEMENT3D", f"#{origin}", "$", "$")
    context = w.add("IFCGEOMETRICREPRESENTATIONCONTEXT",
                    "$", "'Model'", "3", "1.E-5", f"#{axis}", "$")
    units = [
        w.add("IFCSIUNIT", "*", ".LENGTHUNIT.", "$", ".METRE."),
        w.add("IFCSIUNIT", "*", ".AREAUNIT.", "$", ".SQUARE_METRE."),
        w.add("IFCSIUNIT", "*", ".VOLUMEUNIT.", "$", ".CUBIC_METRE."),
    ]
    unit_assign = w.add("IFCUNITASSIGNMENT",
                        "(" + ",".join(f"#{u}" for u in units) + ")")
    project = w.add("IFCPROJECT", _s(ifc_guid()), "$", _s(name),
                    "$", "$", "$", "$", f"(#{context})", f"#{unit_assign}")
    placement = w.add("IFCLOCALPLACEMENT", "$", f"#{axis}")
    # The site and the building carry the JOB's own names where the office
    # gave them: a receiving tool shows «CÔNG TRÌNH» from its IFC tree, and
    # a file whose every building is called «Building» makes the reader
    # open the model to find out which job they are looking at.
    job = building.project
    site_name = str(job.get("address") or job.get("name") or "Site")
    building_name = str(job.get("name") or "Building")
    site = w.add("IFCSITE", _s(ifc_guid()), "$", _s(site_name), "$", "$",
                 f"#{placement}", "$", "$", ".ELEMENT.",
                 "$", "$", "$", "$", "$")
    building_id = w.add("IFCBUILDING", _s(ifc_guid()), "$", _s(building_name),
                        "$", "$", f"#{placement}", "$", "$", ".ELEMENT.",
                        "$", "$", "$")
    w.add("IFCRELAGGREGATES", _s(ifc_guid()), "$", "$", "$",
          f"#{project}", f"(#{site})")
    w.add("IFCRELAGGREGATES", _s(ifc_guid()), "$", "$", "$",
          f"#{site}", f"(#{building_id})")

    # One storey per level, at its real elevation (metres).
    storey_ids: dict = {}
    for story in building.stories:
        z_m = float(story.get("z_mm", 0.0)) / 1000.0
        at = w.add("IFCCARTESIANPOINT", f"(0.,0.,{_f(z_m)})")
        spot = w.add("IFCAXIS2PLACEMENT3D", f"#{at}", "$", "$")
        place = w.add("IFCLOCALPLACEMENT", f"#{placement}", f"#{spot}")
        storey_ids[str(story["id"])] = w.add(
            "IFCBUILDINGSTOREY", _s(ifc_guid()), "$",
            _s(str(story.get("name") or "")), "$", "$", f"#{place}",
            "$", "$", ".ELEMENT.", _f(z_m))
    w.add("IFCRELAGGREGATES", _s(ifc_guid()), "$", "$", "$",
          f"#{building_id}",
          "(" + ",".join(f"#{s}" for s in storey_ids.values()) + ")")

    by_storey: dict = {sid: [] for sid in storey_ids}
    products: dict = {}
    openings_by_host: dict = {}
    made = 0
    for element in building.elements:
        kind = str(element.get("type") or "")
        story_id = str(element.get("story_id") or "")
        if story_id not in storey_ids:
            continue
        derived = element.get("derived") or {}
        try:
            mesh, computed = builders.build(building, element)
            derived = {**(computed or {}), **derived}
        except ValueError:
            mesh = None
        group = group_for(scene, str(element["id"]))
        faces = list(mesh.faces) if mesh is not None and mesh.faces else (
            list(group.mesh.faces) if group is not None else [])
        ifc_class = schemas.IFC_CLASS_OF.get(kind, "IfcBuildingElementProxy")
        if kind == "zone":
            ifc_class = "IfcSpace"
        label = str((element.get("params") or {}).get("name") or
                    ifc_class)
        if len(faces) < 3:
            # An area-only element (a room) still has a place in the model:
            # export it without geometry rather than dropping the room.
            if kind != "zone":
                continue
            pds = "$"
        else:
            rep = _brep(w, faces, context)
            pds = f"#{w.add('IFCPRODUCTDEFINITIONSHAPE', '$', '$', f'(#{rep})')}"
        total = _ATTR_COUNT.get(ifc_class, _DEFAULT_ATTRS)
        attrs = [_s(ifc_guid()), "$", _s(label), "$", "$",
                 f"#{placement}", pds, "'IngeTrazo'"]
        if ifc_class == "IfcSpace":
            # IfcSpace's 8th attribute is LongName (not Tag) and its 9th is
            # CompositionType, an enumeration — a name there is a schema error.
            attrs[7] = _s(label)
            attrs += [".ELEMENT.", "$", "$"]
        attrs += ["$"] * (total - len(attrs))
        product = w.add(ifc_class.upper(), *attrs)
        products[str(element["id"])] = (product, ifc_class)
        by_storey[story_id].append(product)
        made += 1

        quantities = _quantity_entities(w, derived)
        if quantities:
            eq = w.add("IFCELEMENTQUANTITY", _s(ifc_guid()), "$",
                       _s(_qset_name(ifc_class)), "$", "$",
                       "(" + ",".join(f"#{q}" for q in quantities) + ")")
            w.add("IFCRELDEFINESBYPROPERTIES", _s(ifc_guid()), "$", "$", "$",
                  f"(#{product})", f"#{eq}")
        if kind in _OPENING_KINDS:
            host_id = str((element.get("params") or {}).get(
                "host_wall_id") or "")
            if host_id:
                # IFC4's void relation points at an IfcOpeningElement — a
                # feature element — never at the door itself; the door then
                # FILLS that void. A door under IfcRelVoidsElement is a schema
                # error, which is what a validator catches first.
                void_attrs = [_s(ifc_guid()), "$", _s(label + " (lỗ mở)"),
                              "$", "$", f"#{placement}",
                              pds if pds != "$" else "$", "'IngeTrazo'",
                              ".NOTDEFINED."]
                void = w.add("IFCOPENINGELEMENT", *void_attrs)
                openings_by_host.setdefault(host_id, []).append((void,
                                                                 product))

    if not made:
        raise ValueError("Không có cấu kiện BIM nào để xuất.")

    # Each wall carries the openings that pierce it: the opening products are
    # aggregated under the wall and a void relation says what they cut.
    for host_id, openings in openings_by_host.items():
        host = products.get(str(host_id))
        if host is None:
            continue
        host_product = host[0]
        for void, filler in openings:
            w.add("IFCRELVOIDSELEMENT", _s(ifc_guid()), "$", "$", "$",
                  f"#{host_product}", f"#{void}")
            w.add("IFCRELFILLSELEMENT", _s(ifc_guid()), "$", "$", "$",
                  f"#{void}", f"#{filler}")

    for story_id, ids in by_storey.items():
        if not ids:
            continue
        w.add("IFCRELCONTAINEDINSPATIALSTRUCTURE", _s(ifc_guid()), "$",
              "$", "$", "(" + ",".join(f"#{i}" for i in ids) + ")",
              f"#{storey_ids[story_id]}")

    stamp = datetime.datetime.now().strftime("%Y-%m-%dT%H:%M:%S")
    file_name = Path(path).name.replace("'", "''")
    header = (
        "ISO-10303-21;\n"
        "HEADER;\n"
        "FILE_DESCRIPTION((''),'2;1');\n"
        f"FILE_NAME('{file_name}','{stamp}',('IngeTrazo'),('IngeTrazo'),"
        "'IngeTrazo','IngeTrazo','');\n"
        "FILE_SCHEMA(('IFC4'));\n"
        "ENDSEC;\n"
        "DATA;\n"
    )
    footer = "ENDSEC;\nEND-ISO-10303-21;\n"
    Path(path).write_text(header + "\n".join(w.lines) + "\n" + footer,
                          encoding="ascii")
    return made
