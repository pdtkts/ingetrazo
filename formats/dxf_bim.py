# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Marco Sumari Tellez and IngeTrazo contributors.
"""CAD out: a drawing as a DXF another CAD opens — layers, hatch, dimensions.

The ecosystem bridge is IngeCAD, and a bridge is only as good as what
crosses it. The R12 writer in :mod:`formats.dxf_out` covers lines; this one
covers what a BIM drawing actually consists of:

* **layers by trade** — the same names the model uses, so the CAD's layer
  list reads like the office's own (and a company that renames layers gets
  its own table, which is the layer map);
* **HATCH** for the cut fill and the room patterns, written as SOLID and
  pattern hatches with a boundary — an unhatched section reads as a hole;
* **TEXT** for the drawing's own words (room names, level marks) at their
  paper height, so a 1:50 plan's text is 2.5 mm on the plot whatever it
  scales to in model units;
* **DIMENSION** for the model's dimensions, written as real DIMENSION
  entities with a dimension style, so the CAD can re-associate and renumber
  them rather than inheriting dead lines.

The unit question is answered once, here: a DXF out of this module is drawn
in MODEL millimetres (what a Vietnamese CAD expects against a 1:1 plot) and
carries an ``$INSUNITS`` of millimetres.
"""
from __future__ import annotations

from pathlib import Path

#: The layer map: the model's own layer names → the names a company's CAD
#: expects. Empty by default — the model's names cross as they are, and an
#: office that has a standard renames here rather than in twenty drawings.
DEFAULT_LAYER_MAP: dict = {}

#: Pen (lineweight, mm) and colour per class of line, the trade's table.
PEN_TABLE = {
    "cut": (0.35, 7),
    "profile": (0.25, 7),
    "edge": (0.13, 7),
    "hidden": (0.13, 8),
    "dimension": (0.13, 4),
    "text": (0.18, 7),
    "hatch": (0.09, 9),
    "construction": (0.05, 253),
}


def mapped_layer(name: str, layer_map: dict | None = None) -> str:
    """The layer name a DXF gets for the model's ``name``."""
    table = layer_map if layer_map is not None else DEFAULT_LAYER_MAP
    return str(table.get(name) or name or "0").strip() or "0"


def _try_ezdxf():
    try:
        import ezdxf                               # noqa: PLC0415
        return ezdxf
    except ImportError:                            # pragma: no cover
        return None


#: AutoCAD's own lineweight ladder, in 1/100 mm. A file states one of
#: these or the reader picks for us.
_DXF_LINEWEIGHTS = (0, 5, 9, 13, 15, 18, 20, 25, 30, 35, 40, 50, 53, 60, 70,
                    80, 90, 100, 106, 120, 140, 158, 200, 211)


def _nearest_dxf_lineweight(width_mm: float) -> int:
    """The lineweight a receiving CAD can actually draw, nearest to ours.

    The ladder is read from ezdxf rather than kept here: it is the SAME
    table the writer snaps to on assignment, so a pen of 0.75 mm becomes
    the 0.80 the file will state instead of a number the writer quietly
    rounds behind our back (measured: 0.75 → 0.80, never 0.70).
    """
    wanted = max(0, int(round(float(width_mm) * 100.0)))
    try:
        from ezdxf.lldxf import const

        ladder = sorted(int(v) for v in const.VALID_DXF_LINEWEIGHTS)
    except Exception:                              # noqa: BLE001 — fallback
        ladder = list(_DXF_LINEWEIGHTS)
    up = [w for w in ladder if w >= wanted]
    down = [w for w in ladder if w <= wanted]
    # The writer's own rule: the next weight UP where one exists (a pen
    # must never come out thinner than the office asked for), else the
    # heaviest there is.
    return int(up[0] if up else (down[-1] if down else 0))


def _dxf_linetype_pattern(name: str) -> list:
    """The app's ``(dash, gap, …)`` pairs as a DXF pattern.

    DXF states a simple line type flat: ``[total, +dash, -gap, …]``, in
    drawing units. The app states it in PAPER millimetres, which is what
    the office cares about, so the numbers cross unchanged and the file
    is written with ``$LTSCALE = 1`` — a dashed line then reads dashed at
    every plot scale instead of at one.
    """
    from core.layers import LINETYPES
    pairs = LINETYPES.get(str(name))
    if not pairs:
        return []
    flat: list = []
    for i in range(0, len(pairs) - 1, 2):
        dash, gap = float(pairs[i]), float(pairs[i + 1])
        if dash > 0:
            flat.append(dash)
        if gap:
            flat.append(-abs(gap))
    if not flat:
        return []
    return [float(sum(abs(v) for v in flat)), *flat]


def _ensure_layer(doc, name: str, color: int, lineweight: float,
                  linetype: str = "CONTINUOUS"):
    if name not in doc.layers:
        layer = doc.layers.add(name)
    else:
        layer = doc.layers.get(name)
    layer.color = int(color)
    # ezdxf takes lineweight in 1/100 mm, and AutoCAD accepts only a fixed
    # ladder of them: a pen of 0.75 mm has to be written as the nearest
    # weight the receiving CAD HAS (0.80), or it silently snaps to one
    # anyway and the office cannot tell which of the two it got.
    layer.dxf.lineweight = _nearest_dxf_lineweight(lineweight)
    if linetype and linetype != "CONTINUOUS":
        # The pattern is part of the office's table now, so the linetype
        # is DEFINED here (scaled per mm, as AutoCAD's own are) instead of
        # being dropped when the blank file happens not to carry it.
        if linetype not in doc.linetypes:
            pattern = _dxf_linetype_pattern(linetype)
            if pattern:
                doc.linetypes.add(linetype, pattern, description=linetype)
        if linetype in doc.linetypes:
            layer.dxf.linetype = linetype
    return layer


def save_drawing_dxf(path: str | Path, view, scene, *,
                     layer_map: dict | None = None,
                     with_hatch: bool = True, with_dimensions: bool = True,
                     with_text: bool = True, doc_name: str = "",
                     annotation_key: str = "",
                     hatch_material: str = "",
                     pens: dict | None = None) -> dict:
    """Write one drawing's DXF. Returns a count summary.

    ``view`` is a :class:`core.building.drawings.DrawingView` (its camera
    and its cuts are the drawing's own rule, so the DXF and the sheet show
    the same drawing); ``scene`` supplies the geometry. Without ezdxf the
    call raises, because a half-written DXF is worse than an error the user
    can act on.
    """
    ezdxf = _try_ezdxf()
    if ezdxf is None:
        raise RuntimeError(
            "Cần ezdxf để xuất DXF bản vẽ (pip install ezdxf).")
    from core.hlr import hlr_drawing

    if annotation_key:
        view.annotation_key = str(annotation_key)
    doc = ezdxf.new("R2000", setup=True)
    doc.units = ezdxf.units.MM
    doc.header["$INSUNITS"] = 4                    # millimetres
    if doc_name:
        doc.header["$PROJECTNAME"] = str(doc_name)
    msp = doc.modelspace()

    # The drawing's own cuts, exactly as the sheet applies them: its
    # section becomes the scene's active cut (the composer does the same
    # around a frame), its trims travel beside it, and both come back off
    # afterwards so exporting never disturbs the model.
    drawing = hlr_drawing(scene, view.camera(), profiles=True, fills=True,
                          hidden=True, clip_planes=view.clip_planes,
                          section=(view.section_planes[0]
                                   if view.section_planes else None))
    counts = {"lines": 0, "hatch": 0, "dimensions": 0, "text": 0}
    # Line patterns are stated in millimetres of paper; $LTSCALE = 1 makes
    # the receiving CAD draw them at that size rather than scaling by unit.
    try:
        doc.header["$LTSCALE"] = 1.0
    except Exception:                              # noqa: BLE001 — header optional
        pass
    # The office's pen table: a document that set its own widths is inked
    # with them, and one that never opened the manager keeps the trade's.
    table = dict(PEN_TABLE) if pens is None else {
        str(key): (float(value[0]), int(value[1]))
        for key, value in pens.items()
        if key in PEN_TABLE and len(value) >= 2}
    table = {**PEN_TABLE, **table}
    # The drawing arrives in camera-plane METRES (that is what the HLR
    # works in) while the file declares millimetres — the office's own
    # unit, and the one a receiving CAD reads geometry with. Everything
    # crosses here, once: a 6 m wall must write as 6000, not 6.
    MM = 1000.0


    def _mm(point):
        return (float(point[0]) * MM, float(point[1]) * MM)

    # ---- linework, per class ------------------------------------------
    # One line class per layer, so the CAD's pen table can give each its
    # weight: the cut heaviest, the hidden lightest and dashed.
    kinds = drawing.kinds
    classes = (
        ("cut", "CUT", 2),
        ("profile", "PROFILE", 1),
        ("edge", "EDGE", 0),
        ("hidden", "HIDDEN", 3),
    )
    linetypes = {str(key): str(value[2])
                 for key, value in (pens or {}).items() if len(value) >= 3}
    for key, layer_key, wanted in classes:
        lw, color = table.get(key, PEN_TABLE[key])
        name = mapped_layer(f"KT-{layer_key}", layer_map)
        linetype = linetypes.get(key) or (
            "dashed" if key == "hidden" else "continuous")
        from core.layers import DXF_LINETYPES
        _ensure_layer(doc, name, int(color), lw,
                      linetype=DXF_LINETYPES.get(linetype, "CONTINUOUS"))
        for i, seg in enumerate(drawing.segs):
            # Unclassified segments are drawn as plain edges: a line drawn
            # on the wrong layer is a nuisance, a line not drawn is a fault.
            if kinds is not None and int(kinds[i]) != wanted:
                continue
            msp.add_line(_mm((seg[0], seg[1])), _mm((seg[2], seg[3])),
                         dxfattribs={"layer": name})
            counts["lines"] += 1

    # ---- the section fill ---------------------------------------------
    if with_hatch and drawing.loops:
        lw, _ = table.get("hatch", PEN_TABLE["hatch"])
        name = mapped_layer("KT-HATCH", layer_map)
        _ensure_layer(doc, name, 8, lw)
        # The pattern of each cut area is DERIVED here rather than written
        # segment by segment: a HATCH carries its own definition, so the
        # receiving CAD regenerates the lines at any zoom and the file
        # stays a drawing instead of thousands of anonymous lines. The
        # definition is the pattern table's own (core.building.patterns),
        # in MILLIMETRES, which is what the file declares.
        #
        # WHICH pattern is the ELEMENT's own, not one material for the whole
        # sheet: a concrete column standing in a masonry wall is exactly
        # what the hatch is for, and hatching both as masonry threw that
        # away. Attribution is recovered from the elements' own geometry
        # (core.building.surface_fill) because the clipper's rings carry no
        # identity of their own.
        from core.building.patterns import families_for
        from core.building.surface_fill import (cut_rings_per_element,
                                                material_of_ring)

        cut_plane = (view.section_planes[0] if view.section_planes else None)
        attributed = (cut_rings_per_element(scene, cut_plane, view.camera())
                      if cut_plane is not None else [])
        # One hatch object per material: a DXF pattern definition belongs
        # to the hatch that carries it, so two materials mean two hatches,
        # each with its own regenerable pattern.
        hatches: dict = {}
        for ring in drawing.loops:
            points = [_mm((p[0], p[1])) for p in ring]
            if len(points) < 3:
                continue
            material = material_of_ring(scene, ring, attributed,
                                        hatch_material)
            hatch = hatches.get(material)
            if hatch is None:
                hatch = msp.add_hatch(color=8, dxfattribs={"layer": name})
                hatch.set_pattern_fill(
                    "KT_HATCH", color=8, scale=1.0,
                    definition=_pattern_definition(families_for(material)))
                hatches[material] = hatch
            hatch.paths.add_polyline_path(points, is_closed=True)
            counts["hatch"] += 1

    # ---- the model's own words ----------------------------------------
    if with_text:
        import numpy as np
        from core.hlr import _to_cam, camera_basis

        lw, _ = table.get("text", PEN_TABLE["text"])
        name = mapped_layer("KT-TEXT", layer_map)
        _ensure_layer(doc, name, 7, lw)
        camera = view.camera()
        eye, right, up, fwd = camera_basis(camera)
        # Model millimetres per drawing unit: the drawing's coordinates are
        # camera-plane metres, so a text height in paper millimetres is
        # `mm × scale` in the drawing's own space.
        height = 2.5 * float(view.scale_denom or 100.0)

        def to_plane(point):
            c = _to_cam(np.array([[point.x(), point.y(), point.z()]],
                                 dtype=float), eye, right, up, fwd)[0]
            return (float(c[0]) * MM, float(c[1]) * MM)

        for label in _labels_of(scene, view):
            if not scene.entity_visible(label):
                continue
            x, y = to_plane(label.position())
            for i, line in enumerate(str(label.text).splitlines() or ("",)):
                msp.add_text(line, height=height, dxfattribs={
                    "layer": name,
                    "insert": (x, y - i * height * 1.3)})
                counts["text"] += 1

    # ---- the model's dimensions ---------------------------------------
    # ---- the plan's own drawn entities ---------------------------------
    # The lines, arcs and circles the OFFICE drew on the plan are part of
    # the drawing, so they print with it. They are faceted into segments
    # here — the receiving CAD reads a polyline segment for what it is,
    # and an arc nobody can render is worse than a polyline that reads as
    # one.
    from core.plan_draw import curves_at

    # The drawing's own cut height, the rule every annotation follows: the
    # storey's floor plus the view's cut. A drawn line belongs to the plan
    # it stands on, so the sheet looks for it at exactly this z.
    building_row = getattr(view, "row", None) or {}
    cut_z = _drawn_cut_z_mm(scene, view, building_row)
    drawn = curves_at(scene, cut_z / 1000.0) if cut_z is not None else []
    if drawn:
        import numpy as np
        from core.hlr import _to_cam, camera_basis

        lw, _ = table.get("profile", PEN_TABLE.get("profile", lw))
        name = mapped_layer("KT-NET", layer_map)
        _ensure_layer(doc, name, 7, lw)
        camera = view.camera()
        eye, right, up, fwd = camera_basis(camera)

        def to_curve_plane(x_mm, y_mm, z_m):
            point = np.array([[x_mm / 1000.0, y_mm / 1000.0, z_m]],
                             dtype=float)
            c = _to_cam(point, eye, right, up, fwd)[0]
            return (float(c[0]) * MM, float(c[1]) * MM)

        for curve in drawn:
            if not scene.entity_visible(curve):
                continue
            for x1, y1, x2, y2 in curve.segments():
                msp.add_line(to_curve_plane(x1, y1, curve.z),
                             to_curve_plane(x2, y2, curve.z),
                             dxfattribs={"layer": name})
                counts["lines"] += 1

    if with_dimensions:
        import numpy as np
        from core.hlr import _to_cam, camera_basis

        lw, _ = table.get("dimension", PEN_TABLE["dimension"])
        name = mapped_layer("KT-DIM", layer_map)
        _ensure_layer(doc, name, 4, lw)
        style = "KT_DIM"
        if style not in doc.dimstyles:
            dimstyle = doc.dimstyles.add(style)
            dimstyle.dxf.dimtxt = 2.5 * float(view.scale_denom or 100.0)
            dimstyle.dxf.dimasz = 2.0 * float(view.scale_denom or 100.0)
            dimstyle.dxf.dimblk = "ArchTick"
            dimstyle.dxf.dimdec = 0
        camera = view.camera()
        eye, right, up, fwd = camera_basis(camera)

        def to_plane(point):
            c = _to_cam(np.array([[point.x(), point.y(), point.z()]],
                                 dtype=float), eye, right, up, fwd)[0]
            return (float(c[0]) * MM, float(c[1]) * MM)

        for dim in _dims_of(scene, view):
            if not scene.entity_visible(dim):
                continue
            a, b = to_plane(dim.a), to_plane(dim.b)
            ap, bp = dim.line_points()
            a2, b2 = to_plane(ap), to_plane(bp)
            measurement = float(dim.value()) * 1000.0     # mm
            try:
                msp.add_aligned_dim(p1=a, p2=b, distance=0.0,
                                    dxfattribs={"layer": name},
                                    override={"dimstyle": style,
                                              "dimtxsty": "Standard"})
                counts["dimensions"] += 1
            except Exception:          # noqa: BLE001 — an odd dimension must
                # not sink the whole export: the dimension line is drawn and
                # its number written, which is still a readable drawing.
                msp.add_line(a2, b2, dxfattribs={"layer": name})
                msp.add_text(f"{measurement:.0f}", height=2.5 * float(
                    view.scale_denom or 100.0), dxfattribs={"layer": name,
                                                            "insert": a2})
                counts["lines"] += 1
                counts["text"] += 1

    doc.saveas(str(path))
    counts["layers"] = len(doc.layers)
    return counts


def _pattern_definition(families) -> list:
    """The DXF pattern definition of the pattern table's own families.

    A DXF definition line is ``[angle, base_point, offset, dashes]`` where
    each element is measured ALONG and ACROSS the family's own direction
    (the line is rotated by ``angle`` first), and the dashes are lengths:
    POSITIVE for ink, NEGATIVE for a gap, never a bare positive pair —
    AutoCAD reads a gap as ink and draws a solid line over the whole area,
    which is how a hatched wall came out as a black box.

    The table states ``(angle, spacing_mm, offset_mm, dash_mm)`` in paper
    millimetres: a family's spacing is what separates its own parallel
    lines, so it goes on the ACROSS axis (``dy``), and the family's lateral
    shift — what interleaves two families into a brick look — travels
    ALONG the line (``dx``). Both are paper distances, and a hatch is a
    drawing convention, so the same wall hatches the same at 1:50 and at
    1:100 in the file the receiving CAD regenerates.
    """
    lines: list = []
    for angle, spacing, offset, dash in families:
        across = float(spacing) or 0.0
        if across <= 0.0:
            across = 1.0            # a zero gap is a division by zero to CAD
        along = float(offset) or 0.0
        dashes: list = []
        if dash:
            run = abs(float(dash))
            dashes = [run, -run]
        lines.append([float(angle), (0.0, 0.0), (along, across), dashes])
    return lines


def _owned(scene, view):
    """The entities one BIM drawing published, or ``None`` for «everything».

    The document holds EVERY storey's annotations at once (each drawing
    stamps the ones it made with the registry ``bim_annotations``), and an
    export that wrote them all would carry the floor above's levels and
    room areas on the ground floor's DXF — numbers that are not wrong,
    only about a drawing nobody is looking at. Scoped when the registry
    knows this drawing; unscoped for a document whose annotations were
    placed by hand (the composer's own labels), which the registry does
    not describe.
    """
    registry = getattr(scene, "bim_annotations", None)
    if not isinstance(registry, dict) or not registry:
        return None
    key = _drawing_key(scene, view)
    if key is None:
        return None
    return {id(e) for e in registry.get(key, ())}


def resolve_annotation_key(scene, view) -> str:
    """The key a caller should FILE this drawing's annotations under.

    A drawing SET has already published each storey under its sheet's own
    name; an export that minted a private key beside that one left BOTH
    sets in the document, and the composer draws every dimension its frame
    can see — so one export doubled the sheet's chains. When the set's key
    exists, it is reused and the annotations are REPLACED, not added.
    """
    found = _drawing_key(scene, view)
    if found:
        return str(found)
    return f"dxf:{getattr(view, 'story_id', '') or view.name}"


def _drawing_key(scene, view):
    """The registry key this drawing's annotations were filed under.

    An explicit ``view.annotation_key`` wins — the caller that published
    the annotations knows where it put them (the DXF menu files them under
    ``dxf:<storey>``, a sheet under its own scene name). Without one the
    drawing's name is tried, then the storey's, which covers a document
    issued by the set.
    """
    registry = getattr(scene, "bim_annotations", None) or {}
    wanted = str(getattr(view, "annotation_key", "") or "")
    if wanted and wanted in registry:
        return wanted
    # The key a drawing set filed this storey under carries the storey's own
    # ID («Mặt bằng Tầng 1·story-abc»): two storeys may legitimately share a
    # name, and the id is the only part that cannot. Look for it FIRST —
    # it is the exact answer, where the name lookups below are guesses.
    story = str(getattr(view, "story_id", "") or "")
    if story:
        suffix = f"·{story}"
        for key in registry:
            if str(key).endswith(suffix) or str(key).endswith(f"{suffix}·grid"):
                return str(key)
    candidates = [str(getattr(view, "name", "") or ""),
                  str(getattr(view, "story_id", "") or "")]
    for candidate in candidates:
        if not candidate:
            continue
        for key in registry:
            if str(key) == candidate or str(key).endswith(f":{candidate}"):
                return str(key)
    # The DRAWING SET files each storey's annotations under the SHEET's
    # name, not under the storey id — so a storey export from a document
    # the set has issued finds no key of its own and would fall back to
    # «everything the document holds», printing the floor above's levels
    # on this plan. The sheet names carry the storey's own name, which is
    # the last thing that reliably identifies them.
    story = str(getattr(view, "story_id", "") or "")
    if story:
        building = None
        try:
            from core.building.model import building_of

            building = building_of(scene)
        except Exception:                        # noqa: BLE001 — optional
            building = None
        story_name = ""
        if building is not None:
            row = building.story(story) or {}
            story_name = str(row.get("name") or "")
        if story_name:
            # A sheet names its drawing «Mặt bằng <storey>» and the
            # registry key is that whole name. The match is the storey's
            # name against the key with the drawing's KIND words taken off
            # the front: accepting «every word of the storey appears
            # somewhere in the key» matched «Tầng» against «Mặt bằng Tầng
            # 1» and printed the floor above's level marks on a plan whose
            # own floor is ±0.000. Trailing words of the key that the
            # storey does not have mean it is a DIFFERENT drawing.
            words = story_name.split()
            for candidate in sorted(registry, key=lambda k: len(str(k))):
                parts = str(candidate).replace("—", " ").split()
                if not words or len(parts) < len(words):
                    continue
                # Strip the key's leading kind words («Mặt bằng», «Plan»)
                # then require the REST to be the storey's own name.
                if parts[-len(words):] == words:
                    return str(candidate)
    return None


def _drawn_cut_z_mm(scene, view, row: dict):
    """The z a drawn entity must stand at to belong to this drawing,
    in model millimetres — ``None`` when the view is not a storey plan
    (a section or a 3D view carries no plan ink)."""
    story_id = str(getattr(view, "story_id", "") or "")
    if not story_id:
        return None
    # A frame renders through a SAVED VIEW, whose ``drawing`` dict is the
    # rule the drawing was issued with — story id, cut and all. That is
    # what the sheet's own frames carry, so the rule is read from wherever
    # the caller found the drawing.
    rule = dict(getattr(view, "row", None) or {})
    story_id = str(story_id or rule.get("story_id") or "")
    from core.building import drawings as _drawings
    from core.building.model import building_of

    building = building_of(scene)
    story = building.story(story_id) if building is not None else None
    if not story:
        return None
    cut = row.get("cut_mm")
    if cut is None:
        cut = story.get("cut_mm")
    if cut is None:
        cut = _drawings.DEFAULT_CUT_MM
    return float(story.get("z_mm", 0.0)) + float(cut)


def _labels_of(scene, view):
    """The labels this drawing owns, or every visible one when unscoped."""
    owned = _owned(scene, view)
    labels = getattr(scene, "text_labels", None) or []
    if owned is None:
        return list(labels)
    return [label for label in labels if id(label) in owned]


def _dims_of(scene, view):
    """The dimensions this drawing owns, or every visible one."""
    owned = _owned(scene, view)
    dims = getattr(scene, "dimensions", None) or []
    if owned is None:
        return list(dims)
    return [dim for dim in dims if id(dim) in owned]


def save_plan_dxf(path: str | Path, scene, building, story_id: str, **kw):
    """The common case: the plan of one storey, straight to a DXF."""
    from core.building import drawings as _drawings
    row = {"kind": "story", "story_id": str(story_id)}
    view = _drawings.view_for(building, row)
    return save_drawing_dxf(path, view, scene, **kw)
