# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Marco Sumari Tellez and IngeTrazo contributors.
"""The drawing set: every sheet a project issues, generated from the model.

"Lập hồ sơ" is one operation, not an afternoon. :func:`generate_docset`
walks the model once and produces the whole set in the order the trade
issues it:

* a **cover** and the **sheet list**, both filled from the project's own
  fields, so a cover never lags the building it describes;
* the **layouts** (column, beam) drawn from what the model actually
  contains — a project with no beams gets no beam layout, because an empty
  sheet is worse than no sheet;
* per storey the **plan** (cut at +1200, trimmed at its floor, dimensioned
  outside the house, its rooms stamped), the **wall plan**, the **floor
  plan** and the **ceiling plan**;
* the **elevations** (one per side that has walls) and the **sections**
  (through the building's own middle — where a section is taken by default
  in every drawing office);
* a **detail** — the stair, when there is one.

Everything is idempotent: running it again re-fills the same sheets, so a
revised model re-issues the set instead of doubling it, and the sheet list
matches what is on the sheets because both are produced by this one call.

The set is *checked* as well as produced: :func:`check_docset` states what
each sheet will be missing (a plan with no room stamps, an elevation with
nothing to show) BEFORE anything is written, which is what makes a long
generation worth the wait.
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field

from core.building import drawings as _drawings
from core.building import sheets as _sheets


@dataclass
class DocStep:
    """One step of the generation, as the progress dialog reports it."""

    key: str
    label: str
    sheets: int = 0
    note: str = ""


@dataclass
class DocSetResult:
    """What a run produced, in issue order."""

    sheets: list = field(default_factory=list)
    steps: list = field(default_factory=list)
    notes: list = field(default_factory=list)

    def summary(self) -> str:
        return "; ".join(f"{s.key}={s.sheets}" for s in self.steps if s.sheets)


def _story_ids_for(building, story_ids):
    if story_ids is None:
        return [str(s["id"]) for s in building.stories]
    wanted = {str(s) for s in story_ids}
    return [str(s["id"]) for s in building.stories if str(s["id"]) in wanted]


def _elements_of(building, story_id, kind):
    return [e for e in building.elements
            if str(e.get("story_id")) == str(story_id)
            and e.get("type") == kind]


def _story_span(building) -> tuple:
    """``(z_base, z_top)`` of the whole building, in mm."""
    stories = list(building.stories)
    if not stories:
        return (0.0, 3300.0)
    z0 = min(float(s.get("z_mm", 0.0)) for s in stories)
    top = max(float(s.get("z_mm", 0.0)) + float(s.get("height_mm", 3300.0))
              for s in stories)
    return (z0, top)


def check_docset(building, story_ids=None) -> list:
    """What the set will be missing, in words — read before generating.

    Returns a list of ``(issue, severity)`` with severity ``"warn"`` or
    ``"info"``. A warning does not stop the run: it tells the user what to
    fix so the re-issued set is right.
    """
    out: list = []
    ids = _story_ids_for(building, story_ids)
    if not ids:
        out.append(("Chưa có tầng nào — không có bản vẽ nào để sinh.", "warn"))
        return out
    if not building.elements:
        out.append(("Chưa có cấu kiện nào trên mô hình.", "warn"))
    for sid in ids:
        story = building.story(sid)
        if story is None:
            continue
        name = str(story.get("name") or sid)
        if not _elements_of(building, sid, "wall"):
            out.append((f"{name}: không có tường — mặt bằng sẽ trống.",
                        "warn"))
        if not _elements_of(building, sid, "zone"):
            out.append((f"{name}: chưa có phòng (zone) — bản vẽ thiếu tên "
                        f"và diện tích phòng.", "info"))
    if not any(e.get("type") in ("door", "window")
               for e in building.elements):
        out.append(("Chưa có cửa nào — bản vẽ sẽ không có ký hiệu cửa.",
                    "info"))
    if not any(e.get("type") == "beam" for e in building.elements):
        out.append(("Chưa có dầm — bỏ qua bản vẽ định vị dầm.", "info"))
    if not any(e.get("type") == "stair" for e in building.elements):
        out.append(("Chưa có cầu thang — bỏ qua bản vẽ cầu thang.", "info"))
    return out


def generate_docset(scene, building, project=None, story_ids=None,
                    paper: str = "A3", landscape: bool = True,
                    sections: bool = True, elevations: bool = True,
                    annotations: bool = True, progress=None) -> DocSetResult:
    """Generate (or re-generate) the whole drawing set.

    ``progress`` is called as ``progress(index, total, label)`` so a dialog
    can show where the run is; it is optional and never required for the
    generation itself. Returns a :class:`DocSetResult` whose ``sheets`` are
    the ``Composicion`` objects in issue order.
    """
    project = dict(project or building.project or {})
    ids = _story_ids_for(building, story_ids)
    result = DocSetResult()
    if not ids:
        # An empty model has no storey, so no view to hang a drawing on.
        result.notes.append("Chưa có tầng nào — không sinh bản vẽ.")
        return result

    made = _sheets.ensure_sheets(scene, building, project, ids, paper=paper,
                                 landscape=landscape, elevations=elevations,
                                 sections=sections)
    by_name = {str(s.name): s for s in made}
    total = max(len(made), 1)
    done = 0

    def tick(label: str, sheets: int = 0, note: str = "") -> None:
        nonlocal done
        done += 1
        result.steps.append(DocStep(key=label, label=label, sheets=sheets,
                                    note=note))
        if progress is not None:
            progress(min(done, total), total, label)

    # ---- cover and sheet list ------------------------------------------
    cover = by_name.get(f"KT00-01 Trang bìa") or (made[0] if made else None)
    if cover is not None:
        _fill_cover(cover, project, building)
        tick("Trang bìa", 1)
    index_sheet = next((s for s in made
                        if "Bảng liệt kê" in str(s.name)), None)
    if index_sheet is not None:
        _fill_index(index_sheet, made, project)
        tick("Bảng liệt kê bản vẽ", 1)

    # ---- layouts --------------------------------------------------------
    for key, kind, label in (("column", "column", "Định vị cột"),
                             ("beam", "beam", "Định vị dầm")):
        if not any(e.get("type") == kind for e in building.elements):
            continue
        sheet = next((s for s in made if _sheets_code_group(s) == key), None)
        if sheet is None:
            continue
        view = _layout_view(building, ids, label, kind)
        _sheets.fill_sheet(sheet, view, scene, name=label)
        tick(label, 1)

    # ---- per storey -----------------------------------------------------
    for sid in ids:
        story = building.story(sid)
        if story is None:
            continue
        story_name = str(story.get("name") or sid)
        # Each of the storey's sheets is the SAME cut showing one thing:
        # ``show`` is the trade's own layer, kept on while the others are
        # hidden. A wall plan with the furniture drawn on it is a drawing
        # nobody can read, and a floor plan that also shows the beams is
        # not a floor plan.
        for key, label_extra, show, cut in (
                ("plan", "Mặt bằng", None, None),
                ("wall", "Mặt bằng tường", "wall", None),
                ("floor", "Mặt bằng lát sàn", "slab", None),
                ("ceiling", "Mặt bằng trần", "ceiling", 0.0)):
            sheet = next((s for s in made
                          if _sheets_code_group(s) == key
                          and story_name in str(s.name)), None)
            if sheet is None:
                continue
            row = {"kind": "story", "story_id": sid,
                   "name": f"{label_extra} {story_name}"}
            if cut is not None:
                row["cut_mm"] = cut
            view = _drawings.view_for(building, row)
            if show is not None:
                view.hidden_layers = _layers_except(show)
            # Only the main plan carries the drawing's language: the wall,
            # floor and ceiling plans are the same cut showing other
            # things, and annotating all four would print four room stamps
            # on one room.
            pass_building = building if key == "plan" else None
            _sheets.fill_sheet(
                sheet, view, scene,
                name=f"{label_extra} {story_name}",
                building=pass_building,
                annotations=annotations and key == "plan")
            tick(f"{label_extra} {story_name}", 1)

    # ---- elevations -----------------------------------------------------
    # The set issues ONE elevation: the sheet the plan above the house is
    # read with. Its label is the sheet's own, so the sheet, the scene and
    # the frame's title line say the same words — three names for one
    # drawing is one name too many.
    if elevations:
        sheet = next((s for s in made
                      if _sheets_code_group(s) == "elev"), None)
        if sheet is not None:
            label = _sheet_view_label(sheet)
            z0, z_top = _story_span(building)
            box = _building_box(building)
            row = {"kind": "elevation", "story_id": ids[0], "name": label,
                   "p1": [box[0] - 500.0, box[3]],
                   "p2": [box[2] + 500.0, box[3]],
                   "normal": [0.0, 1.0],
                   "z_mm": z0, "height_mm": z_top - z0}
            view = _drawings.view_for(building, row)
            _sheets.fill_sheet(sheet, view, scene, name=label,
                               building=building, annotations=False)
            tick(label, 1)

    # ---- sections -------------------------------------------------------
    if sections:
        z0, z_top = _story_span(building)
        box = _building_box(building)
        cy = (box[1] + box[3]) / 2.0
        sheet = next((s for s in made if _sheets_code_group(s) == "sect"),
                     None)
        if sheet is not None:
            label = _sheet_view_label(sheet)
            row = {"kind": "section", "story_id": ids[0], "name": label,
                   "p1": [box[0] - 500.0, cy], "p2": [box[2] + 500.0, cy],
                   "normal": [0.0, -1.0], "z_mm": z0,
                   "height_mm": z_top - z0}
            view = _drawings.view_for(building, row)
            _sheets.fill_sheet(sheet, view, scene, name=label,
                               building=building, annotations=False)
            tick(label, 1)

    # ---- the door and window location plan ------------------------------
    # The sheet that fixes WHICH door is D01: the same cut as the plan,
    # the openings' layer on and every other trade off, with the schedule
    # beneath it. One sheet answers "where is this door" and "what is it".
    door_sheet = next((s for s in made
                       if _sheets_code_group(s) == "door"), None)
    openings = [e for e in building.elements
                if e.get("type") in ("door", "window")]
    if door_sheet is not None and openings:
        label = _sheet_view_label(door_sheet)
        row = {"kind": "story", "story_id": ids[0], "name": label,
               "cut_mm": float(_drawings.DEFAULT_CUT_MM)}
        view = _drawings.view_for(building, row)
        view.hidden_layers = _layers_except("door")
        _sheets.fill_sheet(door_sheet, view, scene, name=label,
                           building=None, annotations=False)
        if annotations:
            _fill_schedule(door_sheet, "openings", building,
                           key="__schedule_openings__",
                           title="BẢNG THỐNG KÊ CỬA ĐI & CỬA SỔ")
        tick(label, 1)

    # ---- the WC sheet ---------------------------------------------------
    # The plumbing layout of the storey whose rooms say "WC": the main
    # plan's own cut, the fixtures in place, with the fixtures' schedule
    # so the plumber gets a count, not a hunt.
    wc_sheet = next((s for s in made if _sheets_code_group(s) == "wc"), None)
    wc_story = None
    for sid in ids:
        if any(e.get("type") == "fixture"
               and str(e.get("story_id")) == sid
               for e in building.elements):
            wc_story = sid
            break
    if wc_sheet is not None and wc_story is not None:
        story = building.story(wc_story)
        story_name = str((story or {}).get("name") or wc_story)
        label = f"{_sheet_view_label(wc_sheet)} {story_name}".strip()
        row = {"kind": "story", "story_id": wc_story, "name": label,
               "cut_mm": float(_drawings.DEFAULT_CUT_MM)}
        view = _drawings.view_for(building, row)
        view.hidden_layers = _layers_except("fixture")
        _sheets.fill_sheet(wc_sheet, view, scene, name=label,
                           building=None, annotations=False)
        tick("Vệ sinh", 1)

    # ---- the door detail ------------------------------------------------
    # A 1:25 window on one door: what the joiner needs and the plan at 1:100
    # cannot show. It is a CROP of the plan's own rule, so the wall, the
    # opening and the cut agree with the sheet it was taken from.
    detail_sheet = next((s for s in made
                         if _sheets_code_group(s) == "detail"), None)
    first_door = next((e for e in building.elements
                       if e.get("type") == "door"), None)
    if detail_sheet is not None and first_door is not None:
        label = _sheet_view_label(detail_sheet)
        source = _drawings.view_for(
            building, {"kind": "story",
                       "story_id": str(first_door.get("story_id"))})
        params = first_door.get("params") or {}
        host = building.element(str(params.get("host_wall_id") or ""))
        a = (host.get("params") or {}).get("baseline_start_mm")             if host is not None else None
        b = (host.get("params") or {}).get("baseline_end_mm")             if host is not None else None
        if a and b:
            length = math.hypot(b[0] - a[0], b[1] - a[1]) or 1.0
            al = ((b[0] - a[0]) / length, (b[1] - a[1]) / length)
            off = float(params.get("offset_along_wall_mm", 0.0) or 0.0)
            cu = a[0] + al[0] * off
            cv = a[1] + al[1] * off
            half = 1500.0
            rect = [cu - half, cv - half, cu + half, cv + half]
        else:
            rect = [0.0, 0.0, 3000.0, 3000.0]
        view = _drawings.detail_view(
            building, {"kind": "detail", "name": label},
            source, rect=rect, scale_denom=25.0)
        _sheets.fill_sheet(detail_sheet, view, scene, name=label,
                           building=None, annotations=False)
        tick(label, 1)

    # ---- the stair detail ----------------------------------------------
    stair = next((e for e in building.elements if e.get("type") == "stair"),
                 None)
    if stair is not None:
        sheet = next((s for s in made if _sheets_code_group(s) == "stair"),
                     None)
        if sheet is not None:
            source_row = {"kind": "story",
                          "story_id": str(stair.get("story_id"))}
            source = _drawings.view_for(building, source_row)
            params = stair.get("params") or {}
            path = params.get("path_mm") or []
            if path:
                xs = [float(p[0]) for p in path]
                ys = [float(p[1]) for p in path]
                rect = [min(xs) - 500.0, min(ys) - 500.0,
                        max(xs) + 500.0, max(ys) + 500.0]
            else:
                rect = [0.0, 0.0, 3000.0, 4000.0]
            view = _drawings.detail_view(building,
                                         {"kind": "detail",
                                          "name": "Chi tiết cầu thang"},
                                         source, rect=rect, scale_denom=25.0)
            _sheets.fill_sheet(sheet, view, scene, name="Chi tiết cầu thang",
                               building=building, annotations=False)
            tick("Chi tiết cầu thang", 1)

    result.sheets = made
    return result


# ---- helpers ----------------------------------------------------------------

def _sheets_code_group(sheet) -> str:
    """The group key a sheet's code says (``KT04-02`` → ``plan``)."""
    name = str(getattr(sheet, "name", "") or "")
    code = name.split(" ")[0] if name else ""
    for i, (key, *_rest) in enumerate(_sheets.GROUPS):
        if code.startswith(f"{_sheets.SHEET_PREFIX}{i:02d}-"):
            return key
    return ""


def _sheet_view_label(sheet) -> str:
    """The drawing's own name, taken from the sheet it is issued on:
    ``KT09-18 Mặt cắt`` → ``Mặt cắt``."""
    name = str(getattr(sheet, "name", "") or "")
    parts = name.split(" ", 1)
    return parts[1] if len(parts) > 1 else name


def _building_box(building) -> tuple:
    """``(x0, y0, x1, y1)`` over every storey, in mm."""
    box = None
    for story in building.stories or ():
        s = _drawings.story_box(building, story)
        box = s if box is None else (min(box[0], s[0]), min(box[1], s[1]),
                                     max(box[2], s[2]), max(box[3], s[3]))
    return box or (-1000.0, -1000.0, 1000.0, 1000.0)


def _layout_view(building, ids, label, only_kind: str):
    """A top view of only the given trade — the column / beam layout.

    The view carries the layers it KEEPS: one trade's layer on, every other
    BIM layer off. Nothing is copied out of the model, so a column moved on
    the plan the next day is moved on its layout too.
    """
    row = {"kind": "story", "story_id": ids[0], "name": label,
           "cut_mm": 0.0}
    view = _drawings.view_for(building, row)
    view.hidden_layers = _layers_except(only_kind)
    return view


def _layers_except(only_kind: str) -> list:
    """Every BIM element layer except the one that shows the trade."""
    from core.building.scene_sync import TR_NAMES, element_layer
    keep = element_layer(only_kind)
    return [element_layer(kind) for kind in TR_NAMES
            if element_layer(kind) != keep]


def _fill_schedule(sheet, table_key: str, building, *, key: str,
                   title: str = "") -> None:
    """Write one takeoff table onto a sheet as the schedule a reader reads.

    The schedule is the SAME numbers the takeoff prints — a door schedule
    that disagrees with the priced bill is worse than no schedule — so it
    is built from :func:`~core.building.takeoff.tables`, never recounted
    here. Like every derived annotation it is regenerable: re-issuing the
    sheet rewrites this block instead of stacking a second table under it.
    """
    from core.building import takeoff as _takeoff
    from core.composition import TextoItem

    rows = (_takeoff.tables(building) or {}).get(table_key)
    if not rows:
        return
    headers = _takeoff.HEADERS.get(table_key, ())
    if not headers and rows:
        headers = tuple(rows[0].keys())
    lines = [title or f"BẢNG {table_key.upper()}", ""]
    lines.append(" | ".join(str(h) for h in headers))
    lines.append("-" * min(90, max(20, len(lines[-1]))))
    for row in rows:
        lines.append(" | ".join(_cell_text(row.get(h, "")) for h in headers))
    page_w, page_h = sheet.page_size_mm()
    margin = float(sheet.margin_mm)
    block = next((t for t in sheet.texts if t.list_name == key), None)
    if block is None:
        block = TextoItem(x_mm=margin, y_mm=page_h - margin - 90.0,
                          w_mm=page_w - 2 * margin, text="", size_pt=9.0,
                          align="left", list_name=key)
        sheet.texts.append(block)
    block.text = "\n".join(lines)


def _cell_text(value) -> str:
    if isinstance(value, float):
        return f"{value:,.2f}".rstrip("0").rstrip(".")
    return str(value)


def _fill_cover(sheet, project: dict, building) -> None:
    from core.composition import TextoItem
    page_w, page_h = sheet.page_size_mm()
    margin = float(sheet.margin_mm)
    story_count = len(building.stories)
    total_h = sum(float(s.get("height_mm", 3300.0))
                  for s in building.stories)
    body = "\\n".join(
        line for line in (
            str(project.get("name") or ""),
            str(project.get("address") or ""),
            "",
            f"Số tầng: {story_count}",
            f"Tổng chiều cao: {total_h / 1000.0:.2f} m",
            "",
            str(project.get("designer") or ""),
        ) if line is not None)
    block = next((t for t in sheet.texts
                  if t.list_name == "__cover__"), None)
    if block is None:
        block = TextoItem(x_mm=margin, y_mm=page_h / 3.0,
                          w_mm=page_w - 2 * margin,
                          text="", size_pt=16.0, align="center",
                          list_name="__cover__")
        sheet.texts.append(block)
    block.text = body


def _fill_index(sheet, made, project: dict) -> None:
    from core.composition import TextoItem
    page_w, _page_h = sheet.page_size_mm()
    margin = float(sheet.margin_mm)
    block = next((t for t in sheet.texts
                  if t.list_name == "__index__"), None)
    if block is None:
        block = TextoItem(x_mm=margin, y_mm=margin, w_mm=page_w - 2 * margin,
                          text="", size_pt=11.0, align="left",
                          list_name="__index__")
        sheet.texts.append(block)
    block.text = _sheets.sheet_index_text(made, project)
