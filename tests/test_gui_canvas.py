"""Canvas regression tests (offscreen Qt)."""

from __future__ import annotations

import os
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest

pytest.importorskip("PySide6")

from PIL import Image
from PySide6.QtWidgets import QApplication

from mangatl.domain.block import TextBlock
from mangatl.gui.canvas import PageCanvas


@pytest.fixture(scope="module")
def app():
    return QApplication.instance() or QApplication([])


def test_redraw_after_scene_clear_keeps_working(app):
    # Use a workspace scratch path: the system temp dir is ACL-restricted here.
    scratch = Path(__file__).resolve().parents[1] / ".tmp"
    scratch.mkdir(exist_ok=True)
    image = scratch / "canvas_test.png"
    Image.new("RGB", (120, 160), "white").save(image)
    canvas = PageCanvas()
    block = TextBlock(id=1, bbox=(10, 10, 60, 60))

    canvas.show_image(image)
    canvas.set_blocks([block], [1])
    assert len(canvas._handle_items) == 9

    # show_image() clears the scene, invalidating the handle wrappers; the next
    # redraw must not raise "Internal C++ object already deleted".
    canvas.show_image(image)
    canvas.set_blocks([block], [1])

    assert len(canvas._overlay_items) == 1
    assert len(canvas._handle_items) == 9
