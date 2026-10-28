"""Solid-bubble fast path: fill each text block with its surrounding colour.

Manga dialogue usually sits on a flat white bubble, so the expensive inpainting
model is only needed for the rest. This adapter handles the flat case with a
median colour taken from a ring around the block, and refuses to guess when the
ring is not uniform (:func:`is_solid`).

The result is intentionally conservative: a wrong fill is worse than leaving the
glyphs for the model, so :class:`SolidFillInpainter` only fills blocks whose
surroundings pass the variance check and leaves the others untouched.

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
    max_std: float = 12.0


def _clip_bbox(
    bbox: tuple[int, int, int, int], width: int, height: int
) -> tuple[int, int, int, int]:
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

    >>> np = __import__("numpy")
    >>> canvas = np.zeros((30, 30, 3), dtype=np.uint8)
    >>> ring_pixels(canvas, (10, 10, 20, 20), ring=3).shape[1]
    3
    """
    height, width = pixels.shape[:2]
    x1, y1, x2, y2 = _clip_bbox(bbox, width, height)
    if x2 <= x1 or y2 <= y1:
        return None

    ox1, oy1 = max(0, x1 - ring), max(0, y1 - ring)
    ox2, oy2 = min(width, x2 + ring), min(height, y2 + ring)
    outer = pixels[oy1:oy2, ox1:ox2]
    mask = np.ones(outer.shape[:2], dtype=bool)
    mask[y1 - oy1 : y2 - oy1, x1 - ox1 : x2 - ox1] = False
    selected = outer[mask]
    return selected if selected.size else None


def is_solid(pixels: np.ndarray, bbox: tuple[int, int, int, int], config: SolidFillConfig) -> bool:
    """Return whether the ring around ``bbox`` is a flat colour."""
    ring = ring_pixels(pixels, bbox, ring=config.ring)
    if ring is None:
        return False
    return bool(float(ring.std(axis=0).max()) <= config.max_std)


def median_colour(pixels: np.ndarray, bbox: tuple[int, int, int, int], config: SolidFillConfig):
    """Return the median ring colour as ``uint8`` per channel, or ``None``."""
    ring = ring_pixels(pixels, bbox, ring=config.ring)
    if ring is None:
        return None
    return np.median(ring, axis=0).astype(np.uint8)


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
    ) -> None:
        """Write ``destination`` with every solid-background block filled."""
        with Image.open(image_path) as handle:
            image = handle.convert("RGBA" if "A" in handle.getbands() else "RGB")
        pixels = np.array(image)
        out = pixels.copy()

        for block in blocks:
            if not is_solid(pixels, block.bbox, self.config):
                continue
            colour = median_colour(pixels, block.bbox, self.config)
            if colour is None:
                continue
            height, width = out.shape[:2]
            x1, y1, x2, y2 = _clip_bbox(block.bbox, width, height)
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
