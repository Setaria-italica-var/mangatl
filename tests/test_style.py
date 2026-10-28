"""Tests for typography estimation from pixels."""

from __future__ import annotations

import numpy as np
import pytest

pytest.importorskip("numpy")

from mangatl.render.style import estimate_style  # noqa: E402

PAPER = 250
INK = 10


def draw_bars(
    page: np.ndarray,
    top: int,
    bottom: int,
    left: int,
    right: int,
    width: int,
    gap: int,
    value: int = INK,
) -> None:
    for x in range(left, right, width + gap):
        page[top:bottom, x : x + width] = value


def test_thin_strokes_are_regular_weight() -> None:
    page = np.full((100, 300, 3), PAPER, dtype=np.uint8)
    draw_bars(page, 30, 70, 60, 240, width=3, gap=18)

    style = estimate_style(page, None, (60, 30, 240, 70))

    assert style.weight == "regular"
    assert style.stroke_width < 6


def test_thick_strokes_are_bold() -> None:
    page = np.full((100, 300, 3), PAPER, dtype=np.uint8)
    draw_bars(page, 20, 80, 60, 240, width=12, gap=12)

    style = estimate_style(page, None, (60, 20, 240, 80))

    assert style.weight == "bold"
    assert style.stroke_width >= 10


def test_colours_come_from_ink_and_ring() -> None:
    page = np.full((120, 300, 3), PAPER, dtype=np.uint8)
    page[30:60, 100:200] = 10

    style = estimate_style(page, None, (80, 30, 220, 60))

    assert style.fg[0] < 40
    assert style.bg[0] > 220


def test_grey_ink_is_measured_not_assumed() -> None:
    page = np.full((60, 200, 3), PAPER, dtype=np.uint8)
    page[20:40, 50:150] = 120

    style = estimate_style(page, None, (50, 20, 150, 40))

    assert 100 <= style.fg[0] <= 140


def test_font_size_follows_line_count() -> None:
    page = np.full((140, 300, 3), PAPER, dtype=np.uint8)
    page[20:45, 60:240] = INK
    page[80:105, 60:240] = INK

    single = np.full((140, 300, 3), PAPER, dtype=np.uint8)
    single[20:105, 60:240] = INK

    two_lines = estimate_style(page, None, (60, 20, 240, 105))
    one_line = estimate_style(single, None, (60, 20, 240, 105))

    assert two_lines.font_size < one_line.font_size


def test_alignment_is_derived_from_margins() -> None:
    centred = np.full((60, 200, 3), PAPER, dtype=np.uint8)
    centred[20:40, 60:140] = INK
    left = np.full((60, 200, 3), PAPER, dtype=np.uint8)
    left[20:40, 10:80] = INK

    assert estimate_style(centred, None, (10, 20, 190, 40)).align == "center"
    assert estimate_style(left, None, (10, 20, 190, 40)).align == "left"


def test_mask_overrides_thresholding() -> None:
    page = np.full((60, 200, 3), PAPER, dtype=np.uint8)
    page[20:40, 50:150] = 160  # faint glyph, would be missed by a hard threshold
    mask = np.zeros((60, 200), dtype=bool)
    mask[20:40, 50:150] = True

    style = estimate_style(page, mask, (50, 20, 150, 40))

    assert 140 <= style.fg[0] <= 175
