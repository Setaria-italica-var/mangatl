"""Tests for the diffusion fill and the composite inpainter."""

from __future__ import annotations

from pathlib import Path

import pytest

pytest.importorskip("numpy")
pytest.importorskip("PIL")

import numpy as np  # noqa: E402
from PIL import Image, ImageDraw  # noqa: E402

from mangatl.adapters.inpaint.auto import AutoInpainter  # noqa: E402
from mangatl.adapters.inpaint.diffusion import (  # noqa: E402
    DiffusionConfig,
    build_mask,
    diffuse,
)
from mangatl.domain.block import TextBlock  # noqa: E402

WHITE = (250, 250, 250)


def gradient_page(path: Path, size: int = 120) -> None:
    ramp = np.tile(np.arange(size, dtype=np.uint8)[None, :, None], (size, 1, 3))
    Image.fromarray(ramp, mode="RGB").save(path)


def glyph_page(path: Path, box: tuple[int, int, int, int]) -> None:
    image = Image.new("RGB", (120, 120), WHITE)
    x1, y1, x2, y2 = box
    ImageDraw.Draw(image).rectangle((x1, y1, x2 - 1, y2 - 1), fill=(10, 10, 10))
    image.save(path)


def test_build_mask_covers_expanded_bbox() -> None:
    mask = build_mask((20, 20), [TextBlock(id=0, bbox=(5, 5, 10, 10))], expand=2)
    assert mask[5, 5] and mask[11, 11] is not None
    assert mask[3, 3]  # expanded by 2
    assert not mask[0, 0]


def test_diffuse_keeps_flat_colour() -> None:
    pixels = np.full((30, 30, 3), 200, dtype=np.uint8)
    mask = np.zeros((30, 30), dtype=bool)
    mask[10:20, 10:20] = True
    result = diffuse(pixels, mask, iterations=32)
    assert int(result[15, 15, 0]) == 200


def test_diffuse_follows_gradient(tmp_path: Path) -> None:
    page = tmp_path / "grad.png"
    gradient_page(page)
    pixels = np.array(Image.open(page))
    mask = np.zeros(pixels.shape[:2], dtype=bool)
    mask[55:65, 55:65] = True

    result = diffuse(pixels, mask, iterations=256)

    centre = int(result[60, 60, 0])
    assert 52 <= centre <= 68, centre  # original was 60, ramp stays linear


def test_diffuse_large_hole_reaches_background_colour() -> None:
    """A 120 px hole must not stay grey: the pyramid does the long-range work."""
    pixels = np.full((200, 200, 3), 250, dtype=np.uint8)
    pixels[40:160, 40:160] = 10
    mask = np.zeros((200, 200), dtype=bool)
    mask[40:160, 40:160] = True

    result = diffuse(pixels, mask, iterations=64)

    assert int(result[100, 100, 0]) >= 200


def test_diffusion_inpainter_writes_alpha(tmp_path: Path) -> None:
    source = tmp_path / "rgba.png"
    destination = tmp_path / "out" / "rgba.png"
    image = Image.new("RGBA", (60, 60), (*WHITE, 255))
    ImageDraw.Draw(image).rectangle((20, 20, 39, 39), fill=(10, 10, 10, 255))
    image.save(source)

    from mangatl.adapters.inpaint.diffusion import DiffusionInpainter

    DiffusionInpainter().erase(source, destination, [TextBlock(id=0, bbox=(20, 20, 40, 40))])

    result = np.array(Image.open(destination))
    assert result.shape[2] == 4
    assert int(result[30, 30, 3]) == 255
    assert int(result[30, 30, 0]) > 200


def test_auto_uses_exact_colour_on_flat_background(tmp_path: Path) -> None:
    source = tmp_path / "flat.png"
    destination = tmp_path / "out" / "flat.png"
    glyph_page(source, (40, 40, 80, 80))

    AutoInpainter().erase(source, destination, [TextBlock(id=0, bbox=(40, 40, 80, 80))])

    result = np.array(Image.open(destination))
    assert tuple(int(value) for value in result[60, 60]) == WHITE


def test_auto_falls_back_to_diffusion_on_gradient(tmp_path: Path) -> None:
    source = tmp_path / "grad.png"
    destination = tmp_path / "out" / "grad.png"
    gradient_page(source)

    AutoInpainter(diffusion=DiffusionConfig(iterations=256)).erase(
        source, destination, [TextBlock(id=0, bbox=(55, 55, 65, 65))]
    )

    result = np.array(Image.open(destination))
    centre = int(result[60, 60, 0])
    assert 45 <= centre <= 75, centre  # neither original black nor a flat fill
