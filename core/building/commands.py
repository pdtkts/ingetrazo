# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Marco Sumari Tellez and IngeTrazo contributors.
"""Undoable operations on the building model.

Two things change when a BIM element is edited: its **parameters** (the truth)
and the **geometry** derived from them (the cache). Both must come back in one
step, or an undo leaves a wall that says 200 mm thick showing the 100 mm solid
it wore a moment ago. :class:`BuildingEdit` therefore does both and snapshots
both — the mesh through the host's own ``capture_state``/``restore_state``, the
building through its serialized payload — exactly the doctrine of
``SnapshotCompound`` for operations whose inverses do not compose.

The identity rule that follows: **never hold a** :class:`~core.building.model.Building`
**across an undo**. Always ask :func:`~core.building.model.building_of`, which
hands back the live model for the current state.
"""
from __future__ import annotations

from core.building import model as building_model
from core.history import Command

__all__ = ["BuildingEdit", "add_story", "remove_story", "add_element",
           "set_params", "remove_element", "set_story_params",
           "set_project", "commit"]


class BuildingEdit(Command):
    """One BIM operation: a mutation of the building, its geometry rebuilt.

    ``mutate(building)`` receives the live building and changes it in place.
    ``rebuild`` (optional) regenerates the derived geometry for whatever the
    mutation touched — ``rebuild(scene, building)`` — and runs inside the same
    undo step, so the mesh snapshot covers it.

    The command keeps its data cheap: the building payload is parameters (no
    vertices), so snapshotting it per operation costs far less than the mesh
    snapshot the host takes anyway.
    """

    #: The building's parameters are not paint, but the *geometry* this
    #: command rebuilds does change what the model wears: no cache shortcut.
    keeps_paint = False
    keeps_groups = False

    def __init__(self, mutate, rebuild=None) -> None:
        self._mutate = mutate
        self._rebuild = rebuild
        self._before_payload = None
        self._after_payload = None
        self._mesh_before = None

    # ---- internals -------------------------------------------------------
    @staticmethod
    def _live(scene):
        return building_model.building_of(scene)

    def _apply_payload(self, scene, payload) -> None:
        """Put ``payload`` in place, invalidating the live-object cache."""
        data = scene.plugin_data
        if payload is None:
            data.pop(building_model.DATA_KEY, None)
        else:
            data[building_model.DATA_KEY] = payload
        # The cached Building no longer matches ``plugin_data``: drop it so
        # the next ``building_of`` builds from what is actually stored.
        cache = getattr(scene, "_building_cache", None)
        if cache is not None and cache[0] is scene:
            del scene._building_cache

    def do(self, scene) -> None:
        if self._after_payload is not None:
            # Redo: the state was computed on the first run — reinstate it.
            self._apply_payload(scene, self._after_payload)
            if self._rebuild is not None:
                self._rebuild(scene, self._live(scene))
            scene.version += 1
            return
        self._mesh_before = scene.mesh.capture_state()
        self._before_payload = self._payload(scene)
        building = self._live(scene)
        self._mutate(building)
        building_model.store(scene, building)
        if self._rebuild is not None:
            self._rebuild(scene, building)
        self._after_payload = self._payload(scene)
        scene.version += 1

    def undo(self, scene) -> None:
        if self._mesh_before is not None:
            scene.mesh.restore_state(self._mesh_before)
        self._apply_payload(scene, self._before_payload)
        # The payload is back but the SCENE geometry is not: a rebuilt
        # group (a wall's body, a door's cut) lives in scene.groups, and
        # restoring the mesh snapshot does not touch it. Without this the
        # parameter would say 200 mm while the wall stood 400 mm thick —
        # and the drawings and the IFC read the mesh, so the picture and
        # the numbers would disagree after an undo.
        if self._rebuild is not None:
            self._rebuild(scene, self._live(scene))
        scene.version += 1

    @staticmethod
    def _payload(scene):
        raw = (getattr(scene, "plugin_data", None) or {}).get(
            building_model.DATA_KEY)
        # A deep copy through JSON: the payload must not alias live objects
        # (the same contract ``SetPluginDataCommand`` keeps).
        import json
        return None if raw is None else json.loads(json.dumps(raw))


# ---- Convenience builders ---------------------------------------------------
# Each returns the command; the caller runs ``history.execute(cmd)``. Keeping
# the creation and the execution apart lets a tool inspect, refuse or combine
# before it commits — and lets tests run the command directly.

def add_story(name: str, z_mm: float = 0.0, height_mm: float = 3300.0,
              rebuild=None, **extra) -> BuildingEdit:
    """Add a storey. ``rebuild`` refreshes derived geometry afterwards."""
    def mutate(b):
        b.add_story(name, z_mm, height_mm, **extra)
    return BuildingEdit(mutate, rebuild)


def remove_story(story_id: str, rebuild=None) -> BuildingEdit:
    """Remove a storey together with the elements that sit on it."""
    def mutate(b):
        b.stories[:] = [s for s in b.stories if s["id"] != story_id]
        b.elements[:] = [e for e in b.elements
                         if e.get("story_id") != story_id]
        if b.settings.get("active_story") == story_id:
            b.settings.pop("active_story", None)
    return BuildingEdit(mutate, rebuild)


def add_element(kind: str, story_id: str, params: dict,
                rebuild=None) -> BuildingEdit:
    """Add an element of ``kind`` on the given storey."""
    def mutate(b):
        b.add_element(kind, story_id, params)
    return BuildingEdit(mutate, rebuild)


def set_params(element_id: str, params: dict, rebuild=None) -> BuildingEdit:
    """Merge ``params`` into one element's parameters (None removes a key)."""
    def mutate(b):
        row = b.element(element_id)
        if row is None:
            return
        store = row.setdefault("params", {})
        for key, value in params.items():
            if value is None:
                store.pop(key, None)
            else:
                store[key] = value
    return BuildingEdit(mutate, rebuild)


def remove_element(element_id: str, rebuild=None) -> BuildingEdit:
    """Take one element out of the model."""
    def mutate(b):
        b.remove_element(element_id)
    return BuildingEdit(mutate, rebuild)


def set_story_params(story_id: str, values: dict, rebuild=None) -> BuildingEdit:
    """Merge ``values`` into a storey row (name, z_mm, height_mm, …)."""
    def mutate(b):
        row = b.story(story_id)
        if row is None:
            return
        for key, value in values.items():
            if value is None:
                row.pop(key, None)
            else:
                row[key] = value
        b.sort_stories()
    return BuildingEdit(mutate, rebuild)


def set_project(values: dict, rebuild=None) -> BuildingEdit:
    """Merge project data (name, address, …) used by title blocks."""
    def mutate(b):
        b.project.update(values)
    return BuildingEdit(mutate, rebuild)


def changed_ids_between(before_payload, after_payload):
    """The ids a STEP touched: the diff between its own two payloads.

    This is the question a targeted rebuild actually asks — «which
    elements did this step move» — and it is NOT the same as «which
    elements differ from the model right now», because at the moment an
    undo runs the model already equals the before-payload and that second
    question answers «nothing» while the scene still holds the geometry
    the step created.

    A payload has no Building object to walk, so the payload form of the
    model is used for both sides; the widening rules are the same.
    """
    import json

    if not isinstance(before_payload, dict) \
            or not isinstance(after_payload, dict):
        return None
    was = {str(e.get("id")): e
           for e in (before_payload.get("elements") or ())}
    now = {str(e.get("id")): e
           for e in (after_payload.get("elements") or ())}
    ids: set = set()

    def row_key(row):
        return (str(row.get("type")), str(row.get("story_id")),
                json.dumps(row.get("params") or {}, sort_keys=True,
                           ensure_ascii=False))

    stories_moved = _payload_story_rows_differ(before_payload, after_payload)
    for eid, row in now.items():
        old = was.get(eid)
        if old is None or row_key(old) != row_key(row):
            ids.add(eid)
            if str(row.get("type")) == "wall":
                ids.update(str(other.get("id"))
                           for other in now.values()
                           if str(other.get("story_id"))
                           == str(row.get("story_id")))
    ids.update(str(eid) for eid in was if eid not in now)   # removed
    if stories_moved:
        ids.update(now)
    # An opening's geometry is its HOST wall's business: a door that was
    # ADDED and is now removed (an undo) exists only in the before-payload
    # — the after side has no row to read the host from — so BOTH sides
    # are consulted, and the host is rebuilt either way.
    for row in (*now.values(), *was.values()):
        host = str((row.get("params") or {}).get("host_wall_id") or "")
        if row.get("id") and str(row.get("id")) in ids and host:
            ids.add(host)
    return ids


def _payload_story_rows_differ(before_payload, after_payload) -> bool:
    """Whether a storey row moved between two payloads."""
    import json

    was = {str(s.get("id")): s
           for s in (before_payload.get("stories") or ())}
    now = {str(s.get("id")): s
           for s in (after_payload.get("stories") or ())}
    if set(was) != set(now):
        return True
    return any(json.dumps(was[k], sort_keys=True, default=str)
               != json.dumps(now[k], sort_keys=True, default=str)
               for k in was)


def changed_element_ids(before_payload, building):
    """The ids whose rows differ between a stored payload and the model.

    A command keeps the payload as it stood before its step (what Undo
    restores), so «what did this step touch» is a diff of two dicts rather
    than a guess — the answer a targeted geometry rebuild needs.

    The diff is deliberately WIDER than «the rows that differ», because a
    building's geometry is not per-element:

    * an opening's body is cut out of the WALL, so a changed opening
      brings its host along;
    * a WALL's body is trimmed against every other wall it meets, so a
      changed wall brings its whole STOREY — the join at the corner is a
      property of the pair, and rebuilding one of them leaves the other
      showing last revision's mitre;
    * a changed STOREY row (elevation, height) moves everything on it, so
      it brings its own storey's elements too.

    ``None`` means «cannot tell»: the caller rebuilds everything.
    """
    import json

    if not isinstance(before_payload, dict):
        return None
    was = {str(e.get("id")): e
           for e in (before_payload.get("elements") or ())}
    ids: set = set()
    story_changed = _story_rows_differ(before_payload, building)

    def row_key(row):
        return (str(row.get("type")), str(row.get("story_id")),
                json.dumps(row.get("params") or {}, sort_keys=True,
                           ensure_ascii=False))

    for element in building.elements:
        eid = str(element.get("id"))
        old = was.pop(eid, None)
        if old is None or row_key(old) != row_key(element):
            ids.add(eid)
            if str(element.get("type")) == "wall":
                # A wall's geometry is its join with its neighbours.
                ids.update(str(other.get("id"))
                           for other in building.elements
                           if str(other.get("story_id"))
                           == str(element.get("story_id")))
    ids.update(was)                             # removed elements
    if story_changed:
        ids.update(str(e.get("id")) for e in building.elements)
    for element in building.elements:
        host = str((element.get("params") or {}).get("host_wall_id") or "")
        if host and host in ids:
            ids.add(str(element.get("id")))
    return ids


def _story_rows_differ(before_payload, building) -> bool:
    """Whether a storey's own row (elevation, height, name) moved.

    Storeys carry no geometry of their own, but every element on one is
    placed BY it: an elevation change moves the whole floor, and a diff
    that only compared elements would rebuild nothing at all.
    """
    import json

    was = {str(s.get("id")): s
           for s in (before_payload.get("stories") or ())}
    for story in building.stories:
        old = was.pop(str(story.get("id")), None)
        if old is None:
            return True
        if json.dumps(old, sort_keys=True, default=str) != \
                json.dumps(story, sort_keys=True, default=str):
            return True
    return bool(was)            # a storey was removed


def commit(history, command: BuildingEdit) -> None:
    """Run a building command through the host's history (one undo step)."""
    history.execute(command)
