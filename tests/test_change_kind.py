# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Marco Sumari Tellez and IngeTrazo contributors.
"""Đổi Loại — an element becoming another kind, without losing itself.

«A slab I drew too thick is really a foundation; that wall was meant to be
a glazed run» is an ordinary gesture, and doing it by deleting and
redrawing throws away everything the element carried: where it stands, its
name, what it is made of. What these tests hold down is that the
conversion KEEPS what the two schemas share, that it is one undo step, and
that a conversion the builder cannot make is refused in words rather than
producing an element that will not build.
"""
import sys

import pytest  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

if QApplication.instance() is None:
    QApplication(sys.argv[:1])


@pytest.fixture()
def window():
    from views.main_window import MainWindow

    win = MainWindow()
    yield win
    win.hide()


def _house(window):
    from core.building import samples as _samples
    from core.building.model import building_of

    _samples.build_sample(window.viewport.history, window.viewport.scene,
                          "townhouse")
    return building_of(window.viewport.scene)


def _element(window, element_id) -> dict:
    from core.building.model import building_of

    return building_of(window.viewport.scene).element(element_id)


def test_a_conversion_keeps_what_the_two_schemas_share(window):
    """The name, the material and the position are the element's IDENTITY:
    a conversion that dropped them would be a delete and a redraw."""
    from core.building import commands as _commands
    from core.building.scene_sync import sync

    building = _house(window)
    slab = next(e for e in building.elements if e.get("type") == "slab")
    window.viewport.history.execute(_commands.set_params(
        str(slab["id"]), {"name": "Sàn tầng 1",
                          "building_material_id": "btct"}))

    command = _commands.change_kind(str(slab["id"]), "ceiling")
    command._rebuild = lambda s, b: sync(s, b)
    window.viewport.history.execute(command)

    after = _element(window, slab["id"])
    assert after["type"] == "ceiling"
    assert after["params"]["name"] == "Sàn tầng 1", \
        "đổi loại làm mất tên cấu kiện"
    assert after["params"]["building_material_id"] == "btct", \
        "đổi loại làm mất vật liệu"


def test_a_conversion_is_one_undo_step(window):
    from core.building import commands as _commands
    from core.building.scene_sync import sync

    building = _house(window)
    slab = next(e for e in building.elements if e.get("type") == "slab")
    before = str(slab["type"])

    command = _commands.change_kind(str(slab["id"]), "column")
    command._rebuild = lambda s, b: sync(s, b)
    window.viewport.history.execute(command)
    assert _element(window, slab["id"])["type"] == "column"

    window.viewport.history.undo()
    assert _element(window, slab["id"])["type"] == before
    window.viewport.history.redo()
    assert _element(window, slab["id"])["type"] == "column"


def test_the_geometry_is_rebuilt_for_the_new_kind(window):
    """A relabelled element with the old kind's geometry is the one thing
    this must never be: the drawings and the schedule read the mesh."""
    from core.building import commands as _commands
    from core.building.scene_sync import sync, group_for

    building = _house(window)
    slab = next(e for e in building.elements if e.get("type") == "slab")

    def corners():
        """The geometry's own outline. A face COUNT would call a slab and a
        column identical — both are six faces — and pass whatever happened,
        so the positions are what is compared."""
        mesh = group_for(window.viewport.scene, slab["id"]).mesh
        return sorted((round(float(v.position.x()), 4),
                       round(float(v.position.y()), 4),
                       round(float(v.position.z()), 4))
                      for v in mesh.vertices)

    before = corners()
    command = _commands.change_kind(str(slab["id"]), "column")
    command._rebuild = lambda s, b: sync(s, b)
    window.viewport.history.execute(command)

    assert corners() != before, "hình học chưa dựng lại theo loại mới"


def test_a_hosted_type_is_refused_with_the_way_to_do_it(window):
    """A door cannot exist outside a wall. Offering that conversion
    produces an element the builder refuses, which reads to the user as a
    broken model — so it is refused, in words, with the gesture that
    works."""
    from core.building import commands as _commands
    from core.building.scene_sync import sync
    from core.history import CommandRejected

    building = _house(window)
    wall = next(e for e in building.elements if e.get("type") == "wall")

    command = _commands.change_kind(str(wall["id"]), "curtain_wall")
    command._rebuild = lambda s, b: sync(s, b)
    window.viewport.history.execute(command)

    history = window.viewport.history
    assert history.last_rejected, history.last_error
    assert "tường chủ" in history.last_rejected
    # A refusal is a NO-OP, not a failure: nothing on the stack, nothing
    # logged, and the element is exactly as it was.
    assert history.last_error is None
    after = _element(window, wall["id"])
    assert after["type"] == "wall"
    assert after["params"]["building_material_id"], "mất vật liệu sau lời từ chối"


def test_the_menu_offers_only_what_can_be_made(window):
    """An entry that cannot work must not be shown — the list is the
    schemas minus the hosted types, which need a host this element has
    not got."""
    from PySide6.QtWidgets import QMenu

    from core.building import elements as _schemas
    from core.building.scene_sync import TR_NAMES

    building = _house(window)
    wall = next(e for e in building.elements if e.get("type") == "wall")
    host = QMenu()
    menu = window._bim_change_kind_menu(host, wall, [wall])
    labels = {action.text() for action in menu.actions()}

    assert tr_label("wall") not in labels, "đề nghị đổi thành chính nó"
    for hosted in ("door", "window", "curtain_wall"):
        assert tr_label(hosted) not in labels, hosted
    assert tr_label("column") in labels and tr_label("slab") in labels


def tr_label(kind: str) -> str:
    from core.building.scene_sync import TR_NAMES
    from core.i18n import tr

    return tr(TR_NAMES.get(kind, kind))
