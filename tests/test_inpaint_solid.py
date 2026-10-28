"""Tests for the solid-bubble fast path (needs numpy + Pillow)."""

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
    is_solid,
    median_colour,
)
from mangatl.domain.block import TextBlock  # noqa: E402

WHITE = (250, 250, 250)


def make_page(path: Path, *, background=WHITE, text_box=(40, 40, 80, 80)) -> None:
    image = Image.new("RGB", (120, 120), background)
    drawer = ImageDraw.Draw(image)
    drawer.rectangle(text_box, fill=(10, 10, 10))
    image.save(path)


def test_is_solid_on_flat_background(tmp_path: Path) -> None:
    page = tmp_path / "flat.png"
    make_page(page)
    pixels = np.array(Image.open(page))
    assert is_solid(pixels, (40, 40, 80, 80), SolidFillConfig())


def test_is_solid_rejects_gradient(tmp_path: Path) -> None:
    page = tmp_path / "grad.png"
    ramp = np.tile(np.arange(120, dtype=np.uint8)[None, :, None], (120, 1, 3))
    Image.fromarray(ramp, mode="RGB").save(page)
    pixels = np.array(Image.open(page))
    assert not is_solid(pixels, (40, 40, 80, 80), SolidFillConfig())


def test_median_colour_is_background(tmp_path: Path) -> None:
    page = tmp_path / "flat.png"
    make_page(page)
    pixels = np.array(Image.open(page))
    colour = median_colour(pixels, (40, 40, 80, 80), SolidFillConfig())
    assert colour is not None
    assert tuple(int(value) for value in colour) == WHITE


def test_erase_fills_the_text_box(tmp_path: Path) -> None:
    source = tmp_path / "page.png"
    destination = tmp_path / "out" / "page.png"
    make_page(source)

    SolidFillInpainter().erase(source, destination, [TextBlock(id=0, bbox=(40, 40, 80, 80))])

    assert destination.is_file()
    result = np.array(Image.open(destination))
    assert tuple(int(value) for value in result[60, 60]) == WHITE


def test_erase_leaves_non_solid_blocks_untouched(tmp_path: Path) -> None:
    source = tmp_path / "grad.png"
    destination = tmp_path / "out" / "grad.png"
    ramp = np.tile(np.arange(120, dtype=np.uint8)[None, :, None], (120, 1, 3))
    Image.fromarray(ramp, mode="RGB").save(source)

    SolidFillInpainter().erase(source, destination, [TextBlock(id=0, bbox=(40, 40, 80, 80))])

    result = np.array(Image.open(destination))
    assert int(result[60, 60, 0]) == 60  # gradient preserved


def test_erase_keeps_alpha_channel(tmp_path: Path) -> None:
    source = tmp_path / "rgba.png"
    destination = tmp_path / "out" / "rgba.png"
    image = Image.new("RGBA", (120, 120), (*WHITE, 255))
    ImageDraw.Draw(image).rectangle((40, 40, 80, 80), fill=(10, 10, 10, 255))
    image.save(source)

    SolidFillInpainter().erase(source, destination, [TextBlock(id=0, bbox=(40, 40, 80, 80))])

    result = np.array(Image.open(destination))
    assert result.shape[2] == 4
    assert int(result[60, 60, 3]) == 255
