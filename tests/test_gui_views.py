"""View separation: blocks select in source/result, regions in erased only."""

from __future__ import annotations

import os
import shutil
import uuid
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest

pytest.importorskip("PySide6")

from PySide6.QtCore import QPoint, Qt
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication

from mangatl.gui.main_window import MainWindow

SAMPLE = Path(__file__).resolve().parents[1] / "samples" / "vol1"


@pytest.fixture(scope="module")
def app():
    return QApplication.instance() or QApplication([])


@pytest.fixture
def window(app):
    destination = (
        Path(__file__).resolve().parents[1] / ".tmp" / f"views-{uuid.uuid4().hex[:8]}"
    )
    shutil.copytree(SAMPLE, destination)
    window = MainWindow(destination)
    window.resize(1200, 800)
    window.show()
    app.processEvents()
    window.canvas.fit()
    app.processEvents()
    yield window
    window.close()
    window.deleteLater()
    app.processEvents()
    shutil.rmtree(destination, ignore_errors=True)


def _draw_rect(window, start: QPoint, end: QPoint) -> None:
    window._set_mode("rect")
    QTest.mousePress(window.canvas.viewport(), Qt.MouseButton.LeftButton, pos=start)
    QTest.mouseMove(window.canvas.viewport(), end)
    QTest.mouseRelease(window.canvas.viewport(), Qt.MouseButton.LeftButton, pos=end)
    window.parent()


def test_source_view_allows_blocks_and_region(window):
    assert window.canvas._overlay_mode == "blocks"
    assert window.canvas._region_enabled is True
    assert len(window.canvas._overlay_items) == len(window.editor.page.blocks)


def test_erased_view_hides_blocks_and_keeps_region(window):
    window.show_view("erased")

    assert window.canvas._overlay_mode == "diff"
    assert window.canvas._overlay_items == {}
    assert window.canvas._region_enabled is True


def test_result_view_disables_region_tool(window):
    window.show_view("result")
    window.region = None

    _draw_rect(window, QPoint(300, 250), QPoint(420, 350))

    assert window.canvas._overlay_mode == "text"
    assert window.canvas._region_enabled is False
    assert window.region is None
    assert window.selection_bar.isVisible() is False


def test_result_view_shows_a_frame_for_every_block(window):
    window.show_view("result")
    if window.view_mode != "result":
        pytest.skip("page has no result image")

    assert len(window.canvas._overlay_items) == len(window.editor.page.blocks)


def test_undo_removes_a_newly_created_inpainted_page(window):
    window._snapshot(images=("inpainted", "result"))
    path = window.editor.erased_path
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(b"fake")

    window.undo()

    assert not path.exists()


def test_undo_restores_previous_inpainted_bytes(window):
    path = window.editor.erased_path
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(b"before")
    window._snapshot(images=("inpainted",))
    path.write_bytes(b"after")

    window.undo()

    assert path.read_bytes() == b"before"


def test_region_action_keeps_block_selection(window):
    window.select_block(0)
    window.region = [(0, 0), (10, 0), (10, 10), (0, 10)]

    window._finish_selection_action()

    assert window.region is None
    assert window.selected_ids == [0]
    assert window.selection_bar.isVisible() is False
