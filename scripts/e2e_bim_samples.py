# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Marco Sumari Tellez and IngeTrazo contributors.
"""One command, three sample buildings, done end to end.

The preset tests prove each model's numbers. This drives the thing a user
actually does — open the app, ask for a sample, then use what came out:
clean the document between samples (the guard question must not appear on
an empty one), export the takeoff, issue a drawing, save and reopen.

Run: ``python scripts/e2e_bim_samples.py``
"""
from __future__ import annotations

import os
import sys
import tempfile
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from PySide6.QtWidgets import QApplication  # noqa: E402

app = QApplication.instance() or QApplication(sys.argv[:1])

from core.building import samples as S  # noqa: E402
from core.building.drawings import story_box, view_for  # noqa: E402
from core.building.model import building_of  # noqa: E402
from core.building.takeoff import tables  # noqa: E402
from formats.igz import load_into, save_scene  # noqa: E402
from views.main_window import MainWindow  # noqa: E402


def main() -> int:
    out = Path(tempfile.mkdtemp(prefix="bim-samples-"))
    win = MainWindow()
    win.show()
    app.processEvents()
    failures = 0

    for key in S.keys():
        try:
            win._on_new()                       # a clean document, no question
            app.processEvents()
            assert not win.viewport.scene.mesh.faces, "tài liệu mới còn hình"
            win._on_build_sample(key)
            app.processEvents()
            scene = win.viewport.scene
            building = building_of(scene)
            t = tables(building)
            story = building.stories[0]
            view = view_for(building, {"kind": "story", "story_id": story["id"]})
            box = story_box(building, story)
            doc = out / f"{key}.igz"
            save_scene(scene, doc)
            back_scene = __import__("core.scene", fromlist=["Scene"]).Scene()
            load_into(back_scene, doc)
            back = building_of(back_scene)
            print(f"  ✓ {key}: {len(building.stories)} tầng · "
                  f"{len(building.elements)} cấu kiện · "
                  f"{len(scene.groups)} nhóm · {len(t['walls'])} dòng tường · "
                  f"{t['totals']['wall_volume_m3']} m³ · "
                  f"mặt bằng {view.scale_denom:.0f} · "
                  f"box {box[2] - box[0]:.0f}×{box[3] - box[1]:.0f} mm · "
                  f"lưu/mở lại {len(back.elements)} cấu kiện")
            assert len(back.elements) == len(building.elements), "mất cấu kiện khi lưu"
        except Exception as exc:                # noqa: BLE001 — reported
            failures += 1
            print(f"  ✗ {key}: {type(exc).__name__}: {exc}")

    print(("ĐẠT" if not failures else f"HỎNG ({failures})") + f" — file trong {out}")
    win.hide()
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
