"""Synthetic manga-like pages for pipeline smoke tests.

Real pages are copyrighted and bulky, so the spike ships a generator that draws
bubbles with glyph-like blocks. It is deliberately crude: the point is to exercise
detection, erasing and layout with known geometry, not to look like a comic.

>>> import tempfile, pathlib
>>> paths = generate(pathlib.Path(tempfile.mkdtemp()), pages=2)
>>> len(paths)
2
"""

from __future__ import annotations

import random
from pathlib import Path

from PIL import Image, ImageDraw

PAGE_SIZE = (800, 1200)
INK = (18, 18, 18)
PAPER = (248, 248, 248)


def _bubble(draw: ImageDraw.ImageDraw, box: tuple[int, int, int, int], fill) -> None:
    draw.ellipse(box, fill=fill, outline=INK, width=3)


def _horizontal_text(
    draw: ImageDraw.ImageDraw, box: tuple[int, int, int, int], rng: random.Random, glyph: int
) -> None:
    x1, y1, x2, y2 = box
    rows = max(1, (y2 - y1) // (glyph * 2))
    for row in range(rows):
        top = y1 + row * glyph * 2
        x = x1
        while x < x2 - glyph:
            width = glyph * rng.randint(1, 2)
            if x + width > x2:
                break
            draw.rectangle((x, top, x + width, top + glyph), fill=INK)
            x += width + glyph // 3


def _vertical_text(
    draw: ImageDraw.ImageDraw, box: tuple[int, int, int, int], rng: random.Random, glyph: int
) -> None:
    x1, y1, x2, y2 = box
    columns = max(1, (x2 - x1) // (glyph * 2))
    for column in range(columns):
        right = x2 - column * glyph * 2
        y = y1
        while y < y2 - glyph:
            height = glyph * rng.randint(1, 2)
            if y + height > y2:
                break
            draw.rectangle((right - glyph, y, right, y + height), fill=INK)
            y += height + glyph // 3


def _page(variant: int, rng: random.Random) -> Image.Image:
    width, height = PAGE_SIZE
    if variant == 2:
        gradient = Image.linear_gradient("L").resize((width, height))
        page = Image.merge("RGB", (gradient, gradient, gradient))
        page = page.point(lambda value: 160 + value // 4)
    else:
        page = Image.new("RGB", PAGE_SIZE, PAPER)
    draw = ImageDraw.Draw(page)

    glyph = rng.randint(14, 22)
    if variant == 0:  # two horizontal bubbles
        for box in ((60, 90, 420, 330), (380, 520, 740, 760)):
            fill = PAPER if variant != 2 else (250, 250, 250)
            _bubble(draw, box, fill)
            inner = (box[0] + 30, box[1] + 40, box[2] - 30, box[3] - 40)
            _horizontal_text(draw, inner, rng, glyph)
    elif variant == 1:  # one tall vertical bubble, right to left columns
        box = (430, 80, 720, 700)
        _bubble(draw, box, PAPER)
        inner = (box[0] + 40, box[1] + 40, box[2] - 40, box[3] - 40)
        _vertical_text(draw, inner, rng, glyph)
    else:  # gradient page with a light bubble, text over both
        box = (120, 200, 700, 520)
        _bubble(draw, box, (252, 252, 252))
        _horizontal_text(draw, (box[0] + 30, box[1] + 40, box[2] - 30, box[3] - 40), rng, glyph)
        _vertical_text(draw, (520, 620, 760, 1120), rng, glyph)
    return page


def generate(directory: Path, pages: int = 6, seed: int = 7) -> list[Path]:
    """Write ``pages`` synthetic PNGs into ``directory`` and return their paths."""
    directory = Path(directory)
    directory.mkdir(parents=True, exist_ok=True)
    rng = random.Random(seed)
    written: list[Path] = []
    for index in range(pages):
        page = _page(index % 3, rng)
        path = directory / f"{index + 1:03d}.png"
        page.save(path)
        written.append(path)
    return written
