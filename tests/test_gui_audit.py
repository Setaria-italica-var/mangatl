"""Behavioural audit: undo, view isolation, transforms and page switching.

These tests are deliberately scenario-shaped (user actions, then assertions) because
the recent bugs were all about state leaking between features rather than about a
single function being wrong.
"""

from __future__ import annotations

import json
import os
import random
import shutil
import uuid
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ.setdefault(
    "MANGATL_RECENT",
    str(Path(__file__).resolve().parents[1] / ".tmp" / "audit-recent.json"),
)

import pytest

pytest.importorskip("PySide6")

from PySide6.QtCore import QPoint, Qt
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication

from mangatl.adapters.inpaint.masked import MaskedInpainter
from mangatl.gui.main_window import MainWindow

SAMPLE = Path(__file__).resolve().parents[1] / "samples" / "vol1"


@pytest.fixture(scope="module")
def app():
    return QApplication.instance() or QApplication([])


@pytest.fixture
def window(app):
    destination = (
        Path(__file__).resolve().parents[1] / ".tmp" / f"audit-{uuid.uuid4().hex[:8]}"
    )
    shutil.copytree(SAMPLE, destination)
    window = MainWindow(destination)
    window.editor.inpainter = MaskedInpainter()  # avoid the slow LaMa load in tests
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


def _block(window, block_id=0):
    return next(b for b in window.editor.page.blocks if b.id == block_id)


def _rect_drag(window, start: QPoint, end: QPoint) -> None:
    QTest.mousePress(window.canvas.viewport(), Qt.MouseButton.LeftButton, pos=start)
    QTest.mouseMove(window.canvas.viewport(), end)
    QTest.mouseRelease(window.canvas.viewport(), Qt.MouseButton.LeftButton, pos=end)
    QApplication.processEvents()


# -- undo ------------------------------------------------------------------
def test_undo_lifo_for_text_edits(window):
    block = _block(window)
    original = block.translation
    window.on_block_edited(block.id, block.text, "first", "dialogue")
    window.on_block_edited(block.id, block.text, "second", "dialogue")
    window.undo()
    assert _block(window).translation == "first"
    window.undo()
    assert _block(window).translation == original
    window.undo()  # empty stack must not raise
    assert _block(window).translation == original


def test_undo_geometry_uses_the_active_view(window):
    block = _block(window)
    window.show_view("result")
    original_box = block.text_bbox or block.bbox

    _rect_drag(
        window,
        window.canvas.mapFromScene(
            (original_box[0] + original_box[2]) / 2,
            (original_box[1] + original_box[3]) / 2,
        ),
        window.canvas.mapFromScene(
            (original_box[0] + original_box[2]) / 2 + 18,
            (original_box[1] + original_box[3]) / 2 + 12,
        ),
    )
    moved = _block(window).text_bbox
    assert moved != original_box

    window.undo()

    restored = _block(window)
    assert (restored.text_bbox or restored.bbox) == original_box
    assert restored.bbox == block.bbox  # detection box never moved


def test_undo_rotation_and_style(window):
    block = _block(window)
    original_style = dict(block.style)
    original_translation = block.translation
    window.on_block_applied(
        block.id, block.text, "styled", "sfx", {"font_size": 22, "fg": "#ff0000"}
    )
    assert _block(window).style["font_size"] == 22

    window.undo()

    restored = _block(window)
    assert restored.style == original_style
    assert restored.translation == original_translation


def test_undo_never_deletes_page_images(window):
    erased = window.editor.erased_path
    result = window.editor.result_path
    before = {path: path.read_bytes() for path in (erased, result) if path.is_file()}
    window.on_block_edited(0, "t", "翻", "dialogue")

    window.undo()

    for path, payload in before.items():
        assert path.is_file()
        assert path.read_bytes() == payload


# -- views -----------------------------------------------------------------
def test_views_expose_the_right_interactions(window):
    window.show_view("source")
    assert window.canvas._overlay_mode == "blocks"
    assert window.canvas._region_enabled is True

    window.show_view("erased")
    assert window.canvas._overlay_mode == "diff"
    assert window.canvas._overlay_items == {}
    assert window.canvas._region_enabled is True

    window.show_view("result")
    assert window.canvas._overlay_mode == "text"
    assert window.canvas._region_enabled is False


def test_region_tools_are_ignored_in_result_view(window):
    window.show_view("result")
    window.region = None

    _rect_drag(window, QPoint(300, 250), QPoint(420, 350))

    assert window.region is None
    assert window.selection_bar.isVisible() is False


def test_switching_page_clears_region_but_keeps_view(window):
    window.show_view("erased")
    window.region = [(10, 10), (60, 10), (60, 60), (10, 60)]
    window.load_page(1)
    assert window.region is None
    assert window.view_mode == "erased"


# -- blocks ----------------------------------------------------------------
def test_added_block_is_dialogue_and_renders(window):
    window.region = [(120, 1400), (420, 1400), (420, 1490), (120, 1490)]
    window.add_region_block()
    block = window.editor.page.blocks[-1]
    assert block.role == "dialogue"
    window.on_block_applied(block.id, "", "新增译文", "dialogue", {})
    window.editor.rerender()
    assert block.translation == "新增译文"


def test_delete_selected_renumbers_ids(window):
    window.selected_ids = [0, 1]
    window.delete_selected()
    blocks = window.editor.page.blocks
    assert [b.id for b in blocks] == list(range(len(blocks)))


def test_block_table_edit_updates_project(window):
    window.on_block_edited(0, "表原文", "表译文", "")
    with open(window.project.directory / "project.json", encoding="utf-8") as handle:
        data = json.load(handle)
    blocks = data["pages"]["001.jpg"]["blocks"]
    target = next(b for b in blocks if b["id"] == 0)
    assert target["text"] == "表原文"
    assert target["translation"] == "表译文"


# -- renderer --------------------------------------------------------------
def test_locked_size_survives_a_box_change(window):
    block = _block(window)
    block.style = {"font_size": 26}
    window.editor.rerender()
    assert block.rendered_size == 26

    box = block.bbox
    window.editor.set_text_bbox(block, (box[0], box[1], box[0] + 40, box[1] + 40))
    window.editor.rerender()

    assert block.rendered_size == 26


def test_text_frame_does_not_move_detection_box(window):
    block = _block(window)
    original = block.bbox
    window.editor.set_text_bbox(
        block, (original[0] + 15, original[1] + 15, original[2] + 15, original[3] + 15)
    )
    window.editor.rerender()
    assert block.bbox == original
    assert block.text_bbox is not None


def test_undo_cancels_a_pending_auto_render(window):
    block = _block(window)
    window.on_block_edited(block.id, block.text, "pending", "dialogue")
    assert window._preview_timer.isActive()

    window.undo()

    assert not window._preview_timer.isActive()
    assert _block(window).translation != "pending"


def test_undo_added_block_removes_it(window):
    count = len(window.editor.page.blocks)
    window.region = [(120, 1400), (420, 1400), (420, 1490), (120, 1490)]
    window.add_region_block()
    assert len(window.editor.page.blocks) == count + 1

    window.undo()

    assert len(window.editor.page.blocks) == count


def test_undo_delete_restores_blocks(window):
    count = len(window.editor.page.blocks)
    window.select_block(0)
    window.delete_selected()
    assert len(window.editor.page.blocks) == count - 1

    window.undo()

    assert len(window.editor.page.blocks) == count


def test_result_view_falls_back_when_image_missing(window):
    window.editor.result_path.unlink(missing_ok=True)
    window.show_view("result")
    assert window.view_mode == "source"


def test_rubber_band_selects_and_subtracts(window):
    total = len(window.editor.page.blocks)
    window.show_view("source")
    window.canvas.select_ids([])
    _rect_drag(window, QPoint(2, 2), QPoint(1190, 790))
    assert len(window.selected_ids) == total

    block = window.editor.page.blocks[0]
    x1, y1, x2, y2 = block.bbox
    start = window.canvas.mapFromScene(x1 - 4, y1 - 4)
    end = window.canvas.mapFromScene(x2 + 4, y2 + 4)
    QTest.mousePress(
        window.canvas.viewport(), Qt.MouseButton.RightButton, pos=start
    )
    QTest.mouseMove(window.canvas.viewport(), end)
    QTest.mouseRelease(
        window.canvas.viewport(), Qt.MouseButton.RightButton, pos=end
    )
    QApplication.processEvents()

    assert block.id not in window.selected_ids


def test_escape_clears_region(window):
    window.region = [(10, 10), (80, 10), (80, 80), (10, 80)]
    window.canvas._show_selection(window.region)
    assert window.selection_bar.isVisible()

    QTest.keyClick(window.canvas, Qt.Key.Key_Escape)
    QApplication.processEvents()

    assert window.canvas.selection_points == []
    assert window.selection_bar.isVisible() is False


def test_preview_shortcuts_switch_views(window):
    QTest.keyClick(window, Qt.Key.Key_1, Qt.KeyboardModifier.ControlModifier)
    assert window.view_mode == "source"
    QTest.keyClick(window, Qt.Key.Key_2, Qt.KeyboardModifier.ControlModifier)
    assert window.view_mode in {"erased", "source"}
    QTest.keyClick(window, Qt.Key.Key_3, Qt.KeyboardModifier.ControlModifier)
    assert window.view_mode in {"result", "source"}


# -- robustness ------------------------------------------------------------
def test_invalid_image_keeps_previous_page(window):
    window.canvas.show_image("does-not-exist.png")
    assert window.canvas._pixmap_item is not None


@pytest.mark.parametrize("seed", [1, 2, 7, 13])
def test_random_actions_keep_project_consistent(window, seed):
    rng = random.Random(seed)
    for _ in range(40):
        action = rng.choice(["move", "rotate", "text", "undo", "view", "page", "select"])
        try:
            if action == "move" and window.editor.page.blocks:
                block = rng.choice(window.editor.page.blocks)
                box = block.text_bbox or block.bbox
                delta = [rng.randint(-5, 5) for _ in range(4)]
                window.on_geometry_changed(
                    block.id,
                    tuple(box[i] + delta[i] for i in range(4)),
                )
            elif action == "rotate" and window.editor.page.blocks:
                block = rng.choice(window.editor.page.blocks)
                window.on_block_rotated(block.id, rng.uniform(-45, 45))
            elif action == "text" and window.editor.page.blocks:
                block = rng.choice(window.editor.page.blocks)
                window.on_block_edited(block.id, block.text, f"t{rng.randint(0, 9)}", "dialogue")
            elif action == "undo":
                window.undo()
            elif action == "view":
                window.show_view(rng.choice(["source", "erased", "result"]))
            elif action == "page":
                window.load_page(rng.randrange(len(window.project)))
            elif action == "select" and window.editor.page.blocks:
                window.select_block(rng.choice(window.editor.page.blocks).id)
        except Exception as exc:  # noqa: BLE001 - the point is to surface them
            pytest.fail(f"action {action} raised {exc!r}")

    data = json.loads((window.project.directory / "project.json").read_text(encoding="utf-8"))
    for page in data["pages"].values():
        ids = [b["id"] for b in page.get("blocks", [])]
        assert ids == list(range(len(ids)))
