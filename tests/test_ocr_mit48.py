"""Tests for the MIT48px line splitting (no model needed)."""

from __future__ import annotations

import numpy as np

from mangatl.adapters.ocr.mit48px import order_lines, split_lines


def page_with_blocks(boxes, size=(200, 200)) -> np.ndarray:
    canvas = np.full((size[1], size[0], 3), 255, dtype=np.uint8)
    for x1, y1, x2, y2 in boxes:
        canvas[y1:y2, x1:x2] = 0
    return canvas


def test_vertical_block_splits_into_columns() -> None:
    page = page_with_blocks([(10, 10, 40, 90), (60, 10, 90, 90)])

    lines = split_lines(page, (0, 0, 100, 100), vertical=True)

    assert lines == [(10, 0, 40, 100), (60, 0, 90, 100)]


def test_horizontal_block_splits_into_rows() -> None:
    page = page_with_blocks([(10, 10, 90, 40), (10, 60, 90, 90)])

    lines = split_lines(page, (0, 0, 100, 100), vertical=False)

    assert lines == [(0, 10, 100, 40), (0, 60, 100, 90)]


def test_blank_block_stays_whole() -> None:
    page = page_with_blocks([])

    assert split_lines(page, (0, 0, 100, 100), vertical=True) == [(0, 0, 100, 100)]


def test_vertical_lines_are_ordered_right_to_left() -> None:
    lines = [(0, 0, 10, 10), (50, 0, 60, 10), (20, 0, 30, 10)]

    assert order_lines(lines, vertical=True) == [(50, 0, 60, 10), (20, 0, 30, 10), (0, 0, 10, 10)]


def test_horizontal_lines_are_ordered_top_to_bottom() -> None:
    lines = [(0, 50, 10, 60), (0, 0, 10, 10)]

    assert order_lines(lines, vertical=False) == [(0, 0, 10, 10), (0, 50, 10, 60)]
