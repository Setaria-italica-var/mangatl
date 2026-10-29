"""Writing-direction detection (pure numpy, no model)."""

from __future__ import annotations

import numpy as np

from mangatl.adapters.detectors.ctd import _is_vertical


def mask(width: int, height: int, boxes) -> np.ndarray:
    """Probability map with solid rectangles as "glyphs"."""
    canvas = np.zeros((height, width), dtype=np.float32)
    for x1, y1, x2, y2 in boxes:
        canvas[y1:y2, x1:x2] = 0.9
    return canvas


def test_two_columns_read_as_vertical() -> None:
    # Two glyph columns, one continuous vertical run: vertical Japanese.
    glyphs = [(10, 10, 30, 90), (40, 10, 60, 90)]
    probability = mask(100, 120, glyphs)

    assert _is_vertical((5, 5, 70, 110), probability) is True


def test_two_rows_read_as_horizontal() -> None:
    glyphs = [(10, 10, 90, 30), (10, 40, 90, 60)]
    probability = mask(120, 100, glyphs)

    assert _is_vertical((5, 5, 110, 70), probability) is False


def test_tall_single_block_falls_back_to_aspect() -> None:
    probability = mask(60, 200, [(20, 20, 40, 180)])

    assert _is_vertical((0, 0, 60, 200), probability) is True


def test_without_mask_uses_aspect() -> None:
    assert _is_vertical((0, 0, 40, 120), None) is True
    assert _is_vertical((0, 0, 120, 40), None) is False
