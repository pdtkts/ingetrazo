# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Marco Sumari Tellez and IngeTrazo contributors.
"""Sheets: the drawing set, its Vietnamese title block, and the PDF export.

A sheet is the object the office actually issues, so this module treats three
things as one job:

* **The plan of sheets** — the drawing set of a building follows a fixed order
  (cover and sheet list, column and beam layouts, then per storey the main
  plan, the wall plan, the floor and ceiling plans, then elevations, sections
  and the details). :func:`sheet_plan` produces that order from the model, so
  "lập hồ sơ" is one call and the same building always yields the same set.
* **The Vietnamese title block** — the classic bordered grid: project, sheet
  title, scale, sheet number, designer, date, revision. It is a
  :class:`~core.composition.Cajetin` with its own rows, not a second title
  block system, so the composer's editor, the Items list, locking and the PDF
  path all keep working on it.
* **The PDF** — the composer already writes sheets to PDF through Qt
  (``ComposerWindow.export_pdf``); :func:`export_sheets_pdf` batch-exports a
  whole set, one sheet per page, which is what the office sends out.

Sheet numbering follows the trade's convention: a group letter and a running
number (``KT00-01`` …), exactly what a Vietnamese drawing set is issued under.
"""
from __future__ import annotations

from dataclasses import dataclass

from core.composition import PAPER_SIZES_MM, Cajetin, Composicion
from core.i18n import tr

#: The sheet code a drawing set is numbered under: ``<prefix><group>-<n>``.
SHEET_PREFIX = "KT"

#: The drawing groups, in issue order, with the label each sheet carries.
#: ``(key, label, per_storey)`` — per_storey groups produce one sheet each.
GROUPS = (
    ("cover", "Trang bìa", False),
    ("index", "Bảng liệt kê bản vẽ", False),
    ("column", "Định vị cột", False),
    ("beam", "Định vị dầm", False),
    ("plan", "Mặt bằng", True),
    ("wall", "Mặt bằng tường", True),
    ("floor", "Mặt bằng lát sàn", True),
    ("ceiling", "Mặt bằng trần", True),
    ("elev", "Mặt đứng", False),
    ("sect", "Mặt cắt", False),
    ("stair", "Cầu thang", False),
    ("wc", "Vệ sinh", False),
    ("door", "Định vị cửa", False),
    ("detail", "Chi tiết", False),
)

#: The rows of the Vietnamese title block, top to bottom, with their labels.
#: The first row of each pair is the label as it is drawn.
TITLE_ROWS = (
    ("CÔNG TRÌNH", "project"),
    ("HẠNG MỤC", "item"),
    ("LOẠI BẢN VẼ", "drawing"),
    ("TỶ LỆ", "scale"),
    ("SỐ BẢN VẼ", "number"),
    ("NGÀY", "date"),
    ("THIẾT KẾ", "designer"),
    ("CHỦ TRÌ", "chief"),
)


@dataclass
class SheetSpec:
    """One sheet the plan asks for, before it exists in the document."""

    key: str
    group: str
    label: str
    title: str
    scale_denom: int = 50
    story_id: str | None = None
    paper: str = "A3"
    landscape: bool = True


def sheet_plan(building, story_ids=None) -> list:
    """The drawing set a building is issued under, in order.

    ``story_ids`` limits the per-storey sheets (the three-storey townhouse
    issues three plans, three wall plans…); without it every storey gets one.
    The result is deterministic — same model, same set — which is what makes
    a re-issue comparable with the last one.
    """
    stories = [s for s in building.stories
               if story_ids is None or str(s["id"]) in
               {str(i) for i in story_ids}]
    out: list = []
    counters: dict = {}
    for group, label, per_storey in GROUPS:
        if per_storey:
            if group == "plan" and not stories:
                continue
            for story in stories:
                counters[group] = counters.get(group, 0) + 1
                out.append(SheetSpec(
                    key=f"{group}:{story['id']}",
                    group=group,
                    label=f"{label} {story.get('name') or ''}".strip(),
                    title=f"{label} — {story.get('name') or ''}".strip(),
                    story_id=str(story["id"]),
                ))
        else:
            # A group with nothing to draw is not issued: an empty elevation
            # sheet is worse than none.
            counters[group] = counters.get(group, 0) + 1
            out.append(SheetSpec(key=group, group=group, label=label,
                                 title=label))
    return out


def sheet_code(spec: SheetSpec, index: int) -> str:
    """``KT03-02`` — the group's number and its running number in the set."""
    group_no = _group_number(spec.group)
    return f"{SHEET_PREFIX}{group_no:02d}-{index:02d}"


def _group_number(group: str) -> int:
    for i, (key, _label, _ps) in enumerate(GROUPS):
        if key == group:
            return i
    return len(GROUPS)


def title_block(sheet: Composicion, project: dict, spec: SheetSpec,
                code: str, *, revision: str = "") -> Cajetin:
    """Fill the Vietnamese title block of ``sheet`` from the project data.

    Creates the block when the sheet has none (docked to the bottom-right
    margin corner, where a drawing office expects it) and rewrites its rows
    when it has one, so re-issuing a sheet never leaves yesterday's revision
    on it.
    """
    block = sheet.cajetin
    if block is None:
        block = sheet.default_cajetin()
        sheet.cajetin = block
    values = {
        "project": str(project.get("name") or ""),
        "item": str(project.get("item") or ""),
        "drawing": spec.title,
        "scale": f"1:{int(spec.scale_denom)}",
        "number": code,
        "date": str(project.get("date") or ""),
        "designer": str(project.get("designer") or ""),
        "chief": str(project.get("chief") or ""),
    }
    rows = [[label, values.get(key, "")]
            for label, key in TITLE_ROWS]
    if revision:
        rows.append([tr("REVISION"), str(revision)])
    block.campos = rows
    # The legacy named attributes stay in step with the rows: the PDF path
    # and older documents read them.
    block.proyecto = values["project"]
    block.autor = values["designer"]
    block.fecha = values["date"]
    block.escala = values["scale"]
    block.lamina = code
    block.w_mm = max(float(block.w_mm or 0.0), 180.0)
    block.h_mm = max(float(block.h_mm or 0.0), 33.0)
    return block


def ensure_sheets(scene, building, project=None, story_ids=None,
                  paper: str = "A3", landscape: bool = True) -> list:
    """Create (or find) the sheets of the project's drawing set.

    Returns the ``Composicion`` objects in issue order. An existing sheet with
    the same name is reused, so running this twice updates the set instead of
    duplicating it — the behaviour a re-issue needs.
    """
    project = dict(project or building.project or {})
    specs = sheet_plan(building, story_ids)
    by_name = {str(c.name): c for c in scene.compositions}
    made: list = []
    for index, spec in enumerate(specs, start=1):
        code = sheet_code(spec, index)
        name = f"{code} {spec.title}"
        sheet = by_name.get(name)
        if sheet is None:
            sheet = Composicion(name=name, paper=paper,
                                landscape=bool(landscape))
            scene.compositions.append(sheet)
            by_name[name] = sheet
        sheet.paper = paper
        sheet.landscape = bool(landscape)
        title_block(sheet, project, spec, code,
                    revision=str(project.get("revision") or ""))
        made.append(sheet)
    scene.version += 1
    return made


def export_sheets_pdf(window, path: str, sheets=None) -> list:
    """Write the sheets to one PDF, a page per sheet — the issued set.

    Uses the composer's own exporter so the scale, the pens, the Vietnamese
    fonts and the cut fills are exactly what the on-screen sheet shows; there
    is deliberately no second PDF pipeline.
    """
    composer = window._ensure_composer()
    return composer.export_all_pdf(path, sheets)


def paper_size(paper: str, landscape: bool) -> tuple:
    """``(width, height)`` in mm for a paper code, honouring the orientation."""
    w, h = PAPER_SIZES_MM.get(str(paper).upper(), PAPER_SIZES_MM["A3"])
    return (h, w) if landscape else (w, h)
