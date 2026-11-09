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


def _ensure_layer(doc, name: str, color: int, lineweight: float,
                  linetype: str = "CONTINUOUS"):
    if name not in doc.layers:
        layer = doc.layers.add(name)
    else:
        layer = doc.layers.get(name)
    layer.color = int(color)
    # ezdxf takes lineweight in 1/100 mm.
    layer.dxf.lineweight = int(round(lineweight * 100))
    if linetype and linetype != "CONTINUOUS" and \
            linetype in doc.linetypes:
        layer.dxf.linetype = linetype
    return layer


def save_drawing_dxf(path: str | Path, view, scene, *,
                     layer_map: dict | None = None,
                     with_hatch: bool = True, with_dimensions: bool = True,
                     with_text: bool = True, doc_name: str = "") -> dict:
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
    for key, layer_key, wanted in classes:
        lw, color = PEN_TABLE[key]
        name = mapped_layer(f"KT-{layer_key}", layer_map)
        _ensure_layer(doc, name, int(color), lw,
                      linetype="HIDDEN" if key == "hidden" else "CONTINUOUS")
        for i, seg in enumerate(drawing.segs):
            # Unclassified segments are drawn as plain edges: a line drawn
            # on the wrong layer is a nuisance, a line not drawn is a fault.
            if kinds is not None and int(kinds[i]) != wanted:
                continue
            msp.add_line((float(seg[0]), float(seg[1])),
                         (float(seg[2]), float(seg[3])),
                         dxfattribs={"layer": name})
            counts["lines"] += 1

    # ---- the section fill ---------------------------------------------
    if with_hatch and drawing.loops:
        lw, _ = PEN_TABLE["hatch"]
        name = mapped_layer("KT-HATCH", layer_map)
        _ensure_layer(doc, name, 8, lw)
        for ring in drawing.loops:
            points = [(float(p[0]), float(p[1])) for p in ring]
            if len(points) < 3:
                continue
            hatch = msp.add_hatch(color=8, dxfattribs={"layer": name})
            hatch.set_solid_fill(color=8)
            hatch.paths.add_polyline_path(points, is_closed=True)
            counts["hatch"] += 1

    # ---- the model's own words ----------------------------------------
    if with_text:
        import numpy as np
        from core.hlr import _to_cam, camera_basis

        lw, _ = PEN_TABLE["text"]
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
            return (float(c[0]), float(c[1]))

        for label in getattr(scene, "text_labels", None) or []:
            if not scene.entity_visible(label):
                continue
            x, y = to_plane(label.position())
            for i, line in enumerate(str(label.text).splitlines() or ("",)):
                msp.add_text(line, height=height, dxfattribs={
                    "layer": name,
                    "insert": (x, y - i * height * 1.3)})
                counts["text"] += 1

    # ---- the model's dimensions ---------------------------------------
    if with_dimensions:
        import numpy as np
        from core.hlr import _to_cam, camera_basis

        lw, _ = PEN_TABLE["dimension"]
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
            return (float(c[0]), float(c[1]))

        for dim in getattr(scene, "dimensions", None) or []:
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


def save_plan_dxf(path: str | Path, scene, building, story_id: str, **kw):
    """The common case: the plan of one storey, straight to a DXF."""
    from core.building import drawings as _drawings
    row = {"kind": "story", "story_id": str(story_id)}
    view = _drawings.view_for(building, row)
    return save_drawing_dxf(path, view, scene, **kw)
