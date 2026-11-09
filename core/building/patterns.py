# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Marco Sumari Tellez and IngeTrazo contributors.
"""The Vietnamese material patterns — what a cut looks like on paper.

A Vietnamese drawing reads a section by its hatch: concrete is a dense
45° with dots, masonry a single 45°, earth back-slanted, insulation wavy.
The office recognises the material before it reads the label, and an
office in another country expects the same codes (ISO 128-50 / TCVN
8-20), so the patterns are the trade's, not this program's invention.

:data:`PATTERNS` is the library: ``name -> [(angle_deg, spacing_mm,
offset_mm, dash_mm)]``. A line family is a set of parallel lines at
``angle_deg``, ``spacing_mm`` apart on paper, with an in-family
``offset_mm`` (what makes two interleaved families a "brick" look) and an
optional dash length. ``name`` is the same string the building material
tables carry in ``cut_fill``, so the material a wall is made of decides
its hatch without a second mapping — :func:`families_for` is that lookup
and is the only entry point the renderers need.

Spacing is stated in PAPER millimetres: a hatch is a drawing convention,
and a 1:50 and a 1:100 of one wall must look the same on the sheet, which
is the opposite of the model-space spacing a raw section fill uses.
"""
from __future__ import annotations

#: One line family: ``(angle_deg, spacing_mm, offset_mm, dash_mm)``.
#: ``dash_mm`` of 0 means a continuous line; a positive value is the PERIOD
#: of a dashed line (a dash of 60% of it, then a gap), in paper millimetres.
#: Keep the period at least 2 mm: a hatch finer than that is a grey wash
#: nobody draws by hand and tens of thousands of segments on one sheet. Angles are measured from the
#: drawing's own x axis, counter-clockwise, like a protractor on paper.
PATTERNS: dict = {
    "Bê tông cốt thép": [
        (45.0, 1.6, 0.0, 0.0),
        (45.0, 1.6, 0.8, 0.0),          # the tighter pair of the concrete code
        (135.0, 3.2, 0.0, 0.0),         # the open cross that says "reinforced"
    ],
    "Bê tông (lót)": [
        (45.0, 1.6, 0.0, 0.0),
        (45.0, 1.6, 0.8, 0.0),
    ],
    "Tường gạch (cắt)": [
        (45.0, 2.4, 0.0, 0.0),
    ],
    "Gạch block": [
        (45.0, 3.2, 0.0, 0.0),
        (135.0, 3.2, 0.0, 0.0),
    ],
    "Đá granite": [
        (0.0, 1.2, 0.0, 0.0),
        (90.0, 1.2, 0.0, 0.0),
        (45.0, 6.0, 0.0, 0.0),
    ],
    "Đất tự nhiên": [
        (45.0, 2.0, 0.0, 0.0),
        (135.0, 4.0, 0.0, 0.0),
    ],
    "Cát đệm": [
        (0.0, 1.2, 0.0, 0.0),
        (90.0, 3.0, 0.0, 0.0),
    ],
    "Gỗ": [
        (0.0, 2.4, 0.0, 0.0),
        (0.0, 12.0, 0.0, 0.0),          # the grain lines of the wood code
    ],
    "Kim loại (đặc)": [
        (45.0, 1.2, 0.0, 0.0),
    ],
    "Thép": [
        (45.0, 1.2, 0.0, 0.0),
        (315.0, 1.2, 0.0, 0.0),
    ],
    "Kính": [
        (45.0, 8.0, 0.0, 20.0),         # long dashes: glass is drawn broken
    ],
    "Cách nhiệt": [
        (0.0, 5.0, 0.0, 0.0),
        (0.0, 5.0, 2.5, 0.0),           # the double band of the insulation code
    ],
    "Tô đặc xám": [
        (45.0, 1.0, 0.0, 0.0),
        (135.0, 1.0, 0.0, 0.0),
    ],
    "Chống thấm": [
        (0.0, 1.0, 0.0, 0.0),
        (90.0, 4.0, 0.0, 0.0),
    ],
    "Vật liệu khác": [
        (45.0, 6.0, 0.0, 0.0),
    ],
}

#: The pattern a cut falls back to when its material names none: the
#: neutral "other material" hatch, never a wrong specific one.
FALLBACK = "Vật liệu khác"


def names() -> list:
    """Every pattern name, in the order the library declares them."""
    return list(PATTERNS)


def families_for(material_name: str) -> list:
    """The line families of ``material_name`` — the lookup renderers use.

    A material whose name the library does not know gets the neutral
    hatch rather than nothing: an unhatched cut reads as a hole in the
    wall, which is worse than a generic fill.
    """
    return list(PATTERNS.get(str(material_name or ""))
                or PATTERNS[FALLBACK])


def pattern_segments(rings, angle_deg: float, spacing_mm: float,
                     offset_mm: float = 0.0, dash_mm: float = 0.0):
    """Clip one family of parallel lines to ``rings`` (paper millimetres).

    ``rings`` is a list of closed rings — the outline of each cut area in
    drawing millimetres, first ring outer, the rest its holes — and the
    result is a list of ``(x0, y0, x1, y1)`` segments in the same units.
    Lines are spaced ``spacing_mm`` apart across the family, the whole
    family shifted ``offset_mm`` (what makes two families interleave), and
    dashed at ``dash_mm`` when it is positive.

    Even-odd crossing is the same rule the section fill uses: a line that
    enters the outer ring and leaves through a hole stops at the hole, so
    hatch never runs through a door opening or a room.
    """
    import math

    t = math.radians(float(angle_deg))
    d = (math.cos(t), math.sin(t))          # along the line
    m = (-d[1], d[0])                       # across the family
    spacing = float(spacing_mm)
    if spacing <= 0:
        return []
    #: A ceiling on one family's work: a pattern that explodes past this is
    #: a mistake in the table, not a drawing.
    limit = 4000
    crossings: list = []
    for ring in rings or ():
        n = len(ring)
        if n < 3:
            continue
        for i in range(n):
            x0, y0 = float(ring[i][0]), float(ring[i][1])
            x1, y1 = float(ring[(i + 1) % n][0]), float(ring[(i + 1) % n][1])
            sa = x0 * m[0] + y0 * m[1]
            sb = x1 * m[0] + y1 * m[1]
            crossings.append((sa, sb, x0, y0, x1, y1))
    if not crossings:
        return []
    s_values = [c[0] for c in crossings] + [c[1] for c in crossings]
    shift = float(offset_mm)
    k0 = int(math.ceil((min(s_values) - shift) / spacing))
    k1 = int(math.floor((max(s_values) - shift) / spacing))
    out: list = []
    for k in range(k0, k1 + 1):
        s = k * spacing + shift
        hits: list = []
        for sa, sb, x0, y0, x1, y1 in crossings:
            if (sa > s) == (sb > s):
                continue
            f = (s - sa) / (sb - sa)
            px, py = x0 + (x1 - x0) * f, y0 + (y1 - y0) * f
            hits.append(px * d[0] + py * d[1])
        hits.sort()
        for i in range(0, len(hits) - 1, 2):
            if len(out) >= limit:
                return out
            u0, u1 = hits[i], hits[i + 1]
            if u1 - u0 <= 1e-9:
                continue
            if dash_mm and dash_mm > 0:
                u = math.floor(u0 / dash_mm) * dash_mm
                while u < u1:
                    # The budget is checked INSIDE the dash loop: one long
                    # chord across a big ring asks for thousands of dashes,
                    # and the outer check only saw the family, not them.
                    if len(out) >= limit:
                        return out
                    a = max(u, u0)
                    b = min(u + dash_mm * 0.6, u1)
                    if b > a:
                        out.append(_point(a, s, d, m) + _point(b, s, d, m))
                    u += dash_mm
            else:
                out.append(_point(u0, s, d, m) + _point(u1, s, d, m))
    return out


def _point(u: float, s: float, d, m) -> tuple:
    return (d[0] * u + m[0] * s, d[1] * u + m[1] * s)


def pattern_for_kind(kind: str) -> list:
    """The families a BIM element kind cuts with, at its default material.

    The drawing renderer knows an element by its type; the hatch is a
    property of what it is MADE of. This is the one bridge between the
    two, so a wall cut hatches as masonry and a column as concrete
    without the renderer carrying a table of its own.
    """
    from core.building import elements as schemas

    params = schemas.defaults_for(kind)
    material = schemas.material(params.get("building_material_id"))
    return families_for(str(material.get("cut_fill") or ""))


#: A ceiling on one hatch's total work, across all its families. A pattern
#: that goes past this is a mistake in the table or a cut nobody would draw
#: at this scale; either way, stopping is right, and 12000 segments on one
#: wall is a sheet that takes a minute to open.
MAX_SEGMENTS = 4000


def pattern_for_rings(rings, material_name: str) -> list:
    """The whole hatch of ``material_name`` over ``rings``, families merged.

    The budget is TOTAL, not per family: three families of 4000 would
    otherwise be 12000 segments for one cut.
    """
    out: list = []
    for angle, spacing, offset, dash in families_for(material_name):
        out.extend(pattern_segments(rings, angle, spacing, offset, dash))
        if len(out) >= MAX_SEGMENTS:
            break
    return out[:MAX_SEGMENTS]
