# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Marco Sumari Tellez and IngeTrazo contributors.
"""Drawings: one rule per drawing, stated as data, plus its annotations.

The reference made the point that a drawing is a *rule*, not a picture: to
issue a plan you must not have to walk the model hiding tags, lowering the
cut and switching things off, because the sheet then depends on where the
model happened to be left. :func:`view_for` returns the whole rule for a
document row — the camera, the cutting plane, the trimming planes (the
floor limit, the depth of a section, the two sides of the section line, the
window of a detail) and which storey it belongs to — and everything else in
this module consumes that one object:

* the plan is cut at ``z + cut_mm`` (1200) and **trimmed** at its floor, so
  the ground and the storey below do not show through the board (the trim
  hides and never cuts: no second set of chords smeared across the plan);
* a section cuts at its line and looks one way, trimmed to a depth (10 m)
  and to the two sides of the line plus a margin;
* an elevation is the same view without the cut;
* an interior elevation adds a floor-to-ceiling window;
* a roof plan is a top view cut low (450 mm over the storey) so the gable
  walls read as walls do in a plan.

:func:`annotate_plan` then writes the drawing's *language* into the scene:
the two dimension chains outside the house (each opening's two edges in the
detail chain, the two wall ends in the total chain, 10 and 18 mm of paper
off the wall face), the level marks (``FL:+0000`` / ``CL:+2700`` — the
Vietnamese convention: floor and ceiling on one mark, a box in plan and a
triangle in elevation), and a room stamp per zone with its name and area.
They are ordinary ``Dimension`` and ``TextLabel`` entities, so the sheets,
the DXF and the pick all carry them without a second annotation system, and
editing the model moves them with it.
"""
from __future__ import annotations

import math

from PySide6.QtGui import QVector3D

from core.section import SectionPlane

#: Where a plan cuts, over its storey's finished floor, in mm — the trade
#: standard: doors (2.1 m) are cut, windows are cut through their glass.
DEFAULT_CUT_MM = 1200.0

#: A plan is trimmed this far above the storey's floor (0 = at the floor).
DEFAULT_CUT_BOTTOM_MM = 0.0

#: A roof plan cuts low over the topmost storey so its gable walls show.
ROOF_CUT_MM = 450.0

#: How deep a section or elevation looks, in mm (10 m).
DEFAULT_DEPTH_MM = 10000.0

#: How far past the section line's ends the view reaches, in mm.
SIDE_MARGIN_MM = 50.0

#: An interior elevation reaches this far below its floor (the slab under).
INTERIOR_BELOW_MM = 400.0

#: The inner face of an interior elevation when no height is given.
DEFAULT_INTERIOR_HEIGHT_MM = 1000.0

#: Paper millimetres a dimension chain stands off the wall face.
DETAIL_OFFSET_PAPER = 10.0
TOTAL_OFFSET_PAPER = 18.0

#: Text heights on paper (mm) for the drawing's own annotations.
TEXT_MM = 2.5
AREA_TEXT_MM = 2.1
LEVEL_TEXT_MM = 2.5

#: The layer every auto-annotation lands on, so a sheet can hide the lot.
ANNOT_LAYER = "KT-Ghi chú"
#: The layer the axis lines and their bubbles live on — a reader hides the
#: grid when tracing and shows it when dimensioning.
GRID_LAYER = "KT-Trục"

#: How far past the outermost crossing an axis line reaches before its
#: bubble — the trade's own gap, in model mm at 1:100.
GRID_MARGIN_MM = 1200.0

#: A far enough eye for a parallel view: the projection is parallel, so the
#: distance is only what frames it (10 km keeps every depth divide sane).
FAR_MM = 1_000_000.0

KIND_STORY = "story"
KIND_SECTION = "section"
KIND_ELEVATION = "elevation"
KIND_INTERIOR = "interior"
KIND_ROOF = "roof"
KIND_TOP = "top"
KIND_DETAIL = "detail"

#: Every kind :func:`view_for` knows.
KINDS = (KIND_STORY, KIND_ROOF, KIND_TOP, KIND_SECTION, KIND_ELEVATION,
         KIND_INTERIOR, KIND_DETAIL)


class DrawingView:
    """One drawing's rule: the camera, the cuts, what it trims away."""

    __slots__ = ("kind", "name", "row", "story_id", "target", "distance",
                 "yaw", "pitch", "up", "fov_deg", "section_planes",
                 "clip_planes", "crop_u", "crop_v", "scale_denom",
                 "hidden_layers")

    def __init__(self, kind: str, name: str = "", row: dict | None = None,
                 story_id: str | None = None, target=(0.0, 0.0, 0.0),
                 distance: float = 20.0, yaw: float = -math.pi / 2.0,
                 pitch: float = math.pi / 2.0, up=(0.0, 1.0, 0.0),
                 fov_deg: float = 45.0, section_planes=None,
                 clip_planes=None, crop_u=None, crop_v=None,
                 scale_denom: float = 100.0) -> None:
        self.kind = kind
        self.name = name
        self.row = dict(row or {})
        self.story_id = story_id
        self.target = tuple(float(v) for v in target)
        self.distance = float(distance)
        self.yaw = float(yaw)
        self.pitch = float(pitch)
        self.up = tuple(float(v) for v in up)
        self.fov_deg = float(fov_deg)
        self.section_planes = list(section_planes or [])
        #: Trim planes: they hide their side and draw nothing at all.
        self.clip_planes = list(clip_planes or [])
        #: A window on the source plane's own axes (mm), for a detail.
        self.crop_u = crop_u
        self.crop_v = crop_v
        self.scale_denom = float(scale_denom)
        #: Layers this drawing HIDES — the view filter. An empty list shows
        #: everything; a layout names every trade but its own.
        self.hidden_layers: list = []

    # ---- What the rest of the app consumes ----------------------------------

    def camera(self):
        """An :class:`~core.camera.OrbitCamera` pointed at this view."""
        from core.camera import OrbitCamera
        cam = OrbitCamera()
        cam.target = QVector3D(*self.target)
        cam.distance = self.distance
        cam.yaw = self.yaw
        cam.pitch = self.pitch
        cam.up = QVector3D(*self.up)
        cam.fov_deg = self.fov_deg
        cam.perspective = False
        return cam

    def fit_distance(self, height_m: float) -> None:
        """Frame exactly ``height_m`` metres of model in a parallel view."""
        from core.composition import ortho_distance_for_height
        self.distance = ortho_distance_for_height(height_m, self.fov_deg)

    def is_plan(self) -> bool:
        return self.kind in (KIND_STORY, KIND_ROOF, KIND_TOP)

    def to_dict(self) -> dict:
        return {
            "kind": self.kind, "name": self.name, "row": dict(self.row),
            "story_id": self.story_id, "target": list(self.target),
            "distance": self.distance, "yaw": self.yaw, "pitch": self.pitch,
            "up": list(self.up), "fov_deg": self.fov_deg,
            "views": [sp.to_dict() for sp in self.section_planes],
            "clips": [sp.to_dict() for sp in self.clip_planes],
            "crop": (list(self.crop_u) + list(self.crop_v)
                     if self.crop_u and self.crop_v else None),
            "scale_denom": self.scale_denom,
            "hidden_layers": list(self.hidden_layers),
        }

    @classmethod
    def from_dict(cls, raw: dict) -> "DrawingView":
        crop = raw.get("crop")
        yaw = raw.get("yaw")
        pitch = raw.get("pitch")
        view = cls(
            str(raw.get("kind") or KIND_STORY), str(raw.get("name") or ""),
            raw.get("row") or {}, raw.get("story_id"),
            raw.get("target") or (0.0, 0.0, 0.0),
            float(raw.get("distance") or 20.0),
            -math.pi / 2.0 if yaw is None else float(yaw),
            math.pi / 2.0 if pitch is None else float(pitch),
            raw.get("up") or (0.0, 1.0, 0.0),
            float(raw.get("fov_deg") or 45.0),
            [SectionPlane.from_dict(r) for r in raw.get("views") or []],
            [SectionPlane.from_dict(r) for r in raw.get("clips") or []],
            crop[:2] if crop else None, crop[2:] if crop else None,
            float(raw.get("scale_denom") or 100.0))
        view.hidden_layers = [str(n) for n in raw.get("hidden_layers") or ()]
        return view

    def __repr__(self) -> str:  # pragma: no cover — debug aid
        return (f"DrawingView({self.kind} {self.name!r} "
                f"1:{self.scale_denom:g})")


# ---- the rules --------------------------------------------------------------

def _hide(name, n, point_mm) -> SectionPlane:
    """A plane that hides everything on ``n``'s side of ``point`` and draws
    its cut — the section itself.

    Both helpers here take the BUILDING's unit (millimetres, what every
    parameter of a storey or a wall is written in) and hand the plane the
    scene's (metres). Mixing the two silently puts a cut 1000× too high,
    which is invisible on a 3 m house and catastrophic on a 30 m one.
    """
    return SectionPlane(QVector3D(*(float(v) / 1000.0 for v in point_mm)),
                        QVector3D(*n), name=name)


def _trim(name, n, point_mm) -> SectionPlane:
    """A plane that hides its side and draws nothing — the floor limit, the
    depth of a section, the side of a line. ``point_mm`` in millimetres."""
    sp = SectionPlane(QVector3D(*(float(v) / 1000.0 for v in point_mm)),
                      QVector3D(*n), name=name)
    sp.clip_only = True
    return sp


def _mm_or(raw, default: float) -> float:
    """A millimetre value where 0 IS a value — the plan cut is measured
    from the storey floor, so ``cut_mm: 0`` means "cut at the floor"
    (what a beam layout needs) and must not fall back to the default."""
    return float(default) if raw is None else float(raw)


def _mm_vec(row, key, fallback=(0.0, 0.0)) -> tuple:
    v = row.get(key)
    if not v or len(v) < 2:
        return (float(fallback[0]), float(fallback[1]))
    return (float(v[0]), float(v[1]))


def _story_marks(building, row) -> tuple:
    """``(story, z, top)`` of the storey a row draws, in mm."""
    sid = row.get("story_id")
    story = building.story(str(sid)) if sid else None
    if story is None and building.stories:
        story = building.stories[0]
    if story is None:
        raise ValueError("Công trình chưa có tầng nào.")
    z = float(story.get("z_mm", 0.0))
    above = building.story_above(str(story["id"]))
    top = (float(above.get("z_mm", 0.0)) if above is not None
           else z + float(story.get("height_mm", 3300.0)))
    return story, z, top


def story_box(building, story) -> tuple:
    """``(x0, y0, x1, y1)`` of everything on a storey, in mm.

    Every element type states its plan extent somewhere — a baseline, an
    outline, a centre — so this asks them all rather than a scene, which
    keeps a drawing's framing available before anything was built.
    """
    sid = str(story["id"])
    xs: list = []
    ys: list = []
    for element in building.elements:
        if str(element.get("story_id")) != sid:
            continue
        params = element.get("params") or {}
        for key in ("baseline_start_mm", "baseline_end_mm", "center_mm"):
            v = params.get(key)
            if v and len(v) >= 2:
                xs.append(float(v[0]))
                ys.append(float(v[1]))
        outline = params.get("outline_mm") or params.get("path_mm") or []
        for p in outline:
            if len(p) >= 2:
                xs.append(float(p[0]))
                ys.append(float(p[1]))
        for axis in ("start", "end"):
            v = params.get(f"baseline_{axis}_mm")
            if v and len(v) >= 2:
                xs.append(float(v[0]))
                ys.append(float(v[1]))
        half = float(params.get("width_mm", 0.0) or 0.0) / 2.0
        if half and params.get("center_mm"):
            cx, cy = float(params["center_mm"][0]), float(params["center_mm"][1])
            xs.extend((cx - half, cx + half))
            ys.extend((cy - half, cy + half))
    if not xs or not ys:
        return (-1000.0, -1000.0, 1000.0, 1000.0)
    return (min(xs), min(ys), max(xs), max(ys))


def view_for(building, row: dict, scale_denom: float | None = None,
             frame_h_mm: float = 190.0) -> DrawingView:
    """The whole rule of the drawing ``row`` describes.

    ``row`` is the document row the reference keeps in its project map:
    ``{"kind": "story", "story_id": …}`` or ``{"kind": "section", "p1": …,
    "p2": …, "normal": …}``. The scale comes back on the view so plan and
    annotator agree on the one number the sheet will be issued at.
    """
    kind = str(row.get("kind") or KIND_STORY)
    if kind not in KINDS:
        raise ValueError(f"Loại bản vẽ không hỗ trợ: {kind}")
    name = str(row.get("name") or "")
    if kind == KIND_TOP:
        story, z, _top = _story_marks(building, row)
        return _plan_view(building, row, story, z, name, scale_denom,
                          frame_h_mm, cut=None, trim=None)
    if kind in (KIND_STORY, KIND_ROOF):
        story, z, top = _story_marks(building, row)
        if kind == KIND_ROOF:
            cut = _mm_or(row.get("cut_mm"), ROOF_CUT_MM)
            lower = _mm_or(row.get("cut_bottom_mm"), DEFAULT_CUT_BOTTOM_MM)
        else:
            cut = _mm_or(row.get("cut_mm"), DEFAULT_CUT_MM)
            lower = _mm_or(row.get("cut_bottom_mm"), DEFAULT_CUT_BOTTOM_MM)
        return _plan_view(building, row, story, z, name, scale_denom,
                          frame_h_mm, cut=cut, trim=z + lower)
    return _directional_view(building, row, kind, name, scale_denom,
                             frame_h_mm)


def _plan_view(building, row, story, z, name, scale_denom, frame_h_mm,
               cut, trim) -> DrawingView:
    x0, y0, x1, y1 = story_box(building, story)
    cx, cy = (x0 + x1) / 2.0, (y0 + y1) / 2.0
    z_cut = z + (cut if cut is not None else 0.0)
    view = DrawingView(
        KIND_ROOF if cut is not None and cut == ROOF_CUT_MM else
        (KIND_STORY if cut is not None else KIND_TOP),
        name, row, str(story["id"]),
        target=(cx / 1000.0, cy / 1000.0, z_cut / 1000.0),
        yaw=-math.pi / 2.0, pitch=math.pi / 2.0, up=(0.0, 1.0, 0.0),
        scale_denom=_scale(x1 - x0, y1 - y0, scale_denom, frame_h_mm))
    if cut is not None:
        # Hide what is above the cut: the plan looks down at what it sliced.
        view.section_planes.append(_hide("Cao độ cắt", (0.0, 0.0, 1.0),
                                         (0.0, 0.0, z_cut)))
    if trim is not None:
        # …and hide what is under the floor (the ground, the storey below).
        view.clip_planes.append(_trim("Cao độ xén", (0.0, 0.0, -1.0),
                                      (0.0, 0.0, trim)))
    view.fit_distance(max(x1 - x0, y1 - y0) / 1000.0 or 1.0)
    return view


def _directional_view(building, row, kind, name, scale_denom,
                      frame_h_mm) -> DrawingView:
    """Cut/side rules of a section, an elevation or an interior view."""
    p1 = _mm_vec(row, "p1")
    p2 = _mm_vec(row, "p2", (p1[0] + 1000.0, p1[1]))
    normal = _mm_vec(row, "normal", (0.0, -1.0))
    nx, ny = normal
    length = math.hypot(p2[0] - p1[0], p2[1] - p1[1])
    if length < 1e-9:
        al = (1.0, 0.0)
    else:
        al = ((p2[0] - p1[0]) / length, (p2[1] - p1[1]) / length)
    depth = float(row.get("depth_mm") or DEFAULT_DEPTH_MM)
    margin = SIDE_MARGIN_MM

    story, z, top = _story_marks(building, row)
    height_mm = float(row.get("height_mm") or 0.0)
    z0 = float(row.get("z_mm") if row.get("z_mm") is not None else z)
    # An elevation of the whole house states its own floor and height; the
    # storey the row names only decides where the view is filed.
    if row.get("z_mm") is not None or height_mm:
        top = z0 + (height_mm or (top - z0))
    planes: list = []
    if kind in (KIND_SECTION, KIND_INTERIOR):
        # Cut away everything on the viewer's side of the line and look at
        # the cut: the near half of the house is gone, the section is drawn.
        planes.append(_hide("Mặt cắt", (nx, ny, 0.0), (p1[0], p1[1], 0.0)))
    # Look back from the line, at most ``depth`` deep; and no wider than the
    # line plus a margin — the sides of a section are its ends.
    clips = [
        _trim("Độ sâu", (-nx, -ny, 0.0),
              (p1[0] + nx * depth, p1[1] + ny * depth, 0.0)),
        _trim("Trước điểm đầu", (-al[0], -al[1], 0.0),
              (p1[0] - al[0] * margin, p1[1] - al[1] * margin, 0.0)),
        _trim("Sau điểm cuối", (al[0], al[1], 0.0),
              (p2[0] + al[0] * margin, p2[1] + al[1] * margin, 0.0)),
    ]
    if kind == KIND_INTERIOR:
        z1 = z0 + max(height_mm, DEFAULT_INTERIOR_HEIGHT_MM)
        clips.append(_trim("Cao độ đỉnh", (0.0, 0.0, -1.0),
                           (0.0, 0.0, z1)))
        clips.append(_trim("Cao độ đáy", (0.0, 0.0, 1.0),
                           (0.0, 0.0, z0 - INTERIOR_BELOW_MM)))

    mid = ((p1[0] + p2[0]) / 2.0, (p1[1] + p2[1]) / 2.0)
    tall = max(top - (min(z0, z) - 1000.0), 1000.0)
    base = min(z0, z)
    view = DrawingView(
        kind, name, row, str(story["id"]),
        target=(mid[0] / 1000.0, mid[1] / 1000.0,
                (base + tall / 2.0) / 1000.0),
        yaw=0.0, pitch=0.0, up=(0.0, 0.0, 1.0),
        scale_denom=_scale(length or 1000.0, tall, scale_denom,
                           frame_h_mm),
        section_planes=planes, clip_planes=clips)
    # The camera looks ALONG -normal from the far side, so the viewer stands
    # where the normal points.
    _aim_at(view, mid, normal)
    view.fit_distance(tall / 1000.0)
    return view


def _aim_at(view: DrawingView, at_mm, n) -> None:
    """Point the view's camera at ``at_mm`` from the side ``n`` names."""
    nx, ny = float(n[0]), float(n[1])
    norm = math.hypot(nx, ny) or 1.0
    nx, ny = nx / norm, ny / norm
    view.target = (float(at_mm[0]) / 1000.0, float(at_mm[1]) / 1000.0,
                   view.target[2])
    # The echo of the camera's yaw/pitch convention: forward = -d where
    # d = (cos p cos y, cos p sin y, sin p) points FROM the target TO the eye.
    view.pitch = 0.0
    view.yaw = math.atan2(ny, nx)
    view.up = (0.0, 0.0, 1.0)


def _scale(width_mm: float, height_mm: float,
           scale_denom: float | None, frame_h_mm: float) -> float:
    """The scale denominator: the caller's, or the smallest that fits."""
    if scale_denom:
        return float(scale_denom)
    from core.outliner import STANDARD_SCALES
    need = max(float(width_mm) / max(frame_h_mm * 0.9, 1e-6),
               float(height_mm) / max(frame_h_mm * 0.9, 1e-6))
    for n in STANDARD_SCALES:
        if float(n) >= need:
            return float(n)
    return float(STANDARD_SCALES[-1])


def detail_view(building, row: dict, source, rect=None,
                scale_denom: float | None = None) -> DrawingView:
    """A detail: a source drawing's rule, cropped to a rectangle.

    ``rect`` is ``(u0, v0, u1, v1)`` in millimetres on the source plane —
    the model is not copied (the reference's lesson: a detail that copies
    stops agreeing with the model the day after). The crop is four trim
    planes on the source's own axes, so everything else — the cut, the
    floor limit, the depth — is the source's.
    """
    view = DrawingView.from_dict(source.to_dict())
    view.kind = KIND_DETAIL
    view.name = str(row.get("name") or view.name)
    view.row = dict(row)
    if scale_denom:
        view.scale_denom = float(scale_denom)
    rect = rect or row.get("rect_mm")
    if rect and len(rect) >= 4:
        u0, v0, u1, v1 = (float(v) for v in rect[:4])
        if view.is_plan():
            ax = ((1.0, 0.0), (0.0, 1.0))
        else:
            p1 = _mm_vec(view.row, "p1", (0.0, 0.0))
            p2 = _mm_vec(view.row, "p2", (p1[0] + 1000.0, p1[1]))
            length = math.hypot(p2[0] - p1[0], p2[1] - p1[1]) or 1.0
            al = ((p2[0] - p1[0]) / length, (p2[1] - p1[1]) / length)
            ax = (al, (-al[1], al[0]))
        origin = _mm_vec(view.row, "p1") if not view.is_plan() \
            else (0.0, 0.0)
        for (u, v), low, high, tag in (
                (ax[0], u0, u1, "Trái"), (ax[1], v0, v1, "Dưới")):
            base = (origin[0] + u * low, origin[1] + v * low)
            view.clip_planes.append(
                _trim(f"Chi tiết {tag}", (-u, -v, 0.0),
                      (base[0], base[1], 0.0)))
            base2 = (origin[0] + u * high, origin[1] + v * high)
            view.clip_planes.append(
                _trim(f"Chi tiết {tag} trên", (u, v, 0.0),
                      (base2[0], base2[1], 0.0)))
        view.crop_u = (u0, u1)
        view.crop_v = (v0, v1)
    return view


# ---- the drawing's language -------------------------------------------------

def _ensure_layer(scene, name: str) -> None:
    from core.layers import Layer
    if scene.layer(name) is None:
        scene.layers.append(Layer(name))


def level_box_text(prefix: str, level_mm: float) -> str:
    """``FL:+2700`` — a level as the trade writes it (sign always shown,
    four digits)."""
    v = int(round(level_mm))
    sign = "-" if v < 0 else "+"
    return f"{prefix}:{sign}{abs(v):04d}"


def level_triangle_text(level_mm: float) -> str:
    """``+2.700`` — a level as an elevation's triangle states it."""
    v = float(level_mm) / 1000.0
    sign = "-" if v < 0 else "+"
    return f"{sign}{abs(v):.3f}"


def dimension_value(scene, value_m: float) -> str:
    """The text a dimension shows, through the document's own unit."""
    fmt = None
    if scene is not None:
        vp = getattr(scene, "dimension_style", None)
        if isinstance(vp, dict) and callable(vp.get("format")):
            fmt = vp["format"]
    if fmt is not None:
        try:
            return str(fmt(value_m))
        except Exception:               # noqa: BLE001 — a broken style hurts
            pass                        # the drawing, not the model
    from core.units import fmt_len
    return fmt_len(value_m)


def grid_axes(building, story) -> list:
    """Every axis of a storey's grids, in model mm.

    ``[(name, dir, offset_mm, lo, hi), …]`` — an axis is one straight
    line, ``dir`` the axis it runs ALONG and ``lo``/``hi`` how far it
    reaches (the other family's extremes plus the margin, which is where
    its bubbles stand). Two grids stacked on one storey merge: an office
    splits grids by block and reads them as one plan.
    """
    grids = [e for e in building.elements
             if str(e.get("story_id")) == str(story["id"])
             and e.get("type") == "grid"]
    if not grids:
        return []
    out: list = []
    all_x: list = []
    all_y: list = []
    for grid in grids:
        for axis in (grid.get("params") or {}).get("axes") or ():
            d = str(axis.get("dir") or "x")
            (all_y if d == "x" else all_x).append(
                float(axis.get("offset_mm") or 0.0))
    if not all_x or not all_y:
        return []
    margin = float(GRID_MARGIN_MM)
    for grid in grids:
        params = grid.get("params") or {}
        for axis in params.get("axes") or ():
            d = str(axis.get("dir") or "x")
            name = str(axis.get("name") or "").strip()
            off = float(axis.get("offset_mm") or 0.0)
            if d == "x":
                out.append((name, "x", off, all_x[0] - margin,
                            all_x[-1] + margin))
            else:
                out.append((name, "y", off, all_y[0] - margin,
                            all_y[-1] + margin))
    return out


def _grid_pen(scene):
    from core.layers import Layer
    layer = scene.layer(GRID_LAYER)
    if layer is None:
        layer = Layer(GRID_LAYER)
        scene.layers.append(layer)
    return layer


def draw_grid(scene, building, view: DrawingView, *, history=None,
              key=None) -> list:
    """Put a storey's grid on the plan: one line per axis, bubble at each end.

    The bubble is the axis' own NAME — "1", "A" — which is what a
    dimension or a note calls the line by; a grid without names is a
    drawing nobody can talk about, so the name is the point of the
    element, not decoration.
    """
    from core.history import AddTextLabelCommand
    from core.textlabel import TextLabel

    story = building.story(view.story_id) if view.story_id else None
    if story is None:
        return []
    axes = grid_axes(building, story)
    if not axes:
        return []
    _grid_pen(scene)
    z_cut = (float(story.get("z_mm", 0.0))
             + _mm_or(view.row.get("cut_mm"), DEFAULT_CUT_MM)) / 1000.0
    made: list = []
    for name, direction, offset, lo, hi in axes:
        a = QVector3D(lo / 1000.0, offset / 1000.0, z_cut)
        b = QVector3D(hi / 1000.0, offset / 1000.0, z_cut)
        if direction == "x":
            a = QVector3D(lo / 1000.0, offset / 1000.0, z_cut)
            b = QVector3D(hi / 1000.0, offset / 1000.0, z_cut)
        else:
            a = QVector3D(offset / 1000.0, lo / 1000.0, z_cut)
            b = QVector3D(offset / 1000.0, hi / 1000.0, z_cut)
        if history is not None:
            from core.history import AddEdgeCommand
            history.execute(AddEdgeCommand(a, b))
            edge = next((e for e in scene.mesh.edges
                         if (QVector3D(e.a) - a).length() < 1e-6
                         and (QVector3D(e.b) - b).length() < 1e-6), None)
        else:
            edge = scene.add_edge(a, b)
        if edge is not None:
            edge.layer = GRID_LAYER
            made.append(edge)
        for end in (a, b):
            bubble = TextLabel(QVector3D(end.x(), end.y(), z_cut),
                               QVector3D(0.0, 0.0, 0.0), name,
                               layer=GRID_LAYER)
            if history is not None:
                history.execute(AddTextLabelCommand(bubble))
            else:
                scene.text_labels.append(bubble)
            made.append(bubble)
    if key:
        _clear_annotations(scene, key)
        scene.bim_annotations.setdefault(key, []).extend(made)
    return made


def section_marks(building, story) -> list:
    """The section rows filed against a storey, ready to mark on its plan.

    A section drawing is only usable if the plan shows WHERE it cuts: the
    cut line, the direction the viewer looks, and the letter that matches
    the sheet. The rows live in the building's own settings (what the
    document editor writes), so this reads them rather than inventing a
    second place for the same data.

    Returns ``[(symbol, p1_mm, p2_mm, normal_xy), …]`` — the cut line's
    two ends in model mm, and the unit normal pointing the way the viewer
    stands.
    """
    rows = (building.settings or {}).get("sections") or []
    out: list = []
    for row in rows:
        if str(row.get("story_id") or "") not in ("", str(story["id"])):
            continue
        p1 = row.get("p1")
        p2 = row.get("p2")
        if not p1 or not p2:
            continue
        n = row.get("normal") or (0.0, -1.0)
        length = math.hypot(float(p2[0]) - float(p1[0]),
                            float(p2[1]) - float(p1[1]))
        if length < 1e-6:
            continue
        out.append((str(row.get("symbol") or row.get("name") or "A"),
                    (float(p1[0]), float(p1[1])),
                    (float(p2[0]), float(p2[1])),
                    (float(n[0]), float(n[1]))))
    return out


def opening_tags(building, story) -> list:
    """``[(name, x_mm, y_mm), …]`` — where each opening's mark stands.

    A door or window is named by its mark (``D1``, ``W2``) because that is
    the name its schedule row carries: a schedule nobody can point at on
    the plan is a list, not a drawing. The mark stands at the CENTRE of
    the opening, in model mm.
    """
    out: list = []
    for element in building.elements:
        if str(element.get("story_id")) != str(story["id"]):
            continue
        if element.get("type") not in ("door", "window"):
            continue
        params = element.get("params") or {}
        mark = str(params.get("name") or "").strip()
        if not mark:
            continue
        host = building.element(str(params.get("host_wall_id") or ""))
        if host is None:
            continue
        hp = host.get("params") or {}
        a = hp.get("baseline_start_mm")
        b = hp.get("baseline_end_mm")
        if not a or not b:
            continue
        length = math.hypot(float(b[0]) - float(a[0]),
                            float(b[1]) - float(a[1]))
        if length < 1e-6:
            continue
        u = float(params.get("offset_along_wall_mm", 0.0) or 0.0)
        al = ((float(b[0]) - float(a[0])) / length,
              (float(b[1]) - float(a[1])) / length)
        out.append((mark, float(a[0]) + al[0] * u,
                    float(a[1]) + al[1] * u))
    return out


def annotate_plan(scene, building, view: DrawingView, *, history=None,
                  dimensions=True, levels=True, rooms=True, scale_denom=None,
                  offset=None, key=None):
    """Write a plan's dimension chains, levels and room stamps.

    Every entity is added through ``history`` (pass the window's History,
    or wrap in a ``CompoundCommand``), so the whole drawing is ONE undo
    step and the .igz carries it like any other annotation. Without a
    history the entities are appended directly — what a headless test or a
    script wants. Returns the entities added.

    ``key`` names the drawing these annotations belong to. Passing one
    makes the call REGENERABLE: whatever the previous run wrote under that
    key is removed first, so re-issuing a revised model updates the
    drawing instead of stacking a second set of dimensions on it.

    The chains stand where the trade puts them — 10 mm of paper for the
    openings' edges and 18 for the wall ends, OUTSIDE the house — measured
    off the wall faces, so a 1:100 plan and a 1:50 detail of the same wall
    agree.
    """
    from core.dimension import Dimension
    from core.history import AddDimensionCommand, AddTextLabelCommand
    from core.textlabel import TextLabel

    if key:
        _clear_annotations(scene, key)

    def add(command, entity, bucket):
        if history is not None:
            history.execute(command)
        else:
            bucket.append(entity)
        if key:
            scene.bim_annotations.setdefault(key, []).append(entity)
        added.append(entity)

    story = building.story(view.story_id) if view.story_id else None
    if story is None:
        raise ValueError("Bản vẽ không gắn với tầng nào.")
    denom = float(scale_denom or view.scale_denom or 100.0)
    story_z = float(story.get("z_mm", 0.0))
    added: list = []
    _ensure_layer(scene, ANNOT_LAYER)

    walls = [e for e in building.elements
             if str(e.get("story_id")) == str(story["id"])
             and e.get("type") == "wall"]
    if not walls:
        return added

    if dimensions:
        for chain in wall_chains(building, walls):
            stand_off = (offset if offset is not None
                         else (DETAIL_OFFSET_PAPER if len(chain) > 1
                               else TOTAL_OFFSET_PAPER))
            for a, b, side in chain:
                # The chain stands ``stand_off`` PAPER mm off the wall's
                # OUTER FACE: paper mm × the scale denominator is the model
                # millimetres it must be pulled, plus half the wall to clear
                # the centreline the baseline runs along.
                reach = (float(a[2]) / 2.0 + stand_off * denom) / 1000.0
                z_cut = (story_z + _mm_or(view.row.get("cut_mm"),
                                          DEFAULT_CUT_MM)) / 1000.0
                dim = Dimension(
                    QVector3D(a[0] / 1000.0, a[1] / 1000.0, z_cut),
                    QVector3D(b[0] / 1000.0, b[1] / 1000.0, z_cut),
                    QVector3D(side[0] * reach, side[1] * reach, 0.0),
                    layer=ANNOT_LAYER)
                add(AddDimensionCommand(dim), dim, scene.dimensions)

    if levels:
        area = _story_extent(building, story)
        z_top = story_z + float(story.get("height_mm", 3300.0))
        for level_mm, prefix, dy in ((story_z, "FL", 0.0),
                                     (z_top, "CL", 0.0)):
            text = level_box_text(prefix, level_mm)
            label = TextLabel(
                QVector3D((area[2] + 600.0) / 1000.0,
                          (area[1] - 600.0) / 1000.0,
                          (story_z + 1500.0) / 1000.0),
                QVector3D(0.0, 0.0, (level_mm - story_z) / 1000.0 + dy),
                text, layer=ANNOT_LAYER)
            add(AddTextLabelCommand(label), label, scene.text_labels)

    for symbol, p1, p2, normal in section_marks(building, story):
        # The mark is the section's own letter plus one arrow per end,
        # turned the way the viewer looks — the plan's answer to "where
        # does this section come from".
        for end in (p1, p2):
            label = TextLabel(
                QVector3D(end[0] / 1000.0, end[1] / 1000.0,
                          (story_z + float(view.row.get("cut_mm")
                                           or DEFAULT_CUT_MM)) / 1000.0),
                QVector3D(0.0, 0.0, 0.0), symbol, layer=ANNOT_LAYER)
            add(AddTextLabelCommand(label), label, scene.text_labels)
        cut = Dimension(
            QVector3D(p1[0] / 1000.0, p1[1] / 1000.0,
                      (story_z + float(view.row.get("cut_mm")
                                       or DEFAULT_CUT_MM)) / 1000.0),
            QVector3D(p2[0] / 1000.0, p2[1] / 1000.0,
                      (story_z + float(view.row.get("cut_mm")
                                       or DEFAULT_CUT_MM)) / 1000.0),
            QVector3D(0.0, 0.0, 0.0), text="", layer=ANNOT_LAYER)
        add(AddDimensionCommand(cut), cut, scene.dimensions)

    for mark, mx, my in opening_tags(building, story):
        # The mark is the drawing's own word for the opening, so it lands
        # on the annotation layer with the dimensions and the room stamps.
        label = TextLabel(
            QVector3D(mx / 1000.0, my / 1000.0,
                      (story_z + _mm_or(view.row.get("cut_mm"),
                                        DEFAULT_CUT_MM)) / 1000.0),
            QVector3D(0.0, 0.0, 0.0), mark, layer=ANNOT_LAYER)
        add(AddTextLabelCommand(label), label, scene.text_labels)

    if rooms:
        for zone in [e for e in building.elements
                     if str(e.get("story_id")) == str(story["id"])
                     and e.get("type") == "zone"]:
            outline = (zone.get("params") or {}).get("outline_mm") or []
            if len(outline) < 3:
                continue
            cx = sum(float(p[0]) for p in outline) / len(outline)
            cy = sum(float(p[1]) for p in outline) / len(outline)
            derived = (zone.get("derived") or {})
            area = derived.get("area_m2")
            # A name lives with the element's parameters (that is where the
            # panel writes it); `derived` may echo it, the element itself
            # does not carry one.
            params = zone.get("params") or {}
            name = str(params.get("name") or derived.get("name") or "Phòng")
            text = name if area is None else f"{name}\n{area:.2f} m²"
            label = TextLabel(
                QVector3D(cx / 1000.0, cy / 1000.0,
                          (story_z + _mm_or(view.row.get("cut_mm"),
                                            DEFAULT_CUT_MM)) / 1000.0),
                QVector3D(0.0, 0.0, 0.0), text, layer=ANNOT_LAYER)
            add(AddTextLabelCommand(label), label, scene.text_labels)
    return added


def _clear_annotations(scene, key: str) -> list:
    """Drop what a previous run of this drawing wrote — and only that.

    A drawing's dimensions and stamps are DERIVED data. Left in place they
    would be re-issued on top of themselves, so a revised model would show
    two dimension chains disagreeing about the same wall. User-placed
    annotations live outside this registry and are never touched.
    """
    registry = getattr(scene, "bim_annotations", None)
    if registry is None:
        return []
    gone = list(registry.pop(key, ()))
    for entity in gone:
        if entity in scene.dimensions:
            scene.dimensions.remove(entity)
        if entity in scene.text_labels:
            scene.text_labels.remove(entity)
        scene.selection.discard(entity)
    return gone


def wall_chains(building, walls) -> list:
    """The two dimension chains of a plan, outside the house (public: the
    composer, the E2E script and the diff of a revision all read it).

    A chain is a list of ``(a, b, side)`` in mm: the ends of every opening
    on the wall (its own two edges) in the detail chain, and the wall's own
    two ends in the total chain. ``side`` is the unit normal pointing AWAY
    from the house, so both chains stand off the outer face — the reference's
    rule, and the reason a drawing never buries its dimensions in the walls.
    """
    out: list = []
    mids: list = []
    for wall in walls:
        params = wall.get("params") or {}
        p0 = params.get("baseline_start_mm")
        p1 = params.get("baseline_end_mm")
        if not p0 or not p1:
            continue
        mids.append(((float(p0[0]) + float(p1[0])) / 2.0,
                     (float(p0[1]) + float(p1[1])) / 2.0))
    if not mids:
        return out
    cx = sum(m[0] for m in mids) / len(mids)
    cy = sum(m[1] for m in mids) / len(mids)
    for wall in walls:
        params = wall.get("params") or {}
        p0 = params.get("baseline_start_mm")
        p1 = params.get("baseline_end_mm")
        if not p0 or not p1:
            continue
        a = (float(p0[0]), float(p0[1]))
        b = (float(p1[0]), float(p1[1]))
        length = math.hypot(b[0] - a[0], b[1] - a[1])
        if length < 1e-6:
            continue
        al = ((b[0] - a[0]) / length, (b[1] - a[1]) / length)
        nrm = (-al[1], al[0])
        thickness = float(params.get("thickness_mm", 200.0) or 200.0)
        mid = ((a[0] + b[0]) / 2.0, (a[1] + b[1]) / 2.0)
        face_out = ((mid[0] - cx) * nrm[0] + (mid[1] - cy) * nrm[1])
        side = nrm if face_out >= 0 else (-nrm[0], -nrm[1])
        face = (mid[0] + side[0] * thickness / 2.0,
                mid[1] + side[1] * thickness / 2.0)
        del face                                # the stand-off is in `offset`
        chain: list = []
        anchors = [(0.0, 0.0), (length, 0.0)]
        for element in building.elements:
            eparams = element.get("params") or {}
            if str(eparams.get("host_wall_id") or "") != str(wall.get("id")):
                continue
            if element.get("type") not in ("door", "window"):
                continue
            u = float(eparams.get("offset_along_wall_mm", 0.0) or 0.0)
            half = float(eparams.get("width_mm", 0.0) or 0.0) / 2.0
            anchors.extend([(u - half, 0.0), (u + half, 0.0)])
        anchors.sort(key=lambda t: t[0])
        # Dedupe (two openings sharing an edge is one dimension).
        clean: list = []
        for u, _ in anchors:
            if not clean or abs(u - clean[-1][0]) > 0.5:
                clean.append((u, 0.0))
        for i in range(len(clean) - 1):
            u0 = clean[i][0]
            u1 = clean[i + 1][0]
            if u1 - u0 < 0.5:
                continue
            chain.append(((a[0] + al[0] * u0, a[1] + al[1] * u0,
                           thickness),
                          (a[0] + al[0] * u1, a[1] + al[1] * u1, thickness),
                          side))
        total = [((a[0], a[1], thickness), (b[0], b[1], thickness), side)]
        if len(chain) > 1:
            out.append(chain)                       # the openings' chain
            out.append(total)                       # the wall's own chain
        else:
            out.append(total)
    return out


def _story_extent(building, story) -> tuple:
    return story_box(building, story)


# ---- putting a drawing on a sheet -------------------------------------------

#: The frame label a sheet shows under a view, per drawing kind.
VIEW_LABELS = {
    KIND_STORY: "Mặt bằng",
    KIND_ROOF: "Mặt bằng mái",
    KIND_TOP: "Nhìn trên",
    KIND_SECTION: "Mặt cắt",
    KIND_ELEVATION: "Mặt đứng",
    KIND_INTERIOR: "Mặt đứng nội thất",
    KIND_DETAIL: "Chi tiết",
}


def _place_clip_names(view: DrawingView) -> None:
    """Tag every trim plane with the drawing it belongs to.

    A saved scene keeps its rule as data, and the plane's own name is what
    tells a reader (and a later migration) which drawing published it.
    """
    for i, sp in enumerate(view.clip_planes):
        if not sp.name:
            sp.name = f"{view.kind}:{i}"


def install_view_planes(scene, view: DrawingView) -> list:
    """Register a drawing's cutting planes in the scene, once each.

    A frame renders through a saved scene, and a scene refers to its cut by
    uid — so the plane has to BE in the model's list for the frame to find
    it. That is also what the reference does with its per-storey planes:
    the plan's cut belongs to the storey, not to the moment it was drawn.
    Planes already present (same uid) are left alone. Returns what was
    added, so a caller can take them away again.
    """
    added: list = []
    known = {getattr(sp, "uid", None) for sp in
             getattr(scene, "section_planes", None) or ()}
    for sp in view.section_planes:
        if getattr(sp, "uid", None) in known:
            continue
        if not sp.name:
            sp.name = view.name or view.kind
        scene.section_planes.append(sp)
        added.append(sp)
    return added


def place_on_sheet(sheet, view: DrawingView, scene, *, name: str = "",
                   x_mm: float | None = None, y_mm: float | None = None,
                   w_mm: float | None = None, h_mm: float | None = None,
                   title: bool = True, style: str = "vectorial",
                   replace=None):
    """Put a drawing on a sheet as a saved scene + a frame that shows it.

    The two halves are one operation because they are one thing: a FRAME
    renders what a SCENE says, so the drawing's own camera and its trimming
    planes must be recorded as a scene (which is also what makes the sheet
    independent of where the live model happens to be left — the whole
    point of stating a drawing as a rule). Returns the frame.
    """
    from core.composition import MarcoVista
    from core.saved_views import SavedView

    _place_clip_names(view)
    install_view_planes(scene, view)
    scene_name = name or view.name or VIEW_LABELS.get(
        view.kind, view.kind)
    existing = next((sv for sv in scene.saved_views
                     if sv.name == scene_name), None)
    viewpoint = view.camera()
    if existing is None:
        existing = SavedView.capture(scene_name, scene, viewpoint)
        scene.saved_views.append(existing)
    else:
        # A re-issued drawing keeps its NAME and takes the NEW rule: the
        # camera, the distance, the cut and the trims are the drawing's,
        # and the storey may have risen since the last issue. Reusing the
        # old scene wholesale would reprint yesterday's cut with today's
        # model behind it — the picture nobody checks until it is printed.
        existing.target = (float(viewpoint.target.x()),
                           float(viewpoint.target.y()),
                           float(viewpoint.target.z()))
        existing.distance = float(viewpoint.distance)
        existing.yaw = float(viewpoint.yaw)
        existing.pitch = float(viewpoint.pitch)
        existing.fov_deg = float(viewpoint.fov_deg)
        existing.perspective = bool(viewpoint.perspective)
        existing.hidden_layers = []
    # The cut: a scene records which plane is active by uid, and the
    # capture above ran with whatever the VIEWPORT had on — so the
    # drawing's own cut is written in explicitly, or recalling the scene
    # would switch the plan's +1200 cut off.
    if view.section_planes:
        existing.section = {
            "active": view.section_planes[0].uid,
            "planes_shown": bool(getattr(scene, "show_section_planes",
                                         True)),
            "cuts_shown": True}
    # The view filter: a layout shows one trade, so its scene hides the
    # other trades' layers. Recorded on the scene, which is what makes the
    # frame independent of the live layer state.
    if view.hidden_layers:
        existing.hidden_layers = [str(n) for n in view.hidden_layers]
    existing.drawing = view.to_dict()

    page_w, page_h = sheet.page_size_mm()
    margin = float(sheet.margin_mm)
    frame = MarcoVista(
        x_mm=margin if x_mm is None else float(x_mm),
        y_mm=margin if y_mm is None else float(y_mm),
        w_mm=(page_w - 2 * margin) if w_mm is None else float(w_mm),
        h_mm=(page_h - 2 * margin) if h_mm is None else float(h_mm),
        scale_n=float(view.scale_denom),
        view_key=f"scene:{scene_name}",
        style=str(style))
    if title:
        frame.show_title = True
        frame.title_text = name or scene_name
        frame.title_style = "layout"
        frame.title_scale = True
    if replace is not None:
        # Re-issuing an existing sheet: the frame is already there, and
        # only its rule is refreshed (the scene above). Appending a second
        # frame would double the drawing on the page.
        scene.version += 1
        return replace
    sheet.frames.append(frame)
    scene.version += 1
    return frame
