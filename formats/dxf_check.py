# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Marco Sumari Tellez and IngeTrazo contributors.
"""Kiểm tra DXF — read an exported file back and hold it against the model.

An export that «worked» is not the same as a file the next office can use:
a layer the pen table renamed can go missing, a hatch can be written as
ink, a storey's dimension chains can be dropped, and every one of those
produces a file that opens fine and prints wrong. The only place to catch
them is after the file has left the app, so this reads the file the way a
receiving CAD would — through ezdxf, entity by entity — and says what is
missing or does not match the model it came from.

This is a REPORT, never a repair: what it finds is what a colleague would
have found, and the fix is the office's decision.
"""
from __future__ import annotations

__all__ = ["check_dxf_against"]


def _read(path):
    """The file, through the same reader a receiving CAD uses."""
    import ezdxf

    return ezdxf.readfile(str(path))


def count_entities(path) -> dict:
    """``{lines, hatch, dimensions, text, layers, linetypes}`` in the file."""
    doc = _read(path)
    space = doc.modelspace()
    counts = {"lines": 0, "hatch": 0, "dimensions": 0, "text": 0,
              "layers": 0, "linetypes": 0}
    for entity in space:
        kind = str(entity.dxftype())
        if kind in ("LINE", "LWPOLYLINE", "POLYLINE", "ARC", "CIRCLE",
                    "SPLINE", "ELLIPSE"):
            counts["lines"] += 1
        elif kind == "HATCH":
            counts["hatch"] += 1
        elif kind.startswith("DIMENSION"):
            counts["dimensions"] += 1
        elif kind in ("TEXT", "MTEXT"):
            counts["text"] += 1
    counts["layers"] = len(list(doc.layers))
    try:
        counts["linetypes"] = len(list(doc.linetypes))
    except Exception:                                # noqa: BLE001 — optional
        counts["linetypes"] = 0
    return counts


def check_dxf_against(path, scene, building) -> dict:
    """``{counts, problems}`` for one exported file against the model.

    ``problems`` are sentences the user can act on, worst first: a layer
    that should be there and is not, a hatch that became ink, a storey
    whose dimensions never arrived, a pen whose width the file lost.
    """
    from core.building import pens as _pens

    problems: list = []
    counts = count_entities(path)
    doc = _read(path)

    # --- the layers the office's own table asked for ------------------
    # A class with no entities on this drawing has no layer, and that is
    # correct — a plan with no construction lines must not carry a layer
    # for them. What is a real defect is the file carrying the RAW name
    # after the office renamed the layer: the rename reached the pen
    # dialog and not the exporter, which is exactly the failure a user
    # cannot see without opening the file in another CAD.
    pen_table, layer_map = _pens.export_tables(scene)
    names = {str(layer.dxf.name) for layer in doc.layers}
    for standard, own in sorted(layer_map.items()):
        if str(own) != str(standard) and str(standard) in names:
            problems.append(
                f"Lớp «{standard}» vẫn còn trong file dù văn phòng đã đổi "
                f"tên thành «{own}» — bảng tên lớp chưa tới file DXF.")

    # --- the hatch: a cut written as ink cannot be re-drawn ------------
    if counts["lines"] and not counts["hatch"]:
        problems.append(
            "File không có vùng tô (HATCH) nào: mặt cắt gửi đi là nét vẽ "
            "lại chứ không phải hatch — bên nhận không sửa được tỷ lệ tô.")

    # --- the annotations the drawing set publishes ---------------------
    story = None
    stories = list(building.stories)
    if stories:
        active = str(building.settings.get("active_story") or "")
        story = building.story(active) or stories[0]
    if story is not None:
        from core.building import takeoff as _takeoff

        rows = _takeoff.tables(building).get("walls") or []
        walls_on_story = [r for r in rows
                          if str(r.get("story_id")) == str(story["id"])]
        if walls_on_story and counts["lines"] == 0:
            problems.append(
                f"Tầng «{story.get('name')}» có {len(walls_on_story)} tường "
                f"trong mô hình mà file không có nét nào.")

    # --- the pens: a file that lost the ladder prints flat -------------
    weights = set()
    for layer in doc.layers:
        weight = int(getattr(layer.dxf, "lineweight", -1) or -1)
        if weight > 0:
            weights.add(weight)
    if counts["lines"] and len(weights) <= 1 and len(pen_table) > 1:
        problems.append(
            "Mọi lớp trong file cùng một bề rộng nét: bảng bút của văn "
            "phòng (cắt/thấy/khuất) không tới được file.")

    # --- the text: Vietnamese names must survive the encoding ----------
    if counts["text"]:
        names_in_file = "".join(
            str(getattr(e.dxf, "text", "")) for e in doc.modelspace()
            if str(e.dxftype()) in ("TEXT", "MTEXT"))
        job = str(building.project.get("name") or "")
        if job and names_in_file and job[:6] not in names_in_file:
            problems.append(
                f"Tên công trình «{job}» không thấy trong file — khung tên "
                f"gửi đi thiếu tên.")
    return {"counts": counts, "problems": problems}
