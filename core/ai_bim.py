# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Marco Sumari Tellez and IngeTrazo contributors.
"""The BIM engine as one object an AI script can use.

An agent told to "make a three-storey townhouse" should not have to learn
the element schemas, the story bookkeeping and the undo command from a
reference: this is the small vocabulary that covers the whole flow, bound
into the execution scope as ``bim``.

Every call goes through the host's undo stack (the same
:class:`~core.history.History` the user's own clicks use), so an agent's
work is ONE step to undo and appears on screen as it happens — the
principle the AI bridge is built on.
"""
from __future__ import annotations

__all__ = ["BimSession"]


class BimSession:
    """The building engine, spoken to in whole operations."""

    def __init__(self, viewport, history=None) -> None:
        self._viewport = viewport
        self._history = history

    # ---- the model ------------------------------------------------------
    @property
    def scene(self):
        return self._viewport.scene

    @property
    def building(self):
        from core.building.model import building_of
        return building_of(self.scene)

    def stories(self) -> list[dict]:
        return list(self.building.stories)

    def elements(self, kind: str | None = None,
                 story_id: str | None = None) -> list[dict]:
        return [e for e in self.building.elements
                if (kind is None or str(e.get("type")) == kind)
                and (story_id is None
                     or str(e.get("story_id")) == str(story_id))]

    def find(self, name: str) -> dict | None:
        """The first element whose name carries ``name`` (case-insensitive)."""
        wanted = str(name).strip().lower()
        for element in self.building.elements:
            params = element.get("params") or {}
            if wanted in str(params.get("name") or "").lower():
                return element
        return None

    def element(self, element_id: str) -> dict | None:
        return self.building.element(str(element_id))

    # ---- building -------------------------------------------------------
    def add_story(self, name: str, z_mm: float = 0.0,
                  height_mm: float = 3300.0) -> dict:
        from core.building.commands import add_story
        self._run(add_story(name, z_mm, height_mm))
        rows = self.building.stories
        return rows[-1] if rows else {}

    def add(self, kind: str, story_id: str, **params) -> dict:
        """Add one element of ``kind`` to a storey, in the host's undo."""
        from core.building.commands import add_element
        self._run(add_element(str(kind), str(story_id), params))
        return self._last(str(kind))

    def edit(self, element_id: str, **params) -> dict:
        """Change one element's parameters and rebuild its geometry."""
        from core.building.commands import set_params
        self._run(set_params(str(element_id), params))
        return self.element(element_id) or {}

    def change_kind(self, element_id: str, kind: str) -> dict:
        """Change what an element IS, keeping the parameters that apply.

        Refused for a hosted type (a door, a window, a curtain wall) with
        the reason and the gesture that works — an agent should get the
        same sentence a person gets, not a half-built element.
        """
        from core.building.commands import change_kind
        self._run(change_kind(str(element_id), str(kind)))
        return self.element(element_id) or {}

    def steel(self, name: str = "") -> list:
        """The rolled-section catalogue, or the dimensions of one name."""
        from core.building import steel as _steel

        if name:
            record = _steel.by_name(str(name))
            return ([] if record is None else
                    [{"name": str(name), "h_mm": record[0], "b_mm": record[1],
                      "tw_mm": record[2], "tf_mm": record[3],
                      "kg_per_m": record[4]}])
        return [{"name": key, "kg_per_m": row[4]}
                for key, row in _steel.SECTIONS.items()]

    def set_steel(self, element_id: str, name: str) -> dict:
        """Make a column or beam BE a catalogue section."""
        from core.building import steel as _steel
        from core.building.commands import set_params

        values = _steel.adopt({}, str(name))
        if not values:
            raise ValueError(f"không có tiết diện {name!r} trong bảng thép")
        self._run(set_params(str(element_id), values))
        return self.element(element_id) or {}

    def remove(self, element_id: str) -> None:
        from core.building.commands import remove_element
        self._run(remove_element(str(element_id)))

    def wall(self, story_id: str, start_mm, end_mm, *, thickness_mm: float = 200.0,
             height_mm: float = 3300.0, top_link: str = "next",
             material: str = "gach", name: str = "") -> dict:
        return self.add("wall", story_id, baseline_start_mm=list(start_mm),
                        baseline_end_mm=list(end_mm),
                        thickness_mm=float(thickness_mm),
                        height_mm=float(height_mm), top_link=top_link,
                        building_material_id=material, name=name)

    def room(self, story_id: str, outline_mm, name: str = "") -> dict:
        return self.add("zone", story_id, outline_mm=[list(p) for p in
                                                     outline_mm], name=name)

    def door(self, wall_id: str, u_mm: float, *, width_mm: float = 900.0,
             height_mm: float = 2200.0, name: str = "") -> dict:
        host = self.element(str(wall_id)) or {}
        return self.add("door", str(host.get("story_id")), host_wall_id=str(wall_id),
                        offset_along_wall_mm=float(u_mm),
                        width_mm=float(width_mm), height_mm=float(height_mm),
                        sill_height_mm=0.0, name=name)

    def window(self, wall_id: str, u_mm: float, *, width_mm: float = 1200.0,
               height_mm: float = 1200.0, sill_height_mm: float = 900.0,
               name: str = "") -> dict:
        host = self.element(str(wall_id)) or {}
        return self.add("window", str(host.get("story_id")),
                        host_wall_id=str(wall_id),
                        offset_along_wall_mm=float(u_mm),
                        width_mm=float(width_mm), height_mm=float(height_mm),
                        sill_height_mm=float(sill_height_mm), name=name)

    # ---- reading the result --------------------------------------------
    def takeoff(self) -> dict:
        from core.building.takeoff import tables
        return tables(self.building)

    def takeoff_csv(self) -> str:
        from core.building.takeoff import all_csv
        return all_csv(self.building)

    def drawings(self, kind: str = "story",
                 story_id: str | None = None) -> dict:
        """The rule of one drawing — camera, cut, trims — as data."""
        from core.building import drawings as _drawings
        story_id = story_id or (self.building.stories[0]["id"]
                                if self.building.stories else None)
        row = {"kind": kind, "story_id": story_id}
        if kind in ("section", "elevation", "interior"):
            box = _drawings.story_box(
                self.building,
                self.building.story(str(story_id)) or
                {"id": str(story_id)})
            cy = (box[1] + box[3]) / 2.0
            row.update(p1=[box[0] - 500.0, cy], p2=[box[2] + 500.0, cy],
                       normal=[0.0, -1.0], z_mm=0.0, height_mm=9900.0)
        return _drawings.view_for(self.building, row).to_dict()

    def docset(self, paper: str = "A3") -> list:
        """Lập hồ sơ: the whole drawing set, into the live scene."""
        from core.building import docset as _docset
        return _docset.generate_docset(self.scene, self.building,
                                       paper=paper).sheets

    def export_ifc(self, path: str) -> int:
        from formats.ifc import save_building_ifc
        return save_building_ifc(self.scene, path)

    def export_dxf(self, path: str, story_id: str | None = None) -> dict:
        from core.building import drawings as _drawings
        from core.building import pens as _pens
        from formats.dxf_bim import save_plan_dxf

        story_id = story_id or (self.building.stories[0]["id"]
                                if self.building.stories else None)
        # The annotations this drawing is filed under. Without a key the
        # export falls back to «everything the document holds» and writes
        # ALL storeys' levels and room stamps onto one floor's drawing —
        # numbers that are not wrong, only about a drawing nobody is
        # looking at. So the export PUBLISHES this storey's annotations
        # under its own key first, exactly as the menu does, and exports
        # that: the agent's file is then the same drawing the menu's is.
        #
        # The key REUSES the one a drawing set already filed this storey
        # under. Minting a private `dxf:<id>` beside it left BOTH sets in
        # the document, and the composer draws every dimension its frame
        # can see — so one bridge export doubled the sheet's chains and the
        # duplicate set stayed in the file. The menu was fixed for this;
        # the agent's path was not.
        from formats.dxf_bim import resolve_annotation_key

        view = _drawings.view_for(
            self.building, {"kind": "story", "story_id": str(story_id)})
        view.annotation_key = resolve_annotation_key(self.scene, view)
        _drawings.annotate_plan(self.scene, self.building, view,
                                key=view.annotation_key)
        # The office's own inking travels with the file, exactly as the
        # menu's export does: an agent's DXF must not come out in default
        # pens while the same drawing from the menu comes out in the
        # office's.
        pen_table, layer_map = _pens.export_tables(self.scene)
        return save_plan_dxf(path, self.scene, self.building, str(story_id),
                             annotation_key=view.annotation_key,
                             pens=pen_table, layer_map=layer_map)

    def sample(self, key: str) -> dict:
        """Dựng nhanh 3D: one whole sample building, built through the same
        commands a hand does, so the result is an ordinary model."""
        from core.building import samples as _samples

        history = self._history or getattr(self._viewport, "history", None)
        if history is None:
            raise RuntimeError("Phiên BIM không có sổ hoàn tác nào.")
        _building, counts = _samples.build_sample(history, self.scene,
                                                  str(key))
        return {"sample": _samples.name(key), "counts": counts}

    def pens(self) -> dict:
        """How this document inks a drawing: the tables the DXF and the
        paper both read."""
        from core.building import pens as _pens

        return {"pens": {key: list(value)
                         for key, value in _pens.pens(self.scene).items()},
                "layer_renames": dict(_pens.renames(self.scene))}

    def set_pen(self, key: str, width_mm: float,
                color: int | str | None = None,
                linetype: str | None = None) -> dict:
        """Set one class of line: the office's pen for it.

        ``color`` is the AutoCAD index (7 = black, 1 = red ...), which is
        what both tables store. A hex string is REFUSED rather than parsed:
        an agent that guessed the format should be told, not silently
        given a pen it never chose.
        """
        from core.building import pens as _pens

        current = _pens.pen(self.scene, key)
        if color is not None:
            if isinstance(color, str):
                try:
                    color = int(color, 10)
                except ValueError:
                    raise ValueError(
                        f"màu bút là chỉ số AutoCAD (0-256), không phải "
                        f"{color!r}") from None
            color = int(color)
            if not 0 <= color <= 256:
                raise ValueError(f"chỉ số màu {color} ngoài 0-256")
        table = _pens.pens(self.scene)
        table[str(key)] = (round(float(width_mm), 2),
                           int(current[1] if color is None else color),
                           str(current[2] if linetype is None else linetype))
        # The table is DOCUMENT data: the bridge is a way of editing the
        # document, so it marks it dirty exactly as the dialog does.
        self.scene.version += 1
        return {"pen": list(table[str(key)])}

    def list_samples(self) -> list:
        from core.building import samples as _samples

        return [{"key": key, "name": _samples.name(key),
                 "note": _samples.preset(key)["note"]}
                for key in _samples.keys()]

    def rename_layer(self, key: str, name: str) -> dict:
        """Give one class of line the office's own layer name on the way
        out — ``key`` may be the class (``cut``) or the layer the file
        carries today (``KT-CUT``). An empty ``name`` puts the class's own
        layer back. The name is refused when it cannot be a DXF layer:
        the file's layer table is the drawing office's contract, and a
        name with a stray newline breaks the whole export, not one line.
        """
        from core.building import pens as _pens

        # ``key`` may be the class, the layer the file carries today, or
        # the name the office gave it — an agent that just renamed a layer
        # reads the new name back from ``pens`` and must be able to use it.
        table = dict(_pens.LAYER_KEYS)
        renames = dict(_pens.renames(self.scene))
        standard = table.get(str(key))
        if standard is None:
            standard = next((v for v in table.values() if v == str(key)), None)
        if standard is None:
            standard = next((std for std, own in renames.items()
                             if own == str(key)), None)
        if standard is None:
            raise ValueError(
                f"không có lớp {key!r}; các lớp: {sorted(table)}")
        wanted = str(name or "").strip()
        if wanted and ("\n" in wanted or "\r" in wanted or
                       any(ch in wanted for ch in '<>/\\":;?*=`,')):
            raise ValueError(f"tên lớp không hợp lệ: {wanted!r}")
        renames = _pens.renames(self.scene)
        if wanted and wanted != standard:
            renames[standard] = wanted
        else:
            renames.pop(standard, None)
        self.scene.version += 1
        # The answer is the layer the file will now carry, asked by the
        # CLASS's own key — not by whatever name the caller happened to
        # use, which may be the old name it just replaced.
        return {"layer": _pens.renames(self.scene).get(standard)
                or _pens.LAYER_KEYS.get(standard, standard)}



    # ---- internals ------------------------------------------------------
    def _run(self, command) -> None:
        """Run one building command through the host's own undo stack.

        The rebuild hook is attached here rather than at each call site:
        every path that changes the building must regenerate its geometry,
        and forgetting it once leaves a model whose numbers and picture
        disagree.
        """
        from core.building import scene_sync

        def rebuild(scene, building):
            scene_sync.sync(scene, building)

        # The hook goes ON the command, not after it: the command runs it
        # inside its own step, so the snapshot covers the rebuilt geometry
        # and undo/redo restore the picture as well as the parameters.
        # Calling sync() after execute() leaves the step's snapshot blind
        # to the geometry it just built.
        if getattr(command, "_rebuild", None) is None:
            command._rebuild = rebuild
        history = self._history or getattr(self._viewport, "history", None)
        if history is not None:
            history.execute(command)
            # A command that DECLINED (a hosted type without a host, a bad
            # join) is a no-op with a reason in ``last_rejected``. An agent
            # that is not told runs on believing its edit happened, and its
            # next call is built on a model that does not exist — so the
            # reason is raised here, in the words the UI would show.
            rejected = getattr(history, "last_rejected", None)
            if rejected:
                raise ValueError(str(rejected))
            if getattr(history, "last_error", None):
                raise ValueError(str(history.last_error))
        else:
            command.do(self.scene)

    def _last(self, kind: str) -> dict:
        found = self.elements(kind)
        return found[-1] if found else {}
