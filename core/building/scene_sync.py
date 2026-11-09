# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Marco Sumari Tellez and IngeTrazo contributors.
"""The bridge between the building model and the scene.

The scene holds the *cache*: one :class:`~core.group.Group` per built element,
named with its type and id, carrying the element id in ``group.ext["building"]``
so a rebuild can find it again — and so the Browser, the layers and the
selections can tell a parametric element from freeform drawing.

Rebuilding is idempotent and cheap to call: :func:`sync` compares what each
element's group last built from with what its parameters say now, and only
rebuilds what changed. That signature is what makes "edit a wall thickness and
the drawings, the takeoff and the IFC all follow" true without re-solving the
whole model on every keystroke.

Undo works the other way round: the parameters are restored, and the geometry
is rebuilt from them. Nothing about the mesh is remembered, because nothing
about the mesh is the truth.
"""
from __future__ import annotations

from core.building import builder as builders
from core.building import elements as schemas
from core.building import model as building_model
from core.group import Group

#: The ``group.ext`` key this feature owns.
EXT_KEY = "building"


def _signature(building, element) -> tuple:
    """What an element's geometry depends on — the rebuild trigger."""
    story = building.story(str(element.get("story_id") or ""))
    above = builders.story_above(building, story)
    params = element.get("params") or {}
    # Anything the builder reads that is not in params: the storey it sits on,
    # the storey above (for linked tops), and every opening that pierces it.
    children = ()
    if element.get("type") == "wall":
        children = tuple(sorted(
            (str(c.get("id")), _freeze(c.get("params") or {}))
            for c in building.elements
            if c.get("type") in schemas.OPENING_TYPES
            and str((c.get("params") or {}).get("host_wall_id") or "")
            == str(element.get("id"))))
    neighbours = ()
    if element.get("type") == "wall" and story is not None:
        neighbours = tuple(sorted(
            str(w.get("id")) for w in building.on_story(str(story["id"]),
                                                        "wall")))
    return (
        str(element.get("type")),
        _freeze(params),
        float((story or {}).get("z_mm", 0.0)),
        float((above or {}).get("z_mm", -1.0)),
        children,
        neighbours,
    )


def _same_signature(stored, signature) -> bool:
    """Compare a signature against the one a group carries.

    The stored copy went through JSON (``.igz``), where tuples are lists, so
    the comparison normalises both sides the same way — otherwise a reopened
    document rebuilds everything once for no reason.
    """
    if stored is None:
        return False
    import json
    return stored == json.loads(json.dumps(list(signature)))


def _freeze(value):
    """A hashable, order-stable copy of a JSON-ish value."""
    if isinstance(value, dict):
        return tuple(sorted((str(k), _freeze(v)) for k, v in value.items()))
    if isinstance(value, (list, tuple)):
        return tuple(_freeze(v) for v in value)
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return float(value)
    return str(value)


def group_for(scene, element_id: str):
    """The scene group an element's geometry lives in, or ``None``."""
    key = str(element_id)
    for group in scene.groups:
        ext = getattr(group, "ext", None)
        if isinstance(ext, dict) and str(
                (ext.get(EXT_KEY) or {}).get("id") or "") == key:
            return group
    return None


def sync(scene, building=None, element_ids=None, force: bool = False):
    """Bring the scene's geometry in line with the building's parameters.

    ``element_ids`` limits the work to those elements (plus the walls that
    host them); ``force`` rebuilds even when the signature matches — what a
    load-from-disk or a material change needs.

    Returns ``(built, removed)`` element counts.
    """
    building = building or building_model.building_of(scene)
    wanted = {str(el["id"]) for el in building.elements}
    removed = 0
    for group in list(scene.groups):
        ext = getattr(group, "ext", None)
        if not isinstance(ext, dict) or EXT_KEY not in ext:
            continue
        eid = str((ext.get(EXT_KEY) or {}).get("id") or "")
        if eid not in wanted:
            scene.groups.remove(group)
            removed += 1

    # Which elements to touch: the ones asked for, plus every wall that hosts
    # one of them (an opening's geometry is the wall's business).
    if element_ids is None:
        targets = list(building.elements)
    else:
        ids = {str(i) for i in element_ids}
        for eid in list(ids):
            el = building.element(eid)
            if el is None:
                continue
            if el.get("type") in schemas.OPENING_TYPES:
                host = (el.get("params") or {}).get("host_wall_id")
                if host:
                    ids.add(str(host))
        targets = [el for el in building.elements if str(el["id"]) in ids]

    built = 0
    errors = []
    for element in targets:
        signature = _signature(building, element)
        group = group_for(scene, str(element["id"]))
        if not force and group is not None:
            ext = group.ext or {}
            if _same_signature(ext.get(EXT_KEY, {}).get("sig"), signature):
                continue
        try:
            mesh, derived = builders.build(building, element)
        except ValueError as exc:
            errors.append((str(element["id"]), str(exc)))
            continue
        if mesh is None:
            # Area data (a zone): keep the parameters, draw nothing.
            if group is not None:
                scene.groups.remove(group)
            _write_derived(scene, building, element, derived)
            built += 1
            continue
        if group is None:
            group = Group(name=_group_name(element))
            group.component = False
            scene.groups.append(group)
        group.mesh = mesh
        group.name = _group_name(element)
        group.ifc = {"class": schemas.IFC_CLASS_OF.get(
            str(element.get("type")), "IfcBuildingElementProxy"),
            "name": group.name}
        ext = dict(group.ext or {})
        ext[EXT_KEY] = {"id": str(element["id"]),
                        "type": str(element.get("type")),
                        "sig": list(signature)}
        group.ext = ext
        _apply_material(scene, group, element)
        _write_derived(scene, building, element, derived)
        built += 1

    if built or removed:
        scene.version += 1
    if errors:
        scene.building_errors = errors
    return built, removed


def _group_name(element) -> str:
    params = element.get("params") or {}
    label = params.get("name")
    kind = TR_NAMES.get(str(element.get("type")), str(element.get("type")))
    return f"{kind} {label}" if label else f"{kind} {str(element['id'])[-6:]}"


#: Element type → the label the Browser and the drawings use. The English
#: source string; ``tr`` at display time.
TR_NAMES = {
    "wall": "Wall", "door": "Door", "window": "Window",
    "curtain_wall": "Curtain wall", "slab": "Slab", "ceiling": "Ceiling",
    "column": "Column", "beam": "Beam", "roof": "Roof", "stair": "Stair",
    "zone": "Zone", "fixture": "Fixture", "custom": "BIM block",
}


def _apply_material(scene, group, element) -> None:
    """Paint the body with its building material's surface colour."""
    params = element.get("params") or {}
    mid = params.get("building_material_id")
    if not mid:
        return
    record = schemas.MATERIALS.get(str(mid))
    if not record:
        return
    colour = record.get("surface_color")
    if not colour or colour == "#FFFFFF":
        return
    text = str(colour).lstrip("#")
    if len(text) != 6:
        return
    try:
        rgb = tuple(int(text[i:i + 2], 16) / 255.0 for i in (0, 2, 4))
    except ValueError:
        return
    group.material = {"color": rgb}
    for face in group.mesh.faces:
        face.attrs.setdefault("mat", str(mid))
    group.mesh._mut_serial += 1


def _write_derived(scene, building, element, derived) -> None:
    """Keep the computed quantities on the element (the takeoff reads them)."""
    if not derived:
        return
    prev = element.setdefault("derived", {})
    if prev != derived:
        prev.clear()
        prev.update(derived)
        building_model.store(scene, building)


def rebuild_all(scene, building=None) -> int:
    """Rebuild every element — what a material change or a load needs."""
    building = building or building_model.building_of(scene)
    built, _removed = sync(scene, building, force=True)
    return built
