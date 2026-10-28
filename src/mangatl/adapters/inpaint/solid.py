"""Solid-bubble fast path: fill each text block with its surrounding colour.

Manga dialogue usually sits on a flat white bubble, so the expensive inpainting
model is only needed for the rest. This adapter handles the flat case with a
median colour taken from a ring around the block, and refuses to guess when the
ring is not uniform.

The flatness test uses the **median absolute deviation** rather than the standard
deviation: a bubble outline or a stray hair touching the ring is a small
minority there, so it barely moves the MAD, while a gradient or a textured
background does. A wrong fill is worse than leaving the glyphs for the model, so
anything that is not clearly flat is skipped.

>>> np = __import__("numpy")
>>> is_solid(np.full((40, 40, 3), 250, dtype=np.uint8), (10, 10, 20, 20))
True
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path

import numpy as np
from PIL import Image

from mangatl.domain.block import TextBlock


@dataclass(frozen=True)
class SolidFillConfig:
    """Tuning knobs for the fast path."""

    expand: int = 2
    ring: int = 6
    mad_tolerance: float = 12.0
    min_ring_pixels: int = 8


def clip_bbox(
    bbox: tuple[int, int, int, int], width: int, height: int
) -> tuple[int, int, int, int]:
    """Clamp a half-open ``(x1, y1, x2, y2)`` box to the image.

    >>> clip_bbox((-5, 10, 500, 20), 100, 60)
    (0, 10, 100, 20)
    """
    x1, y1, x2, y2 = bbox
    return (
        max(0, min(x1, width)),
        max(0, min(y1, height)),
        max(0, min(x2, width)),
        max(0, min(y2, height)),
    )


def ring_pixels(
    pixels: np.ndarray,
    bbox: tuple[int, int, int, int],
    ring: int = 6,
) -> np.ndarray | None:
    """Return the pixels in a ring around ``bbox`` as ``(N, C)``, or ``None``.

    The block itself is excluded (``bbox`` is half-open), so the result describes
    the surroundings rather than the glyphs.

    >>> np = __import__("numpy")
    >>> ring_pixels(np.zeros((30, 30, 3), dtype=np.uint8), (10, 10, 20, 20), 3).shape[1]
    3
    """
    height, width = pixels.shape[:2]
    x1, y1, x2, y2 = clip_bbox(bbox, width, height)
    if x2 <= x1 or y2 <= y1:
        return None

    ox1, oy1 = max(0, x1 - ring), max(0, y1 - ring)
    ox2, oy2 = min(width, x2 + ring), min(height, y2 + ring)
    outer = pixels[oy1:oy2, ox1:ox2]
    mask = np.ones(outer.shape[:2], dtype=bool)
    mask[y1 - oy1 : y2 - oy1, x1 - ox1 : x2 - ox1] = False
    selected = outer[mask]
    return selected if selected.size else None


def background_mad(
    pixels: np.ndarray,
    bbox: tuple[int, int, int, int],
    config: SolidFillConfig,
) -> float:
    """Median absolute deviation of the surrounding ring (max over channels)."""
    ring = ring_pixels(pixels, bbox, ring=config.ring)
    if ring is None:
        return float("inf")
    rgb = ring[:, :3].astype(np.int16)
    median = np.median(rgb, axis=0)
    deviation = np.abs(rgb - median.astype(np.int16))
    return float(np.median(deviation))


def is_solid(pixels: np.ndarray, bbox: tuple[int, int, int, int], config: SolidFillConfig) -> bool:
    """Return whether the ring around ``bbox`` is flat enough to overwrite."""
    ring = ring_pixels(pixels, bbox, ring=config.ring)
    if ring is None or len(ring) < config.min_ring_pixels:
        return False
    return background_mad(pixels, bbox, config) <= config.mad_tolerance


def median_colour(
    pixels: np.ndarray,
    bbox: tuple[int, int, int, int],
    config: SolidFillConfig,
) -> np.ndarray | None:
    """Return the median ring colour as three ``uint8`` values, or ``None``.

    Alpha is ignored on purpose: the page keeps its own alpha channel.
    """
    ring = ring_pixels(pixels, bbox, ring=config.ring)
    if ring is None:
        return None
    return np.median(ring[:, :3], axis=0).astype(np.uint8)


class SolidFillInpainter:
    """Fill flat-background blocks with their surrounding colour."""

    name = "solid"

    def __init__(self, config: SolidFillConfig | None = None) -> None:
        self.config = config or SolidFillConfig()

    def erase(
        self,
        image_path: Path,
        destination: Path,
        blocks: Sequence[TextBlock] = (),
        mask=None,
    ) -> None:
        """Write ``destination`` with every solid-background block filled."""
        with Image.open(image_path) as handle:
            image = handle.convert("RGBA" if "A" in handle.getbands() else "RGB")
        pixels = np.array(image)
        out = pixels.copy()
        height, width = out.shape[:2]

        for block in blocks:
            if not is_solid(pixels, block.bbox, self.config):
                continue
            colour = median_colour(pixels, block.bbox, self.config)
            if colour is None:
                continue
            x1, y1, x2, y2 = clip_bbox(block.bbox, width, height)
            x1 = max(0, x1 - self.config.expand)
            y1 = max(0, y1 - self.config.expand)
            x2 = min(width, x2 + self.config.expand)
            y2 = min(height, y2 + self.config.expand)
            if x2 <= x1 or y2 <= y1:
                continue
            out[y1:y2, x1:x2, :3] = colour

        destination.parent.mkdir(parents=True, exist_ok=True)
        mode = "RGBA" if out.shape[2] == 4 else "RGB"
        Image.fromarray(out, mode=mode).save(destination)
