# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Marco Sumari Tellez and IngeTrazo contributors.
"""Office: the drawing office's own folder, shared over the network.

An office does not work alone and does not work identically: two people at
two machines must issue the same sheet with the same pens and the same
title block, and a new colleague must not have to be told any of it. This
is that folder — one path, set once per installation (or left at the
default), holding what the office decided ONCE and wants everywhere:

* ``office.json`` — the defaults every new document starts from: the
  project data that goes into the title block, the pen table, the layer
  names, the hatch of each material.
* ``bang-vat-lieu.json`` — the office's own material list, over the
  standard one.
* ``chi-tiet.json`` — the office's own detail library (the build-ups it
  actually builds).
* ``mau/`` — sample documents (``.igz``) the «Dựng nhanh 3D» menu offers.

Nothing here is required: with no office folder the standard tables are
used and the app behaves exactly as it did. The point of the folder is
that the tables can be AGREED once and then be the same on every machine,
which is the difference between a tool and the office's tool.

Reading is deliberately forgiving: a file the folder does not have, or a
file somebody broke, is reported and skipped rather than raised. An office
folder that stopped the app would be worse than no office folder.
"""
from __future__ import annotations

import json
from pathlib import Path

#: The file names inside the office folder. Vietnamese, because this is an
#: office's own directory and it is read by people, not only by us.
CONFIG_NAME = "office.json"
MATERIALS_NAME = "bang-vat-lieu.json"
DETAILS_NAME = "chi-tiet.json"
SAMPLES_DIR = "mau"

#: The settings key an installation remembers its folder in.
SETTING_KEY = "office/path"


class Office:
    """A readable view of one office folder.

    The folder is remembered per installation, so a document opened on
    Monday reads the same tables it read on Friday without the user
    typing the path again.
    """

    def __init__(self, path: str | Path | None = None) -> None:
        self.path: Path | None = Path(path) if path else None

    # ---- where it is -----------------------------------------------------
    @classmethod
    def from_settings(cls) -> "Office":
        """The office folder this installation is set to, or the default."""
        from PySide6.QtCore import QSettings

        remembered = str(QSettings().value(SETTING_KEY, "") or "")
        return cls(remembered or default_path())

    @staticmethod
    def remember(path: str | Path | None) -> None:
        """Set (or clear) the folder this installation uses."""
        from PySide6.QtCore import QSettings

        store = QSettings()
        store.setValue(SETTING_KEY, str(path or ""))
        store.sync()

    # ---- what it holds ---------------------------------------------------
    def exists(self) -> bool:
        return bool(self.path and self.path.is_dir())

    def _read(self, name: str):
        """One JSON file of the folder, or ``None`` (never raises)."""
        if not self.path:
            return None
        target = self.path / name
        try:
            if not target.is_file():
                return None
            return json.loads(target.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return None

    def config(self) -> dict:
        """The office's defaults: project data, pens, layer names."""
        data = self._read(CONFIG_NAME)
        return dict(data) if isinstance(data, dict) else {}

    def materials(self) -> dict:
        """The office's own material table, if it keeps one."""
        data = self._read(MATERIALS_NAME)
        return dict(data) if isinstance(data, dict) else {}

    def details(self) -> dict:
        """The office's own detail library."""
        data = self._read(DETAILS_NAME)
        return dict(data) if isinstance(data, dict) else {}

    def samples(self) -> list:
        """``[(name, Path), …]`` — the office's own sample documents."""
        if not self.path:
            return []
        folder = self.path / SAMPLES_DIR
        if not folder.is_dir():
            return []
        out: list = []
        for item in sorted(folder.glob("*.igz")):
            out.append((item.stem.replace("_", " "), item))
        return out

    # ---- what it hands out -----------------------------------------------
    def project_defaults(self) -> dict:
        """The project data a new document starts with.

        What goes into the title block: the office's own name, the person
        who chairs the drawings, the designer. A new document with these
        filled in is one nobody has to remember to fill in later.
        """
        config = self.config()
        project = config.get("project")
        return dict(project) if isinstance(project, dict) else {}

    def apply_to(self, scene) -> dict:
        """Stamp the office's defaults onto ``scene``. Returns what was set.

        Called when a document is NEW, never when one is opened: an office
        that changes its pen table must not silently restyle last year's
        drawings, which are a record of what was issued.
        """
        applied: dict = {}
        config = self.config()
        details = self.details()
        if not config and not details:
            return applied
        from core.building import pens as _pens
        from core.building.model import building_of

        project = self.project_defaults()
        if project:
            building = building_of(scene)
            for key, value in project.items():
                building.project.setdefault(str(key), value)
            applied["project"] = sorted(project)

        pens = config.get("pens")
        if isinstance(pens, dict) and pens:
            table = _pens.pens(scene)
            for key, value in pens.items():
                if key in _pens.PENS and isinstance(value, (list, tuple)):
                    table[str(key)] = tuple(value)
            applied["pens"] = sorted(pens)

        renames = config.get("layer_renames")
        if isinstance(renames, dict) and renames:
            table = _pens.renames(scene)
            table.update({str(k): str(v) for k, v in renames.items()})
            applied["layer_renames"] = sorted(renames)

        if details:
            overrides = _detail_store(scene)
            for key, record in details.items():
                if isinstance(record, dict):
                    overrides[str(key)] = record
            applied["details"] = sorted(details)
        return applied

    # ---- writing it back -------------------------------------------------
    def write_tables(self, *, project: dict | None = None,
                     pens: dict | None = None, renames: dict | None = None,
                     details: dict | None = None) -> Path:
        """Write the office's tables. Returns the folder written to.

        Only the sections passed are touched, so an office can set its
        pen table without overwriting the title-block data somebody else
        wrote into the same file.
        """
        if not self.path:
            raise ValueError("Chưa chọn thư mục văn phòng.")
        self.path.mkdir(parents=True, exist_ok=True)
        config = self.config()
        if project is not None:
            config["project"] = dict(project)
        if pens is not None:
            config["pens"] = {str(k): list(v) if isinstance(v, tuple) else v
                              for k, v in pens.items()}
        if renames is not None:
            config["layer_renames"] = {str(k): str(v)
                                       for k, v in renames.items()}
        (self.path / CONFIG_NAME).write_text(
            json.dumps(config, ensure_ascii=False, indent=2, sort_keys=True),
            encoding="utf-8")
        if details is not None:
            (self.path / DETAILS_NAME).write_text(
                json.dumps(details, ensure_ascii=False, indent=2,
                           sort_keys=True), encoding="utf-8")
        return self.path


def _detail_store(scene) -> dict:
    from core.building.detail_lib import overrides as _overrides

    return _overrides(scene)


def default_path() -> Path:
    """Where an office folder lives when nobody has chosen one.

    Beside the user's data rather than inside the install folder: on
    Windows the installer lands in Program Files, which a user cannot
    write to, and an office folder that cannot be written is a folder
    nobody keeps. An office that shares one over the network points at it
    with :meth:`Office.remember`.
    """
    from core.paths import user_log_dir

    return user_log_dir().parent / "Office"


def state() -> dict:
    """A one-call summary for the UI: where, and whether it holds anything."""
    office = Office.from_settings()
    return {
        "path": str(office.path) if office.path else "",
        "exists": office.exists(),
        "samples": len(office.samples()),
        "has_project": bool(office.project_defaults()),
        "has_pens": bool(office.config().get("pens")),
        "has_details": bool(office.details()),
    }
