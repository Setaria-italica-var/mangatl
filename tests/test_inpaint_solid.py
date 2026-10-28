"""Tests for the solid-bubble fast path (needs numpy + Pillow).

``TextBlock.bbox`` is half-open (``x2``/``y2`` exclusive), so the fixtures draw
the glyph area as ``(x1, y1, x2 - 1, y2 - 1)`` to keep the ring free of glyph
pixels unless a test wants them there.
"""

from __future__ import annotations

from pathlib import Path

import pytest

pytest.importorskip("numpy")
pytest.importorskip("PIL")

import numpy as np  # noqa: E402
from PIL import Image, ImageDraw  # noqa: E402

from mangatl.adapters.inpaint.solid import (  # noqa: E402
    SolidFillConfig,
    SolidFillInpainter,
    background_mad,
    is_solid,
    median_colour,
)
from mangatl.domain.block import TextBlock  # noqa: E402

WHITE = (250, 250, 250)
TEXT_BOX = (40, 40, 80, 80)


def make_page(path: Path, *, background=WHITE, box=TEXT_BOX, outline=None) -> None:
    """White page with one dark glyph box (half-open coordinates)."""
    image = Image.new("RGB", (120, 120), background)
    drawer = ImageDraw.Draw(image)
    x1, y1, x2, y2 = box
    drawer.rectangle((x1, y1, x2 - 1, y2 - 1), fill=(10, 10, 10))
    if outline is not None:
        ox1, oy1, ox2, oy2 = outline
        drawer.rectangle((ox1, oy1, ox2 - 1, oy2 - 1), outline=(10, 10, 10), width=1)
    image.save(path)


def test_is_solid_on_flat_background(tmp_path: Path) -> None:
    page = tmp_path / "flat.png"
    make_page(page)
    pixels = np.array(Image.open(page))
    assert background_mad(pixels, TEXT_BOX, SolidFillConfig()) == 0.0
    assert is_solid(pixels, TEXT_BOX, SolidFillConfig())


def test_is_solid_tolerates_a_thin_outline(tmp_path: Path) -> None:
    page = tmp_path / "outline.png"
    make_page(page, outline=(34, 34, 86, 86))
    pixels = np.array(Image.open(page))
    assert is_solid(pixels, TEXT_BOX, SolidFillConfig())


def test_is_solid_rejects_gradient(tmp_path: Path) -> None:
    page = tmp_path / "grad.png"
    ramp = np.tile(np.arange(120, dtype=np.uint8)[None, :, None], (120, 1, 3))
    Image.fromarray(ramp, mode="RGB").save(page)
    pixels = np.array(Image.open(page))
    assert not is_solid(pixels, TEXT_BOX, SolidFillConfig())


def test_median_colour_is_background(tmp_path: Path) -> None:
    page = tmp_path / "flat.png"
    make_page(page)
    pixels = np.array(Image.open(page))
    colour = median_colour(pixels, TEXT_BOX, SolidFillConfig())
    assert colour is not None
    assert tuple(int(value) for value in colour) == WHITE


def test_erase_fills_the_text_box(tmp_path: Path) -> None:
    source = tmp_path / "page.png"
    destination = tmp_path / "out" / "page.png"
    make_page(source)

    SolidFillInpainter().erase(source, destination, [TextBlock(id=0, bbox=TEXT_BOX)])

    assert destination.is_file()
    result = np.array(Image.open(destination))
    assert tuple(int(value) for value in result[60, 60]) == WHITE


def test_erase_leaves_non_solid_blocks_untouched(tmp_path: Path) -> None:
    source = tmp_path / "grad.png"
    destination = tmp_path / "out" / "grad.png"
    ramp = np.tile(np.arange(120, dtype=np.uint8)[None, :, None], (120, 1, 3))
    Image.fromarray(ramp, mode="RGB").save(source)

    SolidFillInpainter().erase(source, destination, [TextBlock(id=0, bbox=TEXT_BOX)])

    result = np.array(Image.open(destination))
    assert int(result[60, 60, 0]) == 60  # gradient preserved


def test_erase_keeps_alpha_channel(tmp_path: Path) -> None:
    source = tmp_path / "rgba.png"
    destination = tmp_path / "out" / "rgba.png"
    image = Image.new("RGBA", (120, 120), (*WHITE, 255))
    ImageDraw.Draw(image).rectangle((40, 40, 79, 79), fill=(10, 10, 10, 255))
    image.save(source)

    SolidFillInpainter().erase(source, destination, [TextBlock(id=0, bbox=TEXT_BOX)])

    result = np.array(Image.open(destination))
    assert result.shape[2] == 4
    assert tuple(int(value) for value in result[60, 60, :3]) == WHITE
    assert int(result[60, 60, 3]) == 255
