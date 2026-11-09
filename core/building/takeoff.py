# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Marco Sumari Tellez and IngeTrazo contributors.
"""The takeoff — quantities from the building model, in the trade's tables.

A quantity that has to be argued over is useless, so the rule here is that
every number is either **stored on the element** by its builder (``derived``:
a wall's net elevation area, a slab's own area minus its holes, a column's
section) or is a count. Nothing is measured off the mesh, so the table agrees
with the drawings because both come from the same parameters.

The tables are the ones a Vietnamese priced bill of quantities is written
from, with their exact column labels:

``zones``    Tầng · Số · Tên phòng · Loại · Diện tích (m²)
``openings`` Tầng · Loại · Mã · Rộng (mm) · Cao (mm) · Cao độ đáy (mm) · Số lượng
``walls``    Tầng · Vật liệu · Dày (mm) · Dài (m) · Cao (m) · Diện tích (m²)
``slabs``    Tầng · Vật liệu · Dày (mm) · Diện tích (m²) · Thể tích (m³)
``columns``  Tầng · Mã · Tiết diện · Số lượng · Thể tích (m³)
``beams``    Tầng · Mã · Tiết diện (b x h) · Số lượng · Dài (m)

The CSV export is written for the way the numbers are actually used: `;` as
the separator, a comma as the decimal mark, a BOM and CRLF — the combination
Excel expects on a Vietnamese machine, where a plain `.csv` opens with the
whole table in one column.
"""
from __future__ import annotations

from core.building import builder as builders
from core.building import elements as schemas

#: Column labels per table, in order.
HEADERS = {
    "zones": ("Tầng", "Số", "Tên phòng", "Loại", "Diện tích (m²)"),
    "openings": ("Tầng", "Loại", "Mã", "Rộng (mm)", "Cao (mm)",
                 "Cao độ đáy (mm)", "Số lượng"),
    # The wall table states BOTH rules: the gross area a priced bill is
    # written from, and the deduction that brings it to what the wall
    # actually is. Two offices reading one report must be able to
    # reconcile them without a phone call.
    "walls": ("Tầng", "Vật liệu", "Dày (mm)", "Dài (m)", "Cao (m)",
              "Diện tích (m²)", "Trừ lỗ mở (m²)", "Thực tế (m²)",
              "Khối tích (m³)"),
    "slabs": ("Tầng", "Vật liệu", "Dày (mm)", "Diện tích (m²)",
              "Thể tích (m³)"),
    # A column and a beam state the same five things plus their LENGTH —
    # and a steel member its MASS, which the row carries only when the
    # member came off the rolled-section table. The mass column is
    # declared here because the header list is the table's contract with
    # the spreadsheet that receives it, and a column that appears without
    # being declared breaks every reader that maps by position.
    "columns": ("Tầng", "Mã", "Tiết diện", "Số lượng", "Thể tích (m³)",
                "Dài (m)", "KL (kg)"),
    "beams": ("Tầng", "Mã", "Tiết diện (b x h)", "Số lượng", "Dài (m)",
              "KL (kg)"),
}

#: Element type → the opening label its rows carry.
OPENING_LABELS = {
    "door": "Cửa đi",
    "window": "Cửa sổ",
    "curtain_wall": "Vách kính",
}


def tables(building) -> dict:
    """Every table, plus the totals the report reads."""
    derived = _derive(building)
    out: dict = {
        "zones": _zones(building, derived),
        "openings": _openings(building, derived),
        "walls": _walls(building, derived),
        "slabs": _slabs(building, derived),
        "columns": _columns(building, derived),
        "beams": _beams(building, derived),
    }
    out["totals"] = _totals(out)
    return out


# ---- per-table builders -----------------------------------------------------

def _zones(building, derived):
    rows = []
    for el in building.elements:
        if el.get("type") != "zone":
            continue
        params = el.get("params") or {}
        story = building.story(str(el.get("story_id") or ""))
        area = _num(derived, el, "area_m2")
        rows.append({
            "Tầng": _story_name(story),
            "Số": str(params.get("number") or ""),
            "Tên phòng": str(params.get("name") or ""),
            "Loại": str(params.get("category") or ""),
            "Diện tích (m²)": round(area, 2),
        })
    rows.sort(key=lambda r: (r["Tầng"], r["Số"], r["Tên phòng"]))
    return rows


def _openings(building, derived):
    """One row per opening *kind*, with the identical ones counted."""
    groups: dict = {}
    for el in building.elements:
        kind = str(el.get("type"))
        if kind not in OPENING_LABELS:
            continue
        params = el.get("params") or {}
        story = building.story(str(el.get("story_id") or ""))
        key = (_story_name(story), kind, str(params.get("name") or ""),
               round(float(params.get("width_mm", 0.0) or 0.0)),
               round(float(params.get("height_mm", 0.0) or 0.0)),
               round(float(params.get("sill_height_mm", 0.0) or 0.0)))
        row = groups.get(key)
        if row is None:
            groups[key] = {
                "Tầng": key[0],
                "Loại": OPENING_LABELS[kind],
                "Mã": key[2],
                "Rộng (mm)": key[3],
                "Cao (mm)": key[4],
                "Cao độ đáy (mm)": key[5],
                "Số lượng": 1,
            }
        else:
            row["Số lượng"] += 1
    return sorted(groups.values(), key=lambda r: (r["Tầng"], r["Loại"],
                                                  -r["Rộng (mm)"]))


def _walls(building, derived):
    rows = []
    for el in building.elements:
        if el.get("type") != "wall":
            continue
        params = el.get("params") or {}
        story = building.story(str(el.get("story_id") or ""))
        mat = schemas.material(params.get("building_material_id"))
        length_m = _num(derived, el, "length_mm") / 1000.0
        height_m = _num(derived, el, "effective_height_mm") / 1000.0
        gross = _num(derived, el, "gross_area_m2")
        net = _num(derived, el, "net_area_m2")
        rows.append({
            "Tầng": _story_name(story),
            "Vật liệu": str(mat.get("name") or ""),
            "Dày (mm)": round(float(params.get("thickness_mm", 0.0) or 0.0)),
            "Dài (m)": round(length_m, 2),
            "Cao (m)": round(height_m, 2),
            # Gross area — what a priced bill is written from, and it does
            # NOT deduct the openings (those are their own line).
            "Diện tích (m²)": round(gross, 2),
            # …and the deduction stated, so the two rules can be checked
            # against each other instead of argued about: net is what the
            # wall actually is, gross minus every opening over it.
            "Trừ lỗ mở (m²)": round(gross - net, 2),
            "Thực tế (m²)": round(net, 2),
            "Khối tích (m³)": round(_num(derived, el, "volume_m3"), 3),
        })
    return rows


def _slabs(building, derived):
    rows = []
    for el in building.elements:
        kind = str(el.get("type"))
        if kind not in ("slab", "ceiling", "roof"):
            continue
        params = el.get("params") or {}
        story = building.story(str(el.get("story_id") or ""))
        mat = schemas.material(params.get("building_material_id"))
        rows.append({
            "Tầng": _story_name(story),
            "Vật liệu": str(mat.get("name") or ""),
            "Dày (mm)": round(float(params.get("thickness_mm", 0.0) or 0.0)),
            "Diện tích (m²)": round(_num(derived, el, "area_m2"), 2),
            "Thể tích (m³)": round(_num(derived, el, "volume_m3"), 3),
        })
    return rows


def _columns(building, derived):
    """Columns grouped by section, with marks assigned by section area."""
    return _marked(building, derived, "column", prefix="C",
                   section=_column_section)


def _beams(building, derived):
    return _marked(building, derived, "beam", prefix="DM",
                   section=lambda p: (_steel_name(p) or
                                      f"{round(float(p.get('width_mm', 0)))}"
                                      f"x{round(float(p.get('depth_mm', 0)))}"))


def _marked(building, derived, kind, prefix, section):
    """Shared shape of the column/beam tables: group by section, then mark."""
    groups: dict = {}
    for el in building.elements:
        if el.get("type") != kind:
            continue
        params = el.get("params") or {}
        story = building.story(str(el.get("story_id") or ""))
        key = (section(params), _story_name(story))
        row = groups.get(key)
        if row is None:
            groups[key] = {"row": {
                "Tầng": key[1],
                "Mã": "",
                "Tiết diện": key[0] if kind == "column"
                else key[0],
                "Số lượng": 1,
            }, "elements": [el]}
        else:
            row["row"]["Số lượng"] += 1
            row["elements"].append(el)
    # Marks are assigned per section across the whole building, ordered by
    # section area descending — C1 is the biggest column, as a schedule reads.
    def area_of(key):
        return _section_area(key[0], kind)

    sections = sorted({k[0] for k in groups}, key=area_of, reverse=True)
    marks = {sec: f"{prefix}{i + 1}" for i, sec in enumerate(sections)}
    rows = []
    for (sec, _story), info in groups.items():
        row = info["row"]
        row["Mã"] = marks[sec]
        if kind == "beam":
            # The beam schedule names the column "Tiết diện (b x h)".
            row.pop("Tiết diện", None)
            row["Tiết diện (b x h)"] = sec
        else:
            row["Tiết diện"] = sec
        # Every DECLARED column is written, blank when it does not apply:
        # the header list is the table's contract with the spreadsheet,
        # which maps by position, so a row missing a key would shift every
        # column after it.
        length_m = sum(
            _num(derived, e, "length_mm") for e in info["elements"]) / 1000.0
        row.setdefault("Dài (m)", round(length_m, 2))
        row.setdefault("KL (kg)", "")
        if kind == "column":
            row["Thể tích (m³)"] = round(
                sum(_num(derived, e, "volume_m3") for e in info["elements"]),
                3)
        # A steel member is billed by MASS: the section's own kg/m is what
        # the estimator orders from, and it is the one number a rolled
        # section carries that the geometry does not.
        steel = _steel_name(info["elements"][0].get("params") or {})
        if steel:
            from core.building import steel as _steel

            per_m = _steel.mass_per_m(steel)
            if per_m:
                row["KL (kg)"] = round(length_m * per_m, 2)
        rows.append(row)
    return sorted(rows, key=lambda r: (r["Tầng"], r["Mã"]))


def _steel_name(params) -> str:
    """The catalogue name of a steel member, or ``""``.

    A rolled section is ordered BY NAME — the flange and web thicknesses
    are the design, and ``200x100`` has thrown them away. When the element
    came off the steel table its own name is stated in the schedule, which
    is what the fabricator reads.
    """
    return str(params.get("steel_section") or "")


def _column_section(params) -> str:
    if params.get("shape") == "round":
        return f"D{round(float(params.get('diameter_mm', 0.0) or 0.0))}"
    steel = _steel_name(params)
    if steel:
        return steel
    w = round(float(params.get("width_mm", 0.0) or 0.0))
    d = round(float(params.get("depth_mm", 0.0) or 0.0))
    return f"{min(w, d)}x{max(w, d)}" if w != d else f"{w}x{d}"


def _section_area(section: str, kind: str) -> float:
    """A comparable area for a section code, used to order the marks."""
    try:
        if section.startswith("D"):
            r = float(section[1:]) / 2.0
            import math
            return math.pi * r * r
        a, b = section.lower().split("x")
        return float(a) * float(b)
    except (ValueError, IndexError):
        return 0.0


# ---- totals -----------------------------------------------------------------

def _totals(tables_out) -> dict:
    def total(which, column):
        return round(sum(float(r.get(column, 0.0))
                         for r in tables_out[which]), 3)

    openings = tables_out["openings"]
    return {
        # Gross area (billed) and the wall's real face (net), both totalled:
        # a bill that quotes gross and a builder who lays brick to net must
        # be able to reconcile the two from one report.
        "wall_area_m2": total("walls", "Diện tích (m²)"),
        "wall_net_area_m2": total("walls", "Thực tế (m²)"),
        "wall_volume_m3": total("walls", "Khối tích (m³)"),
        "slab_area_m2": total("slabs", "Diện tích (m²)"),
        "slab_volume_m3": total("slabs", "Thể tích (m³)"),
        "column_volume_m3": total("columns", "Thể tích (m³)"),
        "beam_length_m": total("beams", "Dài (m)"),
        "room_area_m2": total("zones", "Diện tích (m²)"),
        "door_count": sum(int(r["Số lượng"]) for r in openings
                          if r["Loại"] == OPENING_LABELS["door"]),
        "window_count": sum(int(r["Số lượng"]) for r in openings
                            if r["Loại"] == OPENING_LABELS["window"]),
    }


# ---- CSV --------------------------------------------------------------------

def to_csv(building, which: str) -> str:
    """One table as CSV, as Vietnamese Excel expects it.

    `;` separator, decimal comma, a UTF-8 BOM and CRLF: the four things that
    decide whether double-clicking the file shows a table or a single column
    of semicolon-joined text.
    """
    which = str(which)
    if which == "totals":
        rows = [["Chỉ tiêu", "Giá trị"]]
        rows += [[key, _comma(value)]
                 for key, value in tables(building)["totals"].items()]
        return _csv(rows)
    data = tables(building)
    if which not in data:
        raise KeyError(f"Không có bảng thống kê '{which}'.")
    headers = list(HEADERS.get(which) or ())
    rows = [headers]
    for row in data[which]:
        rows.append([row.get(col, "") for col in headers])
    return _csv(rows)


def all_csv(building) -> str:
    """Every table in one file, each under its own title row."""
    parts = []
    titles = {"zones": "THỐNG KÊ PHÒNG", "openings": "THỐNG KÊ CỬA",
              "walls": "THỐNG KÊ TƯỜNG", "slabs": "THỐNG KÊ SÀN",
              "columns": "THỐNG KÊ CỘT", "beams": "THỐNG KÊ DẦM"}
    data = tables(building)
    for which, title in titles.items():
        headers = list(HEADERS[which])
        block = [[title], headers]
        for row in data[which]:
            block.append([row.get(col, "") for col in headers])
        parts.append(_csv(block, bom=False))
    parts.append(to_csv(building, "totals").lstrip("\ufeff"))
    return "\ufeff" + "\r\n\r\n".join(parts)


def _csv(rows, bom: bool = True) -> str:
    lines = []
    for row in rows:
        lines.append(";".join(_cell(value) for value in row))
    text = "\r\n".join(lines) + "\r\n"
    return ("\ufeff" if bom else "") + text


def _cell(value) -> str:
    if isinstance(value, float):
        return _comma(value)
    text = str(value)
    if any(ch in text for ch in ';"\n\r'):
        return '"' + text.replace('"', '""') + '"'
    return text


def _comma(value) -> str:
    """A number the Vietnamese way: comma decimal, no trailing zeros."""
    if isinstance(value, int):
        return str(value)
    text = f"{float(value):.3f}".rstrip("0").rstrip(".")
    return text.replace(".", ",")


# ---- shared -----------------------------------------------------------------

def _derive(building):
    """``{element id: derived}``, computing what the scene has not synced yet."""
    out = {}
    for el in building.elements:
        derived = el.get("derived")
        if derived:
            out[str(el["id"])] = derived
            continue
        try:
            _mesh, computed = builders.build(building, el)
        except ValueError:
            computed = {}
        out[str(el["id"])] = computed or {}
    return out


def _num(derived, element, key: str) -> float:
    value = (derived.get(str(element["id"])) or {}).get(key)
    try:
        return float(value or 0.0)
    except (TypeError, ValueError):
        return 0.0


def _story_name(story) -> str:
    return str((story or {}).get("name") or "")
