"""Renderer smoke tests (skipped when the machine has no CJK font)."""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pytest

pytest.importorskip("numpy")
pytest.importorskip("PIL")

from PIL import Image  # noqa: E402

from mangatl.domain.block import TextBlock  # noqa: E402
from mangatl.render import fonts  # noqa: E402
from mangatl.render.renderer import PageRenderer  # noqa: E402

pytestmark = pytest.mark.skipif(fonts.resolve("sans") is None, reason="no CJK font installed")

BACKGROUND = 250


def blank_page(path: Path, size=(400, 300)) -> None:
    Image.new("RGB", size, (BACKGROUND, BACKGROUND, BACKGROUND)).save(path)


def ink_ratio(pixels: np.ndarray, box) -> float:
    x1, y1, x2, y2 = box
    region = pixels[y1:y2, x1:x2]
    dark = (region.mean(axis=2) < 200).mean()
    return float(dark)


def test_renders_translation_inside_the_box(tmp_path: Path) -> None:
    source = tmp_path / "page.png"
    destination = tmp_path / "result.png"
    blank_page(source)
    block = TextBlock(
        id=0,
        bbox=(50, 50, 350, 150),
        translation="自动排版测试：这是一句中文台词。",
        role="dialogue",
    )

    PageRenderer().render(source, [block], destination)

    pixels = np.array(Image.open(destination))
    assert ink_ratio(pixels, block.bbox) > 0.02  # text was drawn
    assert ink_ratio(pixels, (0, 200, 400, 300)) == 0.0  # nothing outside


def test_vertical_block_draws_a_column(tmp_path: Path) -> None:
    source = tmp_path / "page.png"
    destination = tmp_path / "result.png"
    blank_page(source)
    block = TextBlock(
        id=0, bbox=(80, 40, 220, 260), translation="竖排测试", role="dialogue", vertical=True
    )

    PageRenderer().render(source, [block], destination)

    pixels = np.array(Image.open(destination))
    assert ink_ratio(pixels, block.bbox) > 0.01


def test_texture_blocks_are_not_drawn(tmp_path: Path) -> None:
    source = tmp_path / "page.png"
    destination = tmp_path / "result.png"
    blank_page(source)
    block = TextBlock(
        id=0, bbox=(50, 50, 350, 150), translation="不应出现", role="texture"
    )

    PageRenderer().render(source, [block], destination)

    pixels = np.array(Image.open(destination))
    assert ink_ratio(pixels, block.bbox) == 0.0


def test_long_text_shrinks_and_flags_review(tmp_path: Path) -> None:
    source = tmp_path / "page.png"
    destination = tmp_path / "result.png"
    blank_page(source, size=(300, 200))
    block = TextBlock(
        id=0,
        bbox=(20, 20, 120, 80),
        translation="非常非常非常长的一段台词，放不下的时候应该缩小字号而不是截断文字。",
        role="dialogue",
    )

    PageRenderer().render(source, [block], destination)

    pixels = np.array(Image.open(destination))
    assert ink_ratio(pixels, block.bbox) > 0.02
