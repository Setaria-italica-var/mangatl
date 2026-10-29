"""Mask-constrained erasing: remove glyphs, keep every line the page owns.

The earlier adapters erased whole block boxes, so a bubble border that happened
to fall inside the box lost a chunk of itself. This adapter fills only the pixels
the detector marked as text, minus anything that looks like structure:

* solid bubble outlines and **dashed** bubbles (both are thin, long components);
* **nested** bubbles - the inner outline is structure too, so it survives while
  the text inside it is erased;
* pages with **no bubble at all** - the text mask is just the glyphs, and the
  surrounding artwork is diffused in, never replaced by a flat colour.

Flat backgrounds still take the cheap median-colour path; textured ones fall back
to the pyramid diffusion from :mod:`mangatl.adapters.inpaint.diffusion`.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path

import numpy as np
from PIL import Image

from mangatl.adapters.imaging import ink_mask, label_components, structure_mask
from mangatl.adapters.inpaint.diffusion import DiffusionConfig, diffuse
from mangatl.adapters.inpaint.solid import (
    SolidFillConfig,
    clip_bbox,
    is_solid,
    median_colour,
)
from mangatl.domain.block import TextBlock


@dataclass(frozen=True)
class MaskedConfig:
    """Tuning knobs for mask-constrained erasing."""

    text_threshold: float = 0.45
    grow: int = 1
    structure_dilate: int = 1
    diffusion: DiffusionConfig = DiffusionConfig(expand=0, iterations=64)
    solid: SolidFillConfig = SolidFillConfig()


def dilate(mask: np.ndarray, radius: int = 1) -> np.ndarray:
    """Grow a boolean mask by a square element (no wrap-around at the edges)."""
    if radius <= 0:
        return mask
    height, width = mask.shape
    padded = np.pad(mask, radius, mode="constant", constant_values=False)
    out = np.zeros_like(mask)
    for dy in range(2 * radius + 1):
        for dx in range(2 * radius + 1):
            out |= padded[dy : dy + height, dx : dx + width]
    return out


def erode(mask: np.ndarray, radius: int = 1) -> np.ndarray:
    """Shrink a boolean mask (the dual of :func:`dilate`)."""
    if radius <= 0:
        return mask
    return ~dilate(~mask, radius)


def close_holes(mask: np.ndarray, radius: int = 1) -> np.ndarray:
    """Fill holes up to ``2*radius`` inside glyph shapes without growing them.

    Detector masks often light up the outline of a thick stroke and leave its
    middle dark; closing fills that middle while keeping the outer boundary.
    """
    if radius <= 0:
        return mask
    return erode(dilate(mask, radius), radius)


def erased_mask(
    probability: np.ndarray,
    pixels: np.ndarray,
    config: MaskedConfig,
    blocks: Sequence[TextBlock] = (),
) -> np.ndarray:
    """Pixels to erase: the detector's mask minus structural ink.

    Only text pixels are ever touched. An earlier version also unioned the whole
    block box to fill gaps in the mask, which turned nested bubbles into solid
    rectangles and smeared artwork; the gaps are closed morphologically instead.
    """
    gray = np.asarray(Image.fromarray(pixels[..., :3]).convert("L"))
    allowed = np.zeros(gray.shape, dtype=bool)
    height, width = gray.shape
    for block in blocks:
        area = block.erase_bbox or block.bbox
        x1, y1, x2, y2 = clip_bbox(area, width, height)
        allowed[y1:y2, x1:x2] = True
    if not allowed.any():
        return allowed

    text = (probability > config.text_threshold) & allowed
    text = close_holes(text, radius=1)
    # Grow *before* subtracting structure: growing afterwards would eat one pixel
    # of bubble outline wherever text touches it.
    text = dilate(text, config.grow)
    ink = ink_mask(gray)
    labels, stats = label_components(ink)
    structure = structure_mask(labels, stats, text, allowed)
    if config.structure_dilate:
        structure = dilate(structure, config.structure_dilate)
    return text & ~structure


class MaskedInpainter:
    """Erase only the glyph pixels, preserving bubble borders and artwork."""

    name = "masked"

    def __init__(self, config: MaskedConfig | None = None) -> None:
        self.config = config or MaskedConfig()

    def erase(
        self,
        image_path: Path,
        destination: Path,
        blocks: Sequence[TextBlock] = (),
        mask: np.ndarray | None = None,
    ) -> None:
        """Write ``destination`` with the detected text removed.

        ``mask`` is the detector's per-pixel text probability. Without it the
        adapter falls back to the block boxes, which is only an approximation.
        """
        with Image.open(image_path) as handle:
            image = handle.convert("RGBA" if "A" in handle.getbands() else "RGB")
        pixels = np.array(image)

        if mask is not None:
            probability = np.asarray(mask, dtype=np.float32)
        else:
            probability = self._boxes_as_mask(pixels.shape[:2], blocks)

        erase = erased_mask(probability, pixels, self.config, blocks)
        out = pixels.copy()
        height, width = out.shape[:2]

        for block in blocks:
            if not is_solid(pixels, block.bbox, self.config.solid):
                continue
            x1, y1, x2, y2 = clip_bbox(block.bbox, width, height)
            selection = erase[y1:y2, x1:x2]
            if not selection.any():
                continue
            colour = median_colour(pixels, block.bbox, self.config.solid)
            if colour is None:
                continue
            region = out[y1:y2, x1:x2, :3]
            region[selection] = colour
            erase[y1:y2, x1:x2] = False

        if erase.any():
            out = diffuse(out, erase, iterations=self.config.diffusion.iterations)

        if out.shape[2] == 4:
            out[..., 3] = pixels[..., 3]

        destination.parent.mkdir(parents=True, exist_ok=True)
        mode = "RGBA" if out.shape[2] == 4 else "RGB"
        Image.fromarray(out, mode=mode).save(destination)

    @staticmethod
    def _boxes_as_mask(
        shape: tuple[int, int], blocks: Sequence[TextBlock]
    ) -> np.ndarray:
        height, width = shape
        probability = np.zeros((height, width), dtype=np.float32)
        for block in blocks:
            x1, y1, x2, y2 = clip_bbox(block.bbox, width, height)
            probability[y1:y2, x1:x2] = 1.0
        return probability
