# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Marco Sumari Tellez and IngeTrazo contributors.
"""Ống hút / Ống nhả — copy a building element's properties onto others.

The office does not retype a wall's build-up twenty times: it samples the
wall the engineer specified and applies it to the rest. That is the whole
of this pair of tools, and it is the same gesture the Paint tool has for
materials — one click to take, one to give — because a user who has learnt
it for paint should not learn a second one for parameters.

What travels is the properties, never the geometry: sampling a 220 wall and
dropping it on another wall changes the second wall's thickness, material
and name class, and leaves its own two ends where the user drew them. A
column sampled onto a wall is refused in words — a wall with a column's
parameters is a wall the builder cannot build.
"""
from __future__ import annotations

from core.i18n import tr
from tools.base import Tool, ToolContext

#: The properties that travel, per the element schema. Anything not named
#: here belongs to the element's PLACEMENT (a wall's ends, a door's host),
#: and copying those would move the target rather than re-specify it —
#: which is what the Move tool is for.
def transferable(params: dict) -> dict:
    """The subset of ``params`` a sample carries: the specification."""
    skip = ("baseline_start_mm", "baseline_end_mm", "host_wall_id",
            "offset_along_wall_mm", "outline_mm", "axes", "points",
            "centre_mm", "path_mm", "start_mm", "end_mm", "id")
    return {str(k): v for k, v in (params or {}).items()
            if str(k) not in skip and not str(k).startswith("_")}


def _pick_element(viewport, screen_x: float, screen_y: float):
    """The building element under the cursor, or ``None``.

    Resolved through ``scene_sync``'s own key — the mapping the rebuild
    uses — never by matching a group's name.
    """
    from core.building.model import building_of
    from core.building.scene_sync import EXT_KEY

    group = viewport.pick_group(screen_x, screen_y)
    entity = group
    if entity is None:
        pick_edge = getattr(viewport, "pick_edge", None)
        entity = pick_edge(screen_x, screen_y) if pick_edge else None
    ext = getattr(entity, "ext", None)
    if not isinstance(ext, dict):
        return None
    element_id = str((ext.get(EXT_KEY) or {}).get("id") or "")
    if not element_id:
        return None
    return building_of(viewport.scene).element(element_id)


class PickTool(Tool):
    """Ống hút: take a building element's specification, ready to give."""

    name = "Eyedropper"
    icon = "eyedropper"
    shortcut = None
    description = (
        "Lấy thông số của một cấu kiện (bề dày, vật liệu, tên) để Ống nhả "
        "áp cho cấu kiện khác. Không đổi gì cả — chỉ ghi nhớ.")

    def on_activate(self, viewport) -> None:
        viewport.flash_status(tr(
            "Ống hút: bấm vào cấu kiện cần lấy thông số."))

    def on_deactivate(self, viewport) -> None:
        viewport.set_hover(None)

    def on_click(self, ctx: ToolContext) -> None:
        viewport = ctx.viewport
        element = _pick_element(viewport, ctx.screen.x(), ctx.screen.y())
        if element is None:
            viewport.flash_status(tr(
                "Không có cấu kiện nào ở đây — bấm đúng vào cấu kiện BIM."))
            return
        from core.building import registry as _registry

        label = tr(_registry.find(str(element.get("type")))[1]
                   if _registry.find(str(element.get("type")))
                   else str(element.get("type")))
        spec = transferable(element.get("params") or {})
        viewport.scene.plugin_data["bim_sample"] = {
            "kind": str(element.get("type")),
            "name": str((element.get("params") or {}).get("name") or ""),
            "params": spec,
        }
        viewport.flash_status(tr(
            "Đã lấy thông số của %s «%s» (%d trường) — chuyển sang Ống nhả "
            "để áp cho cấu kiện khác.") % (label, _spec_name(element),
                                           len(spec)))

    def on_key(self, viewport, key, modifiers) -> bool:
        return False


def _spec_name(element) -> str:
    params = element.get("params") or {}
    return str(params.get("name") or params.get("material")
               or element.get("type") or "")


class InjectTool(Tool):
    """Ống nhả: apply the sampled specification to the clicked elements."""

    name = "Apply properties"
    icon = "paint"
    shortcut = None
    description = (
        "Áp thông số đã lấy bằng Ống hút cho cấu kiện được bấm — hoặc cho "
        "mọi cấu kiện đang chọn nếu bấm ra ngoài. Cùng loại cấu kiện mới "
        "nhận; khác loại thì từ chối và nói rõ.")

    def on_activate(self, viewport) -> None:
        from core.building import registry as _registry

        sample = (viewport.scene.plugin_data or {}).get("bim_sample")
        if not sample:
            viewport.flash_status(tr(
                "Chưa có thông số nào — dùng Ống hút lấy từ một cấu kiện "
                "trước đã."))
            return
        found = _registry.find(str(sample.get("kind")))
        viewport.flash_status(tr(
            "Ống nhả %s «%s»: bấm cấu kiện cần áp, hoặc bấm ra ngoài để áp "
            "cho cả vùng đang chọn.")
            % (tr(found[1]) if found else str(sample.get("kind")),
               str(sample.get("name") or "")))

    def on_deactivate(self, viewport) -> None:
        viewport.set_hover(None)

    def _sample(self, viewport):
        return (viewport.scene.plugin_data or {}).get("bim_sample")

    def on_click(self, ctx: ToolContext) -> None:
        viewport = ctx.viewport
        sample = self._sample(viewport)
        if not sample:
            viewport.flash_status(tr(
                "Chưa có thông số nào — dùng Ống hút trước đã."))
            return
        element = _pick_element(viewport, ctx.screen.x(), ctx.screen.y())
        if element is None:
            self._apply_to_selection(viewport, sample)
            return
        self._apply_to(viewport, sample, [element])

    def _apply_to_selection(self, viewport, sample) -> None:
        from core.building.model import building_of
        from core.building.scene_sync import EXT_KEY

        scene = viewport.scene
        ids: list = []
        for entity in list(scene.selection or ()):
            ext = getattr(entity, "ext", None)
            if not isinstance(ext, dict):
                continue
            eid = str((ext.get(EXT_KEY) or {}).get("id") or "")
            if eid:
                ids.append(eid)
        if not ids:
            viewport.flash_status(tr(
                "Không có cấu kiện nào ở đây và không có gì đang chọn."))
            return
        building = building_of(scene)
        targets = [e for e in (building.element(i) for i in ids)
                   if e is not None]
        if not targets:
            viewport.flash_status(tr(
                "Vùng đang chọn không có cấu kiện BIM nào."))
            return
        self._apply_to(viewport, sample, targets)

    def _apply_to(self, viewport, sample, targets) -> None:
        """One undo step for the whole application, whatever its size."""
        from core.building import commands as _commands
        from core.building.scene_sync import sync

        kind = str(sample.get("kind"))
        params = dict(sample.get("params") or {})
        same = [e for e in targets if str(e.get("type")) == kind]
        other = [e for e in targets if str(e.get("type")) != kind]
        if not same:
            viewport.flash_status(tr(
                "Không áp được: Ống hút lấy thông số của «%s», còn thứ đang "
                "bấm là «%s» — chỉ cùng loại mới nhận.")
                % (kind, str(targets[0].get("type")) if targets else "?"))
            return
        if not params:
            viewport.flash_status(tr("Cấu kiện đã lấy không có thông số nào."))
            return

        from core.history import CompoundCommand

        commands = [_commands.set_params(str(e["id"]), params)
                    for e in same]
        for command in commands:
            command._rebuild = lambda s, b: sync(s, b)
        history = viewport.history
        if len(commands) == 1:
            history.execute(commands[0])
        else:
            # ONE step: a user who applies a wall's specification to nine
            # walls expects ONE Ctrl+Z, not nine.
            history.execute(CompoundCommand(commands))
        if history.last_error:
            viewport.flash_status(str(history.last_error))
            return
        message = tr("Đã áp thông số cho %d cấu kiện.") % len(same)
        if other:
            message += " " + tr("Bỏ qua %d cấu kiện khác loại.") % len(other)
        viewport.flash_status(message)
        viewport.notify_scene_changed()

    def on_key(self, viewport, key, modifiers) -> bool:
        return False


__all__ = ["PickTool", "InjectTool", "transferable", "SelectTool"]
