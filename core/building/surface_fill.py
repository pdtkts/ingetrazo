# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Marco Sumari Tellez and IngeTrazo contributors.
"""WHO a cut area belongs to — the bridge from a hatched region to the
element that produced it.

A Vietnamese section is read by its hatch: concrete dense and dotted,
masonry a single 45°, earth back-slanted. One material for the whole
drawing is not that drawing — a plan with a concrete column standing in a
masonry wall showed the whole cut in the wall's pattern, so the reader
could not tell the two apart, and the one thing the hatch is FOR is
telling them apart.

The hidden-line pass returns closed cut rings without saying which solid
each came from: they are chained chords from a triangle soup, and the
soup has already lost the element. Rather than thread an identity through
the clipper (which every renderer, the composer and the DXF all share),
the attribution is recovered here, once, by asking each element's own
geometry for ITS cut rings and matching them to the drawing's.

Matching is by geometry, not by index: the same plane cuts an element's
group mesh exactly the way it cut it inside the whole scene, so the ring
is compared by its own points — a cheap bounding-box and vertex test that
is exact for the walls, columns, slabs and beams a plan is made of.
"""
from __future__ import annotations

#: How close an element ring's box must sit to a drawing ring's box to be
#: considered the same region, in model millimetres (1 mm). The two are
#: computed from the same triangles by the same arithmetic, so this is
#: floating-point slack, not a tolerance anything is allowed to hide in.
_BOX_TOL = 1.0


def _ring_box(ring) -> tuple:
    xs = [float(p[0]) for p in ring]
    ys = [float(p[1]) for p in ring]
    return (min(xs), min(ys), max(xs), max(ys))


def _boxes_match(a: tuple, b: tuple) -> bool:
    return all(abs(float(u) - float(v)) <= _BOX_TOL
               for u, v in zip(a, b))


#: Rounding used to build a ring's signature, in model millimetres. The
#: drawing's ring and the element's are the same loop computed twice from
#: the same triangles, so they agree to far more places than this; the
#: rounding is here so a signature is a small hashable tuple rather than a
#: list of floats compared one by one.
_SIG_DECIMALS = 3


def _ring_signature(ring) -> tuple:
    """The ring's own vertex set, order-independent.

    Two runs of the same clipper produce the same points possibly in a
    different rotation or direction, so the set — not the sequence — is
    what identifies the region."""
    return tuple(sorted(
        (round(float(p[0]), _SIG_DECIMALS), round(float(p[1]), _SIG_DECIMALS))
        for p in ring))


def element_material(scene, element) -> str:
    """The ``cut_fill`` name an element's own material table entry carries.

    Empty when the element names no material: the drawing then falls back
    to the caller's own default, exactly as it did before any of this
    existed, so a model built before the material tables arrived still
    prints.
    """
    from core.building import elements as schemas

    params = element.get("params") or {}
    for key in ("material_id", "building_material_id", "leaf_material_id",
                "frame_material_id"):
        name = str(params.get(key) or "")
        if not name:
            continue
        material = schemas.material(name)
        fill = str((material or {}).get("cut_fill") or "")
        if fill:
            return fill
    # Nothing named: the KIND's default material is the honest answer —
    # a column nobody specified is still concrete on the drawing.
    fill = str((schemas.material(
        (schemas.defaults_for(str(element.get("type"))) or {})
        .get("building_material_id")) or {}).get("cut_fill") or "")
    return fill


def cut_rings_per_element(scene, plane, camera=None) -> list:
    """``[(element_id, part, [rings])]`` — each element's own cut rings,
    in the SAME plane the drawing's rings are in.

    ``part`` is reserved for elements that cut in several disjoint pieces
    (a wall interrupted by a floor-to-ceiling opening, a multi-leaf
    column); it is ``0`` for everything that cuts as one region, which is
    every element today.

    ``camera`` matters: the hidden-line pass returns its rings projected
    into the CAMERA plane (that is the space the composer and the DXF
    both draw in), so the element rings are projected the same way here.
    Comparing world rings against camera rings matches nothing at all —
    which is exactly the silent failure this argument exists to prevent.

    Only VISIBLE element groups are asked, and a group whose geometry
    raises (a hosted opening whose host is gone, a curtain wall mid-edit)
    is skipped rather than sinking the drawing.
    """
    from core.building.scene_sync import EXT_KEY
    from core.group import world_mesh
    from core.hlr import _to_cam, camera_basis, clip_to_section

    project = None
    if camera is not None:
        eye, right, up, fwd = camera_basis(camera)

        def project(points):                        # noqa: F811 — the switch
            import numpy as np

            return _to_cam(np.asarray(points, dtype=float),
                           eye, right, up, fwd)[:, :2]

    out: list = []
    for group in getattr(scene, "groups", None) or ():
        ext = getattr(group, "ext", None)
        if not isinstance(ext, dict):
            continue
        element_id = str((ext.get(EXT_KEY) or {}).get("id") or "")
        if not element_id:
            continue
        if not scene.entity_visible(group):
            continue
        try:
            mesh = world_mesh(group)
        except Exception:                           # noqa: BLE001 — a broken
            continue                                # element is not a crash
        tris: list = []
        for face in mesh.faces:
            for a, b, c in face.triangulate():
                tris.append(((a.x(), a.y(), a.z()),
                             (b.x(), b.y(), b.z()),
                             (c.x(), c.y(), c.z())))
        if not tris:
            continue
        clipped = clip_to_section(tris, [], [], plane, split_cuts=True)
        chords = clipped[3] if len(clipped) == 4 else []
        if not chords:
            continue
        from core.hlr import section_loops

        rings: list = []
        for ring in section_loops(chords):
            pts = ring[:, :2] if project is None else project(ring)
            rings.append([[float(p[0]), float(p[1])] for p in pts])
        if rings:
            out.append((element_id, 0, rings))
    return out


def material_of_ring(scene, ring, attributed, fallback: str = "") -> str:
    """The material name for one drawing ring, by matching it back to the
    element it came from; ``fallback`` when nothing matches.

    A drawing ring and an element ring are the same closed loop computed
    twice, so the test is the element ring's own vertex set against the
    drawing ring's — the drawing's points are a subset of the element's
    up to ordering, and comparing bounding boxes first keeps this linear
    in practice.
    """
    box = _ring_box(ring)
    signature = _ring_signature(ring)
    for element_id, _part, rings in attributed:
        for candidate in rings:
            # The box first (cheap, and it rejects almost everything), then
            # the ring's own vertex set. The box ALONE is not enough: a
            # column standing inside a wall's outline shares that wall's
            # box, and matching on it hatched the column as masonry — the
            # exact failure this whole module exists to prevent.
            if not _boxes_match(box, _ring_box(candidate)):
                continue
            if _ring_signature(candidate) != signature:
                continue
            element = scene_element(scene, element_id)
            if element is None:
                continue
            fill = element_material(scene, element)
            if fill:
                return fill
    return str(fallback or "")


def scene_element(scene, element_id: str):
    """The building element with this id, or ``None``."""
    from core.building.model import building_of

    try:
        building = building_of(scene)
        return building.element(element_id)
    except Exception:                                # noqa: BLE001 — a bare
        return None                                  # Scene has no building
