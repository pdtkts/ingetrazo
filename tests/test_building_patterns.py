# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Marco Sumari Tellez and IngeTrazo contributors.
"""The Vietnamese material patterns — what a section reads as on paper."""
from __future__ import annotations

from core.building import patterns as P


#: A 200 × 200 mm cut with a 60 × 60 mm hole in the middle — a wall with
#: something passing through it, the case a hatch must respect.
_OUTER = [(0.0, 0.0), (200.0, 0.0), (200.0, 200.0), (0.0, 200.0)]
_HOLE = [(70.0, 70.0), (130.0, 70.0), (130.0, 130.0), (70.0, 130.0)]


def test_every_material_the_tables_name_has_a_pattern():
    """A material the model offers and the library does not know would be
    hatched with something else — a wrong material on the sheet."""
    from core.building.elements import MATERIALS

    known = {str(m.get("cut_fill") or "") for m in MATERIALS.values()}
    for fill in known - {""}:
        assert fill in P.PATTERNS, f"thiếu pattern cho vật liệu: {fill}"


def test_an_unknown_material_falls_back_and_never_vanishes():
    families = P.families_for("vật liệu lạ")
    assert families, "vật liệu không biết vẫn phải có nét"
    assert families == P.PATTERNS[P.FALLBACK]


def test_the_lines_stop_at_a_hole():
    """A hatch running through a void is a lie about the section.

    Every family of every pattern is checked: the middle of the hole may
    not be crossed by a line, on any material.
    """
    for name in P.names():
        for x0, y0, x1, y1 in P.pattern_for_rings([_OUTER, _HOLE], name):
            mx, my = (x0 + x1) / 2.0, (y0 + y1) / 2.0
            inside = 70.0 < mx < 130.0 and 70.0 < my < 130.0
            assert not inside, f"{name}: nét chạy xuyên lỗ tại {(mx, my)}"


def test_concrete_reads_denser_than_masonry():
    """The point of a pattern library: the material is legible at a glance."""
    concrete = P.pattern_for_rings([_OUTER], "Bê tông cốt thép")
    masonry = P.pattern_for_rings([_OUTER], "Tường gạch (cắt)")
    assert len(concrete) > len(masonry) * 2


def test_a_pattern_stays_within_a_drawable_budget():
    """A hatch is a drawing convention, not a rendering: thousands of
    segments on one cut is a table mistake, and it freezes the sheet."""
    for name in P.names():
        segs = P.pattern_for_rings([_OUTER], name)
        assert 10 <= len(segs) <= 1500, f"{name}: {len(segs)} nét"

    # …and the budget is TOTAL, not per family: a 40 m cut at a coarse
    # scale must not multiply three families' worth of segments.
    huge = [(0.0, 0.0), (40000.0, 0.0), (40000.0, 40000.0), (0.0, 40000.0)]
    for name in P.names():
        segs = P.pattern_for_rings([huge], name)
        assert len(segs) <= P.MAX_SEGMENTS, f"{name}: {len(segs)} nét"


def test_odd_rings_give_nothing_rather_than_a_crash():
    """A hatch is derived decoration: a ring with two points is a mistake
    upstream, and the hatch must simply not appear."""
    assert P.pattern_for_rings([], "Gỗ") == []
    assert P.pattern_for_rings([[(0.0, 0.0), (1.0, 0.0)]], "Gỗ") == []


def test_the_spacing_is_on_paper_so_two_scales_agree():
    """A 1:50 and a 1:100 of one wall must look the same on the sheet.

    The spacing is stated in paper millimetres, so the line count follows
    the paper extent — and, crucially, halving the spacing doubles the
    count of lines across any extent. That is the property a model-space
    spacing would destroy: it would tie the hatch to the wall's real size
    and the two scales would hatch differently.
    """
    fine = P.pattern_segments([_OUTER], 45.0, 2.4)
    coarse = P.pattern_segments([_OUTER], 45.0, 4.8)
    assert len(fine) > len(coarse) * 1.6
    # Twice the paper extent holds twice the lines, not four times.
    big = P.pattern_segments([[(0, 0), (400, 0), (400, 400), (0, 400)]],
                             45.0, 2.4)
    assert 1.6 < len(big) / len(fine) < 2.4


def test_dashes_are_a_period_not_a_length():
    """``dash_mm`` is the period; a 20 mm period on a 200 mm line gives
    a handful of dashes, not one dash every 20 mm of a runaway loop."""
    segs = P.pattern_segments([_OUTER], 0.0, 20.0, 0.0, 20.0)
    assert segs
    lengths = [((x1 - x0) ** 2 + (y1 - y0) ** 2) ** 0.5
               for x0, y0, x1, y1 in segs]
    assert max(lengths) <= 20.0


def test_the_element_kind_decides_the_hatch_through_its_material():
    """A wall hatches as masonry and a column as concrete, from the same
    tables the model itself uses — no second mapping to drift."""
    wall = P.pattern_for_kind("wall")
    column = P.pattern_for_kind("column")
    assert wall == P.families_for("Tường gạch (cắt)")
    assert column == P.families_for("Bê tông cốt thép")
    assert wall != column
