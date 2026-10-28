"""Estimate the typography of a text block from its pixels.

OCR only returns text, so everything the typesetter needs — colour, size, weight,
slant, alignment — has to be measured back from the image. This module does that
with numpy only, and is deliberately honest about what it cannot know:

* **colour, size, weight, alignment**: measured, reliable;
* **category** (sans / serif): inferred from stroke-width variation, right most of
  the time on clean lettering, unreliable on handwriting;
* **font family**: never guessed here. Only a category is produced; mapping it to
  a real font happens at render time from the bundled fonts.

>>> import numpy as np
>>> page = np.full((80, 200, 3), 250, dtype=np.uint8)
>>> page[30:50, 40:160] = 10
>>> style = estimate_style(page, None, (40, 30, 160, 50))
>>> style.weight, style.category
('regular', 'sans')
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np

from mangatl.adapters.inpaint.solid import clip_bbox, ring_pixels


@dataclass(frozen=True)
class TextStyle:
    """What the renderer needs to reproduce a block's look."""

    fg: tuple[int, int, int]
    bg: tuple[int, int, int]
    font_size: float
    stroke_width: float
    weight: str
    category: str
    italic: bool
    align: str

    def as_dict(self) -> dict:
        """JSON-ready form (used by the project file)."""
        return {
            "fg": list(self.fg),
            "bg": list(self.bg),
            "font_size": round(self.font_size, 1),
            "stroke_width": round(self.stroke_width, 2),
            "weight": self.weight,
            "category": self.category,
            "italic": self.italic,
            "align": self.align,
        }


def _runs(row: np.ndarray) -> list[int]:
    """Lengths of consecutive ``True`` runs in one row/column."""
    padded = np.concatenate(([False], row, [False]))
    changed = np.diff(padded.astype(np.int8))
    starts = np.flatnonzero(changed == 1)
    ends = np.flatnonzero(changed == -1)
    return [int(end - start) for start, end in zip(starts, ends, strict=True)]


def _line_count(mask: np.ndarray) -> int:
    """Number of text rows, from empty horizontal bands inside the box."""
    rows = mask.any(axis=1)
    if not rows.any():
        return 1
    bands = 0
    previous = False
    for value in rows:
        if value and not previous:
            bands += 1
        previous = bool(value)
    return max(1, bands)


def _slant(mask: np.ndarray) -> float:
    """Least-squares slope of the per-row centroid (positive = leaning right)."""
    ys: list[int] = []
    xs: list[float] = []
    for y in range(mask.shape[0]):
        columns = np.flatnonzero(mask[y])
        if columns.size:
            ys.append(y)
            xs.append(float(columns.mean()))
    if len(ys) < 4:
        return 0.0
    slope, _ = np.polyfit(np.array(ys, dtype=np.float32), np.array(xs, dtype=np.float32), 1)
    return float(slope)


def _category(mask: np.ndarray) -> str:
    """Guess serif vs sans from how much stroke width varies across the block."""
    widths: list[int] = []
    for y in range(mask.shape[0]):
        widths.extend(_runs(mask[y]))
    widths = [width for width in widths if width >= 2]
    if len(widths) < 8:
        return "sans"
    variation = float(np.std(widths) / max(1.0, np.mean(widths)))
    return "serif" if variation > 0.55 else "sans"


def _align(mask: np.ndarray) -> str:
    """Compare the left and right margins of the ink inside the box."""
    columns = np.flatnonzero(mask.any(axis=0))
    if columns.size == 0:
        return "center"
    left = columns.min()
    right = mask.shape[1] - 1 - columns.max()
    width = mask.shape[1]
    if abs(int(left) - int(right)) <= max(2, width * 0.08):
        return "center"
    return "left" if left < right else "right"


def estimate_style(
    pixels: np.ndarray,
    mask: np.ndarray | None,
    bbox: tuple[int, int, int, int],
    *,
    vertical: bool = False,
) -> TextStyle:
    """Measure colour, size, weight, slant and alignment for one block."""
    height, width = pixels.shape[:2]
    x1, y1, x2, y2 = clip_bbox(bbox, width, height)
    crop = pixels[y1:y2, x1:x2, :3]
    if crop.size == 0:
        return TextStyle((0, 0, 0), (255, 255, 255), 12.0, 1.0, "regular", "sans", False, "center")

    ring = ring_pixels(pixels, (x1, y1, x2, y2), ring=6)
    if ring is None:
        bg = tuple(int(value) for value in np.median(crop.reshape(-1, 3), axis=0))
    else:
        bg = tuple(int(value) for value in np.median(ring[:, :3], axis=0))

    if mask is not None:
        mask_array = np.asarray(mask)
        if mask_array.dtype == bool:
            region = mask_array[y1:y2, x1:x2]
        else:
            # Detector masks arrive as probabilities; anything above 0.5 is ink.
            region = mask_array[y1:y2, x1:x2] > 0.5
    else:
        # Split ink from paper using the ring colour, not the crop's own range:
        # a crop that is entirely glyph would otherwise have min == max.
        luminance = np.asarray(crop.mean(axis=2))
        background = float(np.mean(bg))
        threshold = (float(luminance.min()) + background) / 2.0
        region = luminance < threshold
        if not region.any():
            region = luminance < background - 10

    if not region.any():
        return TextStyle((0, 0, 0), (255, 255, 255), 12.0, 1.0, "regular", "sans", False, "center")

    # A detector mask can bleed onto paper, so the foreground colour is taken
    # from the darkest 40% of the masked pixels instead of all of them.
    masked = crop[region]
    luminance = masked.mean(axis=1)
    cutoff = float(np.percentile(luminance, 40))
    ink = masked[luminance <= cutoff]
    fg = tuple(int(value) for value in np.median(ink, axis=0))

    horizontal_runs = [
        width_size
        for y in range(region.shape[0])
        for width_size in _runs(region[y])
        if width_size >= 2
    ]
    vertical_runs = [
        height_size
        for x in range(region.shape[1])
        for height_size in _runs(region[:, x])
        if height_size >= 2
    ]
    # A glyph stroke crosses both directions, so the smaller median is the stroke
    # width; the larger one is the character height/width.
    medians = [float(np.median(values)) for values in (horizontal_runs, vertical_runs) if values]
    stroke_width = min(medians) if medians else 1.0

    lines = _line_count(region)
    box_height = y2 - y1
    box_width = x2 - x1
    font_size = float(box_width if vertical else box_height) / max(1, lines)
    if vertical:
        columns = max(1, box_width // max(1, int(font_size)))
        font_size = float(box_height) / max(1, columns) if columns > 1 else font_size

    ratio = stroke_width / max(1.0, font_size)
    weight = "bold" if ratio >= 0.11 else "regular"
    italic = abs(_slant(region)) > 0.18

    return TextStyle(
        fg=fg,
        bg=bg,
        font_size=font_size,
        stroke_width=stroke_width,
        weight=weight,
        category=_category(region),
        italic=italic,
        align=_align(region),
    )
