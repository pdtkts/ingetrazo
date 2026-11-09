# BIM

IngeTrazo draws freeform geometry — faces, edges, push/pull — and BIM is a
**parametric layer on top of that**, not a replacement for it. A wall is a
baseline, a thickness and a height; its geometry is generated from those
parameters and rebuilt when they change, and the drawing set, the schedule
and the IFC all read the same parameters. The freeform tools keep working
on everything else, and the two live in one document.

Everything here is millimetres on the model (a wall is `start → end` in
millimetres), and the drawings are the Vietnamese office's: plans cut at
+1200, dimension chains 10 and 18 mm of paper off the outer face, levels
written `FL:+0000`, sheets numbered `KT04-05`.

---

## 1. Storeys and elements

The **BIM** menu carries the building tools; the **Building** panel (same
menu) lists storeys and elements with their parameters.

| Tool | What it makes |
|---|---|
| Wall | A polyline of any thickness, with a baseline placed left / centre / right and a top that can follow the storey above. |
| Column / Beam | Rectangular sections, the beam following a baseline. |
| Slab / Ceiling | An outline with a thickness — a floor, a soffit. |
| Roof | An outline, a slope, an overhang. Single-slope over a convex outline. |
| Stair | A centre line; the treads follow it and rise to the storey above. |
| Door / Window | An opening **cut into its host wall**, with the leaf or glazing drawn in. Move the wall and the opening follows: its geometry is the host's, and the rebuild knows it. |
| Curtain wall | A glazed grid over an opening. |
| Room (zone) | A boundary that carries a name and an area. |
| Fixture | A sanitary fixture at a point, turned by its angle. |
| Eyedropper / Apply properties | Take a building element's **specification** (thickness, material, name, height) and give it to others — a click each. The PLACEMENT never travels: a wall keeps its own two ends and a door keeps its own host, because copying those would move the element, which is what Move is for. Applying to a whole selection is one undo step. |

Elements are **data**: changing a parameter rebuilds the geometry, and the
whole operation is one undo step (including the geometry).

Two rules keep a plan honest without anyone remembering them:

* cutting a door or window into a wall subtracts its area from that wall,
  so the schedule and the picture can never disagree;
* the plan has no explicit "hide the storey below" step — a plan is cut at
  +1200 and trimmed at its own floor, so the ground never shows through.

## 2. The drawing set

**BIM ▸ Lập hồ sơ tự động…** generates the whole set in one operation:
cover, sheet list, the layouts the model actually contains, per storey the
plan / wall plan / floor plan / ceiling plan, the elevations, a section
through the building's middle, and a detail of the stair when there is one.

Each sheet is filled with its drawing: the frame bound to a **scene** that
carries the drawing's rule (camera, its cut at +1200, its floor trim), so
the sheet never depends on where the live camera was left.

Running it again **re-fills the same sheets** and replaces the previous
run's dimensions and room stamps — they are derived data, and leaving them
would print two dimension chains disagreeing about one wall.

**BIM ▸ Kiểm tra hồ sơ…** says what is missing *before* the run (a storey
with no walls, a plan with no rooms), because an empty sheet looks exactly
like a finished one until it is printed.

**BIM ▸ Thông tin dự án…** is the job's own data — what the title block
prints on every sheet: the works, the item, the investor, the address, who
drew it and who is answerable, the date and the issue. It is document
data (`building.project`), written as one undo step, so re-issuing the set
carries the corrected name on all forty sheets instead of it being
retyped per sheet and drifting. A field left blank falls back to the
office's own defaults (**BIM ▸ Văn phòng…**).

## 3. The language of a plan

Auto-annotation writes what a drafter would:

* **two dimension chains** outside the house — the openings' edges 10 mm of
  paper off the outer face, the wall ends at 18. The stand-off is *paper*
  millimetres × the scale, so a 1:50 plan and a 1:25 detail of the same wall
  agree about where the dimension line sits;
* **level marks** `FL:+0000` / `CL:+2700`, in their own layer;
* **room stamps** carrying the same area the schedule states.

All of it lands on one layer (`KT-Ghi chú`), so an office hides the whole
annotation set with one switch, and all of it is ordinary dimensions and
texts: they pick, edit, print and export like anything else.

## 4. Schedule, files

**BIM ▸ Bảng thống kê (CSV)…** writes the bill in the form a Vietnamese
Excel opens (semicolons, BOM, CRLF, decimal comma). The wall table states
both rules: the **gross** area a priced bill is written from, and the
deduction down to what the wall actually is.

**BIM ▸ Xuất DXF bản vẽ…** writes the plan as a DXF another CAD opens —
lines by class on their own layers with their pens, the section's HATCH
fill **by material**, real DIMENSION and TEXT entities, millimetres
declared. The file
carries **this** storey's annotations and nobody else's, and it reuses the
key the drawing set already published that storey under, so exporting
twice leaves the sheet as it was rather than doubling its dimension
chains.

**BIM ▸ Nâng cao** holds the maintenance a long job needs:

| Entry | What it does |
|---|---|
| Dựng lại mô hình (nối tường) | Rebuilds every element's geometry from its parameters, changing no parameter — the answer to a corner that did not join, and to a picture that disagrees with the numbers. |
| Kiểm tra DXF đã xuất… | Reads a file that has already **left** the application back and holds it against the model: a layer rename that reached the dialog and not the exporter, a cut whose hatch became ink, a pen ladder flattened to one width. It reports; it never repairs. |
| Đo lag… | The live model's own numbers — elements, storeys, faces, the cost of a full rebuild and of a repaint. The question mid-job is «is MY file the problem». |
| Tạm dừng BIM | Holds BIM geometry regeneration while freeform work goes on. Every path that rebuilds asks this one switch, so the parameters keep being written and the geometry catches up when it is released; the switch is session state and never travels in the file. |

**File ▸ IFC (BIM)…** writes IFC4: storeys as `IfcBuildingStorey`, walls,
doors and windows with `IfcOpeningElement` + `IfcRelVoidsElement` +
`IfcRelFillsElement`, rooms as `IfcSpace`, and quantities from the same
engine the schedule reads. It validates with zero statements against
`ifcopenshell`.

Elements are filed under a layer per trade (`BIM Tường`, `BIM Cửa`…),
which is what makes a layout possible: it shows one trade and hides the
rest.

### Surface fill by element

A cut area is hatched by **what that area is made of**, not by one pattern
for the whole sheet: a concrete column standing in a masonry wall reads as
concrete against masonry, which is the one thing a poché is for. The
pattern table is `core/building/patterns.py` (the Vietnamese materials and
their `cut_fill`), and the same table drives the sheet, the DXF and the
plan window — so a wall hatch that prints and a wall hatch that exports
are the same wall.

The hidden-line pass returns closed cut rings carrying no identity of their
own (they are chained chords from a triangle soup), so
`core/building/surface_fill.py` recovers the attribution: each element's
own geometry is cut by the same plane and the rings are matched by their
vertex set. A ring that cannot be matched keeps the drawing's default
material rather than vanishing — an unattributed area is still a cut area.

An area's material follows, in order, the element's own `material_id`,
its `building_material_id` (the building fabric the element is built of —
how a wall knows it is masonry), or the default its KIND carries.

## 5. From an AI client

The MCP bridge exposes the whole engine as one tool. An agent builds a
house with `bim`:

```
action="story"   name="Tầng 1"  z_mm=0        height_mm=3300
action="wall"    story_id=…  start_mm=[0,0]  end_mm=[6000,0]
action="door"    wall_id=…   u_mm=3000        width_mm=900
action="room"    story_id=…  outline_mm=[[0,0],[6000,0],[6000,4000],[0,4000]]
action="takeoff"
action="docset"
action="export_ifc"  path="model.ifc"
```

Every call runs in the user's undo stack and appears on screen as it
happens. In `run_python` the same engine is bound as `bim` (and `tags` is
the face-tagging layer, for BIM on freeform geometry).

## 6. Cheques worth writing

| Check | Command |
|---|---|
| The three-storey acceptance run | `python scripts/e2e_bim_demo.py` |
| What a 3000-element model costs | `python scripts/bench_bim.py` |
| The building tests | `python -m pytest tests/test_building_*.py tests/test_bim_menu.py tests/test_ai_bim.py -q` |
| The plan's own line tools | `python -m pytest tests/test_plan_curves.py tests/test_surface_fill.py -q` |
| The AI bridge parity | `python -m pytest tests/test_ai_bim.py tests/test_pick_inject.py -q` |
