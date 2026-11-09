# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Marco Sumari Tellez and IngeTrazo contributors.
"""The building model — parameters are the truth, geometry is a cache.

A :class:`Building` holds every structured element of a document: its stories
(levels), its elements (walls, openings, slabs…), and the derived data the
drawings and the takeoff read. It is plain data — nested dicts and lists — so
it round-trips through ``.igz`` untouched and can be diffed, tested and sent
to a language model without a schema compiler in the way.

Design rules, carried over from how a BIM model has to behave:

* **Parameters, never measurements.** A wall knows ``thickness_mm`` and its
  baseline; the solid is rebuilt from those. Editing the parameter and
  rebuilding is the only way geometry changes — nothing is ever inferred back
  out of the mesh.
* **Absolute coordinates.** Element geometry is built in world coordinates,
  so the scene graph needs no transform bookkeeping for it.
* **One rebuild, whole storey.** Changing a wall's thickness rebuilds its
  joins and every opening it owns, in one operation — the caller never has
  to know which neighbours care.

Units: every stored length is **millimetres**, every angle degrees, and the
scene works in metres — conversion happens at the geometry boundary only.
"""
from __future__ import annotations

import uuid

#: The ``scene.plugin_data`` key this model lives under.
DATA_KEY = "building"

#: Bumped when the stored shape changes; :meth:`Building.from_dict` upgrades.
SCHEMA_VERSION = 1


def new_id(prefix: str = "el") -> str:
    """A fresh, stable element id (stable across saves, unique in document)."""
    return f"{prefix}-{uuid.uuid4().hex[:12]}"


class Building:
    """The structured model of one document.

    ``stories`` and ``elements`` are ordered: insertion order is meaningful
    (stories are kept sorted by elevation, elements by creation) and it is
    what the plan/drawing generators walk.
    """

    def __init__(self) -> None:
        #: ``[{id, name, z_mm, height_mm, ...}]`` — elevation of each storey.
        self.stories: list[dict] = []
        #: ``[{id, type, story_id, params: {...}, ...}]`` — the elements.
        self.elements: list[dict] = []
        #: Free-form project data (name, address, designer…) for title blocks.
        self.project: dict = {}
        #: Saved view rules (view specs) the drawing generators use.
        self.views: list[dict] = []
        #: Sheet set metadata beyond ``scene.compositions`` (book numbering).
        self.sheets: dict = {}
        #: Named settings of the feature (working units, active story…).
        self.settings: dict = {}

    # ---- storeys ---------------------------------------------------------
    def add_story(self, name: str, z_mm: float = 0.0,
                  height_mm: float = 3300.0, **extra) -> dict:
        """Add a storey and keep the list sorted by elevation."""
        row = {"id": new_id("story"), "name": name, "z_mm": float(z_mm),
               "height_mm": float(height_mm)}
        row.update(extra)
        self.stories.append(row)
        self.sort_stories()
        return row

    def sort_stories(self) -> None:
        self.stories.sort(key=lambda s: float(s.get("z_mm", 0.0)))

    def story(self, story_id: str) -> dict | None:
        """The storey row with this id, or ``None``.

        The comparison is tolerant on purpose: a row without an ``id``
        (a hand-edited payload, an import that carried none) must not take
        every drawing and every sheet down with a ``KeyError`` — it simply
        matches nothing.
        """
        return next((s for s in self.stories
                     if str(s.get("id") or "") == str(story_id)), None)

    def story_above(self, story_id: str) -> dict | None:
        """The next storey up — what ``top_link == "next"`` binds a wall to."""
        row = self.story(story_id)
        if row is None:
            return None
        z = float(row.get("z_mm", 0.0))
        ups = [s for s in self.stories if float(s.get("z_mm", 0.0)) > z + 1e-6]
        return min(ups, key=lambda s: float(s.get("z_mm", 0.0))) if ups else None

    def active_story(self) -> dict | None:
        """The storey tools draw into (``settings["active_story"]`` or first)."""
        sid = self.settings.get("active_story")
        return self.story(sid) if sid else (self.stories[0] if self.stories else None)

    def set_active_story(self, story_id: str) -> None:
        self.settings["active_story"] = str(story_id)

    # ---- elements --------------------------------------------------------
    def add_element(self, kind: str, story_id: str, params: dict) -> dict:
        """Append an element of ``kind`` on a storey, with its parameters."""
        row = {"id": new_id(kind or "el"), "type": str(kind),
               "story_id": story_id, "params": dict(params)}
        self.elements.append(row)
        return row

    def element(self, element_id: str) -> dict | None:
        return next((e for e in self.elements if e["id"] == element_id), None)

    def of_type(self, kind: str) -> list[dict]:
        return [e for e in self.elements if e.get("type") == kind]

    def on_story(self, story_id: str, kind: str | None = None) -> list[dict]:
        return [e for e in self.elements
                if e.get("story_id") == story_id
                and (kind is None or e.get("type") == kind)]

    def remove_element(self, element_id: str) -> dict | None:
        row = self.element(element_id)
        if row is not None:
            self.elements.remove(row)
        return row

    # ---- serialization ---------------------------------------------------
    def to_dict(self) -> dict:
        return {
            "version": SCHEMA_VERSION,
            "stories": [dict(s) for s in self.stories],
            "elements": [{"id": e["id"], "type": e["type"],
                          "story_id": e["story_id"],
                          "params": dict(e.get("params") or {}),
                          **{k: v for k, v in e.items()
                             if k not in ("id", "type", "story_id", "params")}}
                         for e in self.elements],
            "project": dict(self.project),
            "views": [dict(v) for v in self.views],
            "sheets": dict(self.sheets),
            "settings": dict(self.settings),
        }

    @classmethod
    def from_dict(cls, raw) -> "Building":
        """Read a stored building back — tolerant of older/partial payloads."""
        b = cls()
        if not isinstance(raw, dict):
            return b
        b.stories = [dict(s) for s in raw.get("stories") or []
                     if isinstance(s, dict) and s.get("id")]
        b.elements = [dict(e) for e in raw.get("elements") or []
                      if isinstance(e, dict) and e.get("id")
                      and e.get("type")]
        b.project = dict(raw.get("project") or {})
        b.views = [dict(v) for v in raw.get("views") or []]
        b.sheets = dict(raw.get("sheets") or {})
        b.settings = dict(raw.get("settings") or {})
        b.sort_stories()
        return b

    def is_empty(self) -> bool:
        return not self.stories and not self.elements


def building_of(scene) -> Building:
    """The building of ``scene``, made once and kept in ``scene.plugin_data``.

    The object is memoised per scene *by identity*, so callers can hold it —
    it is the live model, not a copy.
    """
    cache = getattr(scene, "_building_cache", None)
    if cache is None or cache[0] is not scene:
        data = (getattr(scene, "plugin_data", None) or {}).get(DATA_KEY)
        cache = (scene, Building.from_dict(data))
        scene._building_cache = cache
    return cache[1]


def drop_cache(scene) -> None:
    """Forget the memoised building of ``scene``.

    The cache is keyed by the scene's IDENTITY, but its contents come from
    ``scene.plugin_data`` — which a LOAD replaces wholesale. Opening a
    document into a scene that had already been asked for its building
    (a panel, a dock, a signal firing during startup) therefore kept
    serving the EMPTY model built before the load: the walls came back and
    the storeys did not. Whoever swaps ``plugin_data`` drops it here, so
    the next reader rebuilds from what is actually in the document.
    """
    if hasattr(scene, "_building_cache"):
        del scene._building_cache


def store(scene, building: Building | None = None) -> None:
    """Write the building back into ``scene.plugin_data`` (the save path)."""
    if building is None:
        cache = getattr(scene, "_building_cache", None)
        if cache is None or cache[0] is not scene:
            return
        building = cache[1]
    payload = building.to_dict()
    scene.plugin_data[DATA_KEY] = payload
    scene.plugin_data["building_rev"] = int(
        scene.plugin_data.get("building_rev", 0)) + 1
