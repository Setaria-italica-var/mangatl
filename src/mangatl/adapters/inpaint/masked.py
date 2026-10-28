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

    text_threshold: float = 0.5
    grow: int = 1
    structure_dilate: int = 1
    diffusion: DiffusionConfig = DiffusionConfig(expand=0, iterations=64)
    solid: SolidFillConfig = SolidFillConfig()


def dilate(mask: np.ndarray, radius: int = 1) -> np.ndarray:
    """Grow a boolean mask by a square element."""
    if radius <= 0:
        return mask
    out = mask.copy()
    for dy in range(-radius, radius + 1):
        for dx in range(-radius, radius + 1):
            if dy == 0 and dx == 0:
                continue
            out |= np.roll(np.roll(mask, dy, axis=0), dx, axis=1)
    return out


def erased_mask(
    probability: np.ndarray,
    pixels: np.ndarray,
    config: MaskedConfig,
    blocks: Sequence[TextBlock] = (),
) -> np.ndarray:
    """Pixels to erase: detector text or block area, minus structural ink.

    The detector's mask is precise but can be thinner than the glyphs (a solid
    demo glyph only lights up near its outline), so the block boxes are unioned
    in. Structure is subtracted per pixel afterwards, which keeps bubble outlines
    safe even when a box touches them.

    ``blocks`` is the *erasable* subset: SFX and texture blocks are filtered out
    by the pipeline before this point, and their pixels must stay untouched even
    if the detector's mask covers them.
    """
    gray = np.asarray(Image.fromarray(pixels[..., :3]).convert("L"))
    block_area = np.zeros(gray.shape, dtype=bool)
    height, width = gray.shape
    for block in blocks:
        x1, y1, x2, y2 = clip_bbox(block.bbox, width, height)
        block_area[y1:y2, x1:x2] = True
    if not block_area.any():
        return block_area

    text = (probability > config.text_threshold) & block_area
    ink = ink_mask(gray)
    labels, stats = label_components(ink)
    structure = structure_mask(labels, stats, text | block_area, block_area)
    if config.structure_dilate:
        structure = dilate(structure, config.structure_dilate)
    return dilate((text | block_area) & ~structure, config.grow)


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
