"""Composite inpainting: flat bubbles by colour, the rest by diffusion.

This is the default adapter until LaMa's weights are wired in: it never fails on
missing models, never downloads anything, and gets the common manga cases right.

>>> callable(AutoInpainter().erase)
True
"""

from __future__ import annotations

from collections.abc import Sequence
from pathlib import Path

import numpy as np
from PIL import Image

from mangatl.adapters.inpaint.diffusion import DiffusionConfig, build_mask, diffuse
from mangatl.adapters.inpaint.solid import (
    SolidFillConfig,
    clip_bbox,
    is_solid,
    median_colour,
)
from mangatl.domain.block import TextBlock


class AutoInpainter:
    """Flat blocks get their bubble colour, textured blocks get diffusion."""

    name = "auto"

    def __init__(
        self,
        solid: SolidFillConfig | None = None,
        diffusion: DiffusionConfig | None = None,
    ) -> None:
        self.solid = solid or SolidFillConfig()
        self.diffusion = diffusion or DiffusionConfig()

    def erase(
        self,
        image_path: Path,
        destination: Path,
        blocks: Sequence[TextBlock] = (),
    ) -> None:
        """Write ``destination`` with every block removed."""
        with Image.open(image_path) as handle:
            image = handle.convert("RGBA" if "A" in handle.getbands() else "RGB")
        pixels = np.array(image)
        out = pixels.copy()
        height, width = out.shape[:2]

        textured: list[TextBlock] = []
        for block in blocks:
            if not is_solid(pixels, block.bbox, self.solid):
                textured.append(block)
                continue
            colour = median_colour(pixels, block.bbox, self.solid)
            if colour is None:
                textured.append(block)
                continue
            x1, y1, x2, y2 = clip_bbox(block.bbox, width, height)
            x1 = max(0, x1 - self.solid.expand)
            y1 = max(0, y1 - self.solid.expand)
            x2 = min(width, x2 + self.solid.expand)
            y2 = min(height, y2 + self.solid.expand)
            if x2 > x1 and y2 > y1:
                out[y1:y2, x1:x2, :3] = colour

        if textured:
            mask = build_mask((height, width), textured, expand=self.diffusion.expand)
            out = diffuse(out, mask, iterations=self.diffusion.iterations)

        destination.parent.mkdir(parents=True, exist_ok=True)
        mode = "RGBA" if out.shape[2] == 4 else "RGB"
        Image.fromarray(out, mode=mode).save(destination)
