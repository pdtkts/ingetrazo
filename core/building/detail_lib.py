# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Marco Sumari Tellez and IngeTrazo contributors.
"""The detail library: the standard details an office reissues every job.

Every Vietnamese office keeps the same set of construction details —
floor build-up, wall footing, flat roof edge, stair landing, door jamb, WC
floor — and re-draws them for each project. Here they are stated once, as
data: a stack of layers, each a material with a thickness, plus the
annotation the detail carries (thickness callouts, the level marks).

A detail is a STACK, not a drawing: :func:`stack_rect` is the geometry of
one detail in its own local millimetres and :func:`insert_detail_on_sheet`
places that drawing on a sheet's frame through the composer's own items —
so a detail is editable on the sheet afterwards like anything else placed
there. That is the line the rest of the drawing code already draws: the
model is the truth for plans and sections, and a library detail is a
standard the office owns.

Thicknesses follow the usual Vietnamese build-ups (TCVN 5574 for concrete
cover, the 20 mm mortar beds and the 100 mm bedding course common in
residential work); they are defaults a project may change, not a
specification.
"""
from __future__ import annotations

#: One layer of a detail: ``(name, material, thickness_mm, pattern)``.
#: ``pattern`` is a name from :mod:`core.building.patterns`, or "" for a
#: layer that is not hatched (insulation is banded, glass is broken).
LAYERS_FLOOR = (
    ("Gạch lát", "ceramic", 10.0, "Tô đặc xám"),
    ("Vữa lót", "mortar", 20.0, "Cát đệm"),
    ("Lớp chống thấm", "membrane", 4.0, "Chống thấm"),
    ("Bê tông gạch vỡ", "concrete_fill", 100.0, "Bê tông (lót)"),
    ("Đất đầm chặt", "earth", 0.0, ""),
)
LAYERS_ROOF = (
    ("Gạch chống nóng", "brick", 100.0, "Tường gạch (cắt)"),
    ("Vữa tạo dốc", "mortar", 30.0, "Cát đệm"),
    ("Chống thấm", "membrane", 4.0, "Chống thấm"),
    ("Bê tông mái", "concrete", 120.0, "Bê tông cốt thép"),
    ("Vữa trát trần", "mortar", 15.0, "Cát đệm"),
)
LAYERS_STAIR = (
    ("Mặt bậc đá", "stone", 20.0, "Đá granite"),
    ("Vữa lót bậc", "mortar", 20.0, "Cát đệm"),
    ("Bản thang BTCT", "concrete", 120.0, "Bê tông cốt thép"),
    ("Vữa trát bụng thang", "mortar", 15.0, "Cát đệm"),
)
LAYERS_DOOR = (
    ("Khuôn cửa gỗ", "wood", 100.0, "Gỗ"),
    ("Khe hở", "gap", 10.0, ""),
    ("Tường gạch", "brick", 220.0, "Tường gạch (cắt)"),
    ("Vữa trát", "mortar", 15.0, "Cát đệm"),
)
LAYERS_WC = (
    ("Gạch ốp lát", "ceramic", 10.0, "Tô đặc xám"),
    ("Vữa lót", "mortar", 20.0, "Cát đệm"),
    ("Chống thấm", "membrane", 4.0, "Chống thấm"),
    ("Bê tông sàn", "concrete", 100.0, "Bê tông cốt thép"),
    ("Vữa trát trần", "mortar", 15.0, "Cát đệm"),
)

#: The library: ``key -> {name, layers, note}``. ``name`` is the Vietnamese
#: title the sheet prints; ``note`` is the line a detail carries when the
#: office needs to say something the drawing cannot.
DETAILS: dict = {
    "floor_tile": {
        "name": "Chi tiết sàn lát gạch",
        "layers": LAYERS_FLOOR,
        "note": "Cao độ hoàn thiện +0.000 so với mặt kết cấu.",
    },
    "roof_flat": {
        "name": "Chi tiết mái bằng chống nóng",
        "layers": LAYERS_ROOF,
        "note": "Tạo dốc 2% về phía miệng thu nước.",
    },
    "stair_step": {
        "name": "Chi tiết bậc thang",
        "layers": LAYERS_STAIR,
        "note": "Bậc rộng 260, cổ bậc 170 — kiểm tra theo tầng.",
    },
    "door_jamb": {
        "name": "Chi tiết khuôn cửa đi",
        "layers": LAYERS_DOOR,
        "note": "Khuôn gỗ nhóm II, ngậm tường 60 mm mỗi bên.",
    },
    "wc_floor": {
        "name": "Chi tiết sàn vệ sinh",
        "layers": LAYERS_WC,
        "note": "Chống thấm vén tường 300 mm, thử nước 24 giờ.",
    },
}

#: The width the drawn stack spans, in millimetres, and the height each
#: named layer with a thickness of 0 is drawn with (earth, and any layer
#: stated as "how far it goes", not "how thick it is").
DETAIL_WIDTH_MM = 900.0
UNBOUNDED_LAYER_MM = 120.0


def keys() -> list:
    """Every detail key, in the order the library declares them."""
    return list(DETAILS)


def detail(key: str) -> dict:
    """The record of ``key``; raises ``KeyError`` for an unknown one."""
    return DETAILS[str(key)]


def name(key: str) -> str:
    return str(detail(key)["name"])


def stack_rect(key: str) -> tuple:
    """``(rect, layers)`` of a detail in its own local millimetres.

    ``rect`` is ``(0, 0, DETAIL_WIDTH_MM, total_height)`` and ``layers`` is
    ``[(name, pattern, y0, y1), …]`` from the bottom up, so a renderer can
    hatch each band with its own pattern without knowing the table.
    """
    record = detail(key)
    out: list = []
    y = 0.0
    for label, _material, thickness, pattern in record["layers"]:
        h = float(thickness) or float(UNBOUNDED_LAYER_MM)
        out.append((str(label), str(pattern), y, y + h))
        y += h
    return (0.0, 0.0, float(DETAIL_WIDTH_MM), y), out


def annotation(key: str) -> list:
    """``[(text, y_mm), …]`` — the callout on each layer, bottom up."""
    record = detail(key)
    out: list = []
    y = 0.0
    for label, _material, thickness, _pattern in record["layers"]:
        h = float(thickness) or float(UNBOUNDED_LAYER_MM)
        if thickness:
            out.append((f"{label} — {int(round(float(thickness)))} mm",
                        y + h / 2.0))
        else:
            out.append((label, y + h / 2.0))
        y += h
    note = str(record.get("note") or "")
    if note:
        out.append((note, y + 40.0))
    return out


def insert_detail_on_sheet(sheet, key: str, *, x_mm: float | None = None,
                           y_mm: float | None = None,
                           scale_denom: float = 10.0) -> dict:
    """Draw a library detail on a sheet, in the sheet's own millimetres.

    Composed of the same items the composer's editor works with — the
    bands as outlined shapes, the callouts as labels, the title as text —
    so the detail can be dragged, restyled, grouped and re-exported like
    anything drawn by hand. A band whose material has a pattern is filled
    solid, which is what the composer's own shapes can render today; the
    pattern table in :mod:`core.building.patterns` is geometry for the
    drawings and the DXF, not for a sheet item.

    A detail is drawn at 1:10 by default: one model millimetre is 0.1 mm
    of paper. Returns where it landed and what was placed.
    """
    from core.composition import EtiquetaItem, FormaItem, TextoItem

    rect, layers = stack_rect(key)
    k = 1.0 / max(float(scale_denom), 1e-6)
    x0 = 40.0 if x_mm is None else float(x_mm)
    y0 = 40.0 if y_mm is None else float(y_mm)
    w = (rect[2] - rect[0]) * k
    # A detail already on the sheet is REPLACED, not stacked: the items
    # carry the detail's own key in their names, so a second insert
    # doubles the drawing unless the old ones go first (the reference
    # geometry is the same stack — nothing is gained by two of it).
    tag = f"__detail__{key}"
    sheet.shapes[:] = [item for item in sheet.shapes
                       if not str(getattr(item, "list_name", "")
                                  ).startswith(tag)]
    sheet.etiquetas[:] = [item for item in sheet.etiquetas
                          if not str(getattr(item, "list_name", "")
                                     ).startswith(tag)]
    sheet.texts[:] = [item for item in sheet.texts
                      if not str(getattr(item, "list_name", "")
                                 ).startswith(tag)]
    made = {"bands": 0, "labels": 0, "x_mm": x0, "y_mm": y0, "w_mm": w,
            "h_mm": (rect[3] - rect[1]) * k, "scale": float(scale_denom),
            "name": name(key)}
    for label, pattern, ya, yb in layers:
        band = FormaItem(kind="rect", x_mm=x0, y_mm=y0 + ya * k, w_mm=w,
                         h_mm=(yb - ya) * k, fill=bool(pattern))
        band.list_name = f"__detail__{key}__{label}"
        sheet.shapes.append(band)
        made["bands"] += 1
        callout = EtiquetaItem(x_mm=x0 + w + 6.0,
                               y_mm=y0 + (ya + yb) / 2.0 * k,
                               ax_mm=-6.0, ay_mm=0.0, text=label,
                               size_pt=7.0)
        callout.list_name = f"__detail__{key}__lb_{label}"
        sheet.etiquetas.append(callout)
        made["labels"] += 1
    title = TextoItem(x_mm=x0, y_mm=max(y0 - 10.0, 2.0), w_mm=260.0,
                      text=f"{name(key)}  1:{int(scale_denom)}",
                      size_pt=10.0, bold=True, list_name=f"__detail__{key}")
    sheet.texts.append(title)
    made["title"] = title.text
    return made
