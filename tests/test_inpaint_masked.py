"""Tests for mask-constrained erasing across bubble styles.

Every case builds a synthetic page plus the detector's text mask, so the tests
run without the model and stay fast.
"""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pytest

pytest.importorskip("numpy")
pil = pytest.importorskip("PIL")

from PIL import Image, ImageDraw  # noqa: E402

from mangatl.adapters.imaging import (  # noqa: E402
    ink_mask,
    label_components,
    otsu_threshold,
    structure_mask,
)
from mangatl.adapters.inpaint.masked import MaskedInpainter  # noqa: E402
from mangatl.domain.block import TextBlock  # noqa: E402

PAPER = (248, 248, 248)
INK = (15, 15, 15)


def glyph_rows(draw: ImageDraw.ImageDraw, box, rows: int = 3, height: int = 10) -> None:
    x1, y1, x2, _ = box
    for row in range(rows):
        top = y1 + row * (height + 6)
        x = x1
        while x < x2 - height:
            width = height * 2
            draw.rectangle((x, top, x + width, top + height), fill=INK)
            x += width + 6


def save(page, path: Path) -> np.ndarray:
    page.save(path)
    return np.array(page)


def erase(page_path: Path, destination: Path, mask: np.ndarray, box) -> np.ndarray:
    MaskedInpainter().erase(
        page_path,
        destination,
        [TextBlock(id=0, bbox=box)],
        mask=mask.astype(np.float32),
    )
    return np.array(Image.open(destination))


def test_otsu_and_ink_mask_separate_ink_from_paper() -> None:
    gray = np.full((20, 20), 250, dtype=np.uint8)
    gray[5:9, 5:9] = 10

    threshold = otsu_threshold(gray)
    mask = ink_mask(gray)

    assert 10 <= threshold <= 250
    assert mask[6, 6] and not mask[1, 1]


def test_label_components_counts_two_blobs() -> None:
    mask = np.zeros((12, 12), dtype=bool)
    mask[1:3, 1:3] = True
    mask[7:10, 6:11] = True

    _, stats = label_components(mask)

    assert len(stats) == 2
    assert sorted(item.area for item in stats) == [4, 15]


def test_structure_mask_keeps_loops_and_dashes() -> None:
    page = Image.new("L", (200, 200), 250)
    draw = ImageDraw.Draw(page)
    draw.ellipse((20, 20, 120, 120), outline=10, width=3)  # solid bubble
    for x in range(140, 190, 8):  # dashed rule
        draw.line((x, 150, x + 4, 150), fill=10, width=2)

    gray = np.array(page)
    ink = ink_mask(gray)
    labels, stats = label_components(ink)
    structure = structure_mask(labels, stats, text_mask=ink)

    assert structure[70, 20] or structure[21, 70]  # outline pixel
    assert structure[150, 141]  # dash pixel


def test_masked_erases_glyphs_but_keeps_solid_border(tmp_path: Path) -> None:
    page = Image.new("RGB", (200, 200), PAPER)
    draw = ImageDraw.Draw(page)
    draw.ellipse((30, 30, 170, 170), outline=INK, width=3)
    glyph_rows(draw, (55, 70, 145, 130))
    source = tmp_path / "solid.png"
    pixels = save(page, source)

    mask = (pixels.sum(axis=2) < 120).astype(np.float32)
    result = erase(source, tmp_path / "out.png", mask, (55, 70, 145, 130))

    assert int(result[100, 100].sum()) > 600  # glyph area cleared
    assert int(result[100, 30].sum()) < 120  # left border preserved


def test_masked_keeps_dashed_border_even_if_marked_as_text(tmp_path: Path) -> None:
    page = Image.new("RGB", (200, 200), PAPER)
    draw = ImageDraw.Draw(page)
    for x in range(40, 160, 12):  # dashed top and bottom
        draw.line((x, 40, x + 6, 40), fill=INK, width=3)
        draw.line((x, 160, x + 6, 160), fill=INK, width=3)
    glyph_rows(draw, (60, 80, 140, 120))
    source = tmp_path / "dash.png"
    pixels = save(page, source)

    mask = (pixels.sum(axis=2) < 120).astype(np.float32)  # includes the dashes
    result = erase(source, tmp_path / "out.png", mask, (60, 80, 140, 120))

    assert int(result[40, 42].sum()) < 120  # dash survived
    assert int(result[95, 100].sum()) > 600  # text erased


def test_masked_handles_nested_bubbles(tmp_path: Path) -> None:
    page = Image.new("RGB", (240, 240), PAPER)
    draw = ImageDraw.Draw(page)
    draw.ellipse((20, 20, 220, 220), outline=INK, width=3)  # outer
    draw.ellipse((70, 70, 170, 170), outline=INK, width=3)  # inner
    glyph_rows(draw, (85, 100, 155, 150))
    source = tmp_path / "nested.png"
    pixels = save(page, source)

    mask = (pixels.sum(axis=2) < 120).astype(np.float32)
    result = erase(source, tmp_path / "out.png", mask, (85, 100, 155, 150))

    assert int(result[120, 120].sum()) > 600  # inner text erased
    assert int(result[20, 120].sum()) < 120  # outer border kept
    assert int(result[70, 120].sum()) < 120  # inner border kept


def test_masked_works_without_any_bubble(tmp_path: Path) -> None:
    ramp = np.tile(np.arange(200, dtype=np.uint8)[None, :, None], (200, 1, 3))
    page = Image.fromarray(ramp, mode="RGB")
    ImageDraw.Draw(page).rectangle((60, 80, 140, 120), fill=INK)
    source = tmp_path / "text.png"
    pixels = save(page, source)

    mask = (pixels.sum(axis=2) < 120).astype(np.float32)
    result = erase(source, tmp_path / "out.png", mask, (60, 80, 140, 120))

    assert int(result[100, 100].sum()) > 300  # no black patch left
    assert abs(int(result[100, 100, 0]) - 100) < 40  # close to the ramp value
