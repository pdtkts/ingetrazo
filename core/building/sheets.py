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


#: The element types each non-per-storey group needs to exist at all. A
#: group whose trade is absent from the model is not issued: a blank sheet
#: is worse than no sheet, because it still gets printed and bound.
GROUP_NEEDS = {
    "column": ("column",),
    "beam": ("beam",),
    "stair": ("stair",),
    "wc": ("fixture",),
    "door": ("door", "window"),
    "detail": ("door", "window"),
}


def _has_trade(building, kinds) -> bool:
    return any(str(e.get("type")) in kinds for e in building.elements)


#: The groups a set may be asked to leave out — the caller's own switch.
OPTIONAL_GROUPS = {"elev": "elevations", "sect": "sections"}


def sheet_plan(building, story_ids=None, *, elevations: bool = True,
               sections: bool = True) -> list:
    """The drawing set a building is issued under, in order.

    ``story_ids`` limits the per-storey sheets (the three-storey townhouse
    issues three plans, three wall plans…); without it every storey gets one.
    A group whose trade the model does not have is not issued at all — see
    :data:`GROUP_NEEDS`. The result is deterministic — same model, same set
    — which is what makes a re-issue comparable with the last one.
    """
    stories = [s for s in building.stories
               if story_ids is None or str(s["id"]) in
               {str(i) for i in story_ids}]
    out: list = []
    counters: dict = {}
    requested = {"elevations": bool(elevations), "sections": bool(sections)}
    for group, label, per_storey in GROUPS:
        switch = OPTIONAL_GROUPS.get(group)
        if switch is not None and not requested[switch]:
            continue
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
            needs = GROUP_NEEDS.get(group)
            if needs and not _has_trade(building, needs):
                continue
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
                  paper: str = "A3", landscape: bool = True, *,
                  elevations: bool = True, sections: bool = True) -> list:
    """Create (or find) the sheets of the project's drawing set.

    Returns the ``Composicion`` objects in issue order. An existing sheet with
    the same name is reused, so running this twice updates the set instead of
    duplicating it — the behaviour a re-issue needs.
    """
    project = dict(project or building.project or {})
    specs = sheet_plan(building, story_ids, elevations=elevations,
                       sections=sections)
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


def sheet_index_text(sheets, project: dict | None = None) -> str:
    """The sheet list a drawing set is issued with (``index`` sheet).

    One line per sheet, in issue order, with its code and its title — the
    list the office checks a set against before it leaves the door.
    """
    project = dict(project or {})
    lines = [str(project.get("name") or "CÔNG TRÌNH"), ""]
    lines.append("BẢNG LIỆT KÊ BẢN VẼ")
    lines.append("")
    for sheet in sheets:
        name = str(getattr(sheet, "name", "") or "")
        code, _, title = name.partition(" ")
        lines.append(f"{code:<10}{title}")
    return "\n".join(lines)


def fill_sheet(sheet, view, scene, *, name: str = "", annotations: bool = True,
               building=None, area=None):
    """Fill a sheet with one drawing: its frame, and the sheet's own text.

    The composition is deliberate — the drawing in the middle, its title
    under it, and a scale bar where the title block does not claim the
    corner — so an office sheet comes out of one call rather than a session
    of dragging items around. Re-issuing the SAME sheet fills it again in
    place: an existing frame bound to this drawing's scene is reused, not
    duplicated.
    """
    from core.building import drawings as _drawings

    scene_name = str(name or view.name or _drawings.VIEW_LABELS.get(
        view.kind, view.kind))
    frame = next((f for f in sheet.frames
                  if str(getattr(f, "view_key", "")) == f"scene:{scene_name}"),
                 None)
    if frame is None:
        frame = _drawings.place_on_sheet(sheet, view, scene, name=scene_name)
    else:
        frame.scale_n = float(view.scale_denom)
    frame.annotations = bool(annotations)
    # A band at the top of the page carries the sheet's own title; the
    # frame's title line says the view (what a reader looks for first).
    page_w, _page_h = sheet.page_size_mm()
    margin = float(sheet.margin_mm)
    head = next((t for t in sheet.texts
                 if t.list_name == f"__title__{scene_name}"), None)
    if head is None:
        from core.composition import TextoItem
        head = TextoItem(x_mm=margin, y_mm=margin, w_mm=page_w - 2 * margin,
                         text="", size_pt=18.0, bold=True, align="left",
                         list_name=f"__title__{scene_name}")
        sheet.texts.append(head)
    head.text = scene_name
    head.y_mm = margin
    if area is not None:
        area.clear()
    if building is not None and bool(annotations):
        # The key is the drawing's name: re-issuing this sheet REPLACES what
        # the previous run wrote instead of stacking a second set on it.
        _drawings.annotate_plan(scene, building, view, key=scene_name)
    scene.version += 1
    return frame


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
