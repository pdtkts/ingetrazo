# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Marco Sumari Tellez and IngeTrazo contributors.
"""Thép hình — the rolled-section tables a Vietnamese office specifies from.

`220x220` is a concrete column and it is enough for one; a steel column or
beam is never specified that way. The trade names a rolled section by its
catalogue — `H200x100x5.5x8` (TCVN 7571 / JIS G3192) or `I200` — and that
name IS the design: a fabricator orders from it, the schedule states it,
and a drawing that writes `200x100` instead has thrown away the flange
and web thicknesses that make the section what it is.

So this is a REFERENCE, not a generator: `w × h` alone cannot produce a
valid H-section (two webs of different thickness in the same height is
perfectly ordinary), and a table that guessed one would put a section on a
drawing that nobody can order. What the table does is let the user pick a
catalogue name and have the model adopt its real dimensions, the takeoff
print the NAME a fabricator recognises, and the schedule state the mass
per metre the bill is written from.

Values are the standard nominal dimensions and masses of the JIS G3192 /
TCVN 7571 H and I series, in millimetres and kilograms per metre.
"""
from __future__ import annotations

__all__ = ["SECTIONS", "families", "by_name", "adopt", "mass_per_m"]

#: ``name -> (h_mm, b_mm, tw_mm, tf_mm, mass_kg_per_m)``.
#:
#: ``h`` is the overall depth, ``b`` the flange width, ``tw`` the web
#: thickness, ``tf`` the flange thickness. The order matches how the trade
#: writes the name (``H h×b×tw×tf``), which is what makes a schedule line
#: readable to the person ordering the steel.
SECTIONS: dict = {
    # ---- H sections (JIS G3192 / TCVN 7571), the everyday ones --------
    "H100x100x6x8": (100.0, 100.0, 6.0, 8.0, 17.2),
    "H125x125x6.5x9": (125.0, 125.0, 6.5, 9.0, 23.8),
    "H150x150x7x10": (150.0, 150.0, 7.0, 10.0, 31.5),
    "H175x175x7.5x11": (175.0, 175.0, 7.5, 11.0, 40.2),
    "H200x200x8x12": (200.0, 200.0, 8.0, 12.0, 49.9),
    "H250x250x9x14": (250.0, 250.0, 9.0, 14.0, 72.4),
    "H300x300x10x15": (300.0, 300.0, 10.0, 15.0, 94.0),
    "H350x350x12x19": (350.0, 350.0, 12.0, 19.0, 137.0),
    "H400x400x13x21": (400.0, 400.0, 13.0, 21.0, 172.0),
    # ---- H sections used as beams (wide flange, unequal) -------------
    "H200x100x5.5x8": (200.0, 100.0, 5.5, 8.0, 21.3),
    "H250x125x6x9": (250.0, 125.0, 6.0, 9.0, 29.6),
    "H300x150x6.5x9": (300.0, 150.0, 6.5, 9.0, 37.3),
    "H350x175x7x11": (350.0, 175.0, 7.0, 11.0, 50.0),
    "H400x200x8x13": (400.0, 200.0, 8.0, 13.0, 66.0),
    "H450x200x9x14": (450.0, 200.0, 9.0, 14.0, 76.0),
    "H500x200x10x16": (500.0, 200.0, 10.0, 16.0, 89.7),
    "H600x200x11x17": (600.0, 200.0, 11.0, 17.0, 106.0),
    # ---- I sections (JIS G3192 / TCVN 7570): the classic beam ---------
    "I100x50x5x7": (100.0, 50.0, 5.0, 7.0, 9.3),
    "I150x75x5x7": (150.0, 75.0, 5.0, 7.0, 14.0),
    "I200x100x5.5x8": (200.0, 100.0, 5.5, 8.0, 21.3),
    "I250x125x6x9": (250.0, 125.0, 6.0, 9.0, 29.6),
    "I300x150x6.5x9": (300.0, 150.0, 6.5, 9.0, 37.3),
    "I400x150x8x13": (400.0, 150.0, 8.0, 13.0, 57.0),
    # ---- Square and rectangular hollow sections ----------------------
    "SH100x100x6": (100.0, 100.0, 6.0, 6.0, 17.2),
    "SH150x150x6": (150.0, 150.0, 6.0, 6.0, 26.6),
    "SH200x200x8": (200.0, 200.0, 8.0, 8.0, 47.4),
    "RH200x100x6": (200.0, 100.0, 6.0, 6.0, 26.6),
    "RH250x150x8": (250.0, 150.0, 8.0, 8.0, 46.0),
    # ---- Round steel pipe (the common structural sizes) --------------
    "P114x4": (114.0, 114.0, 4.0, 4.0, 10.8),
    "P168x5": (168.0, 168.0, 5.0, 5.0, 20.1),
}


def families() -> dict:
    """``{family_letter: [name, …]}`` in table order.

    The trade picks by family first — «cho tôi cái H» — so the list a
    dialog shows is grouped that way rather than alphabetically, where
    «H100x100x6x8» and «I100x50x5x7» would sit together and read as one
    list of unrelated sizes.
    """
    out: dict = {}
    for name in SECTIONS:
        letter = name[0]
        out.setdefault(letter, []).append(name)
    return out


def by_name(name: str):
    """``(h, b, tw, tf, mass)`` for a catalogue name, or ``None``."""
    record = SECTIONS.get(str(name or ""))
    return tuple(record) if record else None


def mass_per_m(name: str) -> float:
    """The section's own kg/m, or ``0.0`` for a name off the table.

    A zero is the honest answer for an unknown name: a bill written from a
    guessed mass is worse than one with a blank the estimator fills in.
    """
    record = SECTIONS.get(str(name or ""))
    return float(record[4]) if record else 0.0


def adopt(params: dict, name: str) -> dict:
    """The parameter changes that make a column or beam BE this section.

    Returns only what changes, so the caller can merge it with whatever
    else the user is editing. The section's own name is recorded in
    ``steel_section`` and the schedule prints THAT — a fabricator orders
    from the catalogue name, and «200x100» is not one.
    """
    record = SECTIONS.get(str(name or ""))
    if record is None:
        return {}
    h, b, tw, tf, _mass = record
    shape = "round" if str(name).startswith("P") else "rect"
    out = {
        "steel_section": str(name),
        "shape": shape,
        "building_material_id": "thep",
    }
    if shape == "round":
        out["diameter_mm"] = float(h)
    else:
        # The SECTION is the h × b rectangle on a plane drawing; the web
        # and flange thicknesses are recorded so the schedule and the IFC
        # can state them, and so a re-open does not silently lose them.
        out["width_mm"] = float(min(h, b)) if h != b else float(b)
        out["depth_mm"] = float(max(h, b)) if h != b else float(h)
        out["steel_web_mm"] = float(tw)
        out["steel_flange_mm"] = float(tf)
    return out
