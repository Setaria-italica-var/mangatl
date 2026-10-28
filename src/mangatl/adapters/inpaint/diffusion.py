"""Weight-free inpainting by solving a Laplace equation on the masked pixels.

For a background that changes smoothly (a gradient in a bubble, a soft shadow, a
grey screentone) filling with one colour leaves a visible patch. Diffusion
propagates the boundary colours inwards instead, which keeps the gradient and
costs only numpy.

It is deliberately not a texture synthesiser: hard edges and line art inside the
block come out blurry, which is exactly where LaMa is still needed. The class
exists so the pipeline has a usable fallback before any weights are downloaded.

>>> np = __import__("numpy")
>>> canvas = np.zeros((8, 8, 3), dtype=np.uint8)
>>> canvas[..., :] = 200
>>> mask = np.zeros((8, 8), dtype=bool)
>>> mask[3:5, 3:5] = True
>>> filled = diffuse(canvas, mask, iterations=16)
>>> int(filled[3, 3, 0])
200
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path

import numpy as np
from PIL import Image

from mangatl.adapters.inpaint.solid import clip_bbox
from mangatl.domain.block import TextBlock


@dataclass(frozen=True)
class DiffusionConfig:
    """Tuning knobs for the diffusion fill."""

    expand: int = 2
    iterations: int = 128


def build_mask(
    shape: tuple[int, int],
    blocks: Sequence[TextBlock],
    expand: int = 2,
) -> np.ndarray:
    """Return a boolean mask covering every block, grown by ``expand`` pixels."""
    height, width = shape
    mask = np.zeros((height, width), dtype=bool)
    for block in blocks:
        x1, y1, x2, y2 = clip_bbox(block.bbox, width, height)
        x1 = max(0, x1 - expand)
        y1 = max(0, y1 - expand)
        x2 = min(width, x2 + expand)
        y2 = min(height, y2 + expand)
        if x2 > x1 and y2 > y1:
            mask[y1:y2, x1:x2] = True
    return mask


def pyramid_fill(pixels: np.ndarray, mask: np.ndarray) -> np.ndarray:
    """Fill ``mask`` by push-pull: average at coarse scales, then upsample.

    Plain Jacobi needs roughly ``n²`` sweeps to cross an ``n`` pixel hole, which
    is unusable for a 200 px block. The pyramid reaches the same answer in
    ``O(log n)`` passes and gives a smooth, gradient-following initial guess; the
    Jacobi sweeps afterwards only polish it.

    >>> np = __import__("numpy")
    >>> canvas = np.full((16, 16, 3), 250, dtype=np.uint8)
    >>> m = np.zeros((16, 16), dtype=bool); m[6:10, 6:10] = True
    >>> int(pyramid_fill(canvas.astype(np.float32), m)[8, 8, 0])
    250
    """
    if not mask.any():
        return pixels.astype(np.float32)

    weight = (~mask).astype(np.float32)
    sums = [(pixels.astype(np.float32) * weight[..., None], weight)]
    while min(sums[-1][1].shape[:2]) > 2:
        value, weight_level = sums[-1]
        rows, cols = (value.shape[0] // 2) * 2, (value.shape[1] // 2) * 2
        shape = (rows // 2, 2, cols // 2, 2)
        reduced_value = value[:rows, :cols].reshape(*shape, -1).sum(axis=(1, 3))
        reduced_weight = weight_level[:rows, :cols].reshape(shape).sum(axis=(1, 3))
        sums.append((reduced_value, reduced_weight))

    coarse_value, coarse_weight = sums[-1]
    divisor = np.maximum(coarse_weight[..., None], 1e-6)
    resolved = np.divide(coarse_value, divisor, out=np.zeros_like(coarse_value), where=divisor > 0)
    known_coarse = coarse_weight > 0
    if known_coarse.any():
        # Seed fully masked coarse cells with the mean of the known ones; leaving
        # zeros there would drag the whole hole towards black.
        fallback = resolved[known_coarse].mean(axis=0)
    else:
        fallback = pixels[mask].mean(axis=0) if mask.any() else np.zeros(pixels.shape[2])
    current = np.where(known_coarse[..., None], resolved, fallback)

    for finer_value, finer_weight in reversed(sums[:-1]):
        height, width = finer_value.shape[:2]
        rows = np.minimum(np.arange(height) // 2, current.shape[0] - 1)
        cols = np.minimum(np.arange(width) // 2, current.shape[1] - 1)
        upsampled = current[rows][:, cols]
        known = (finer_weight > 0)[..., None]
        finer_divisor = np.maximum(finer_weight[..., None], 1e-6)
        current = np.where(known, finer_value / finer_divisor, upsampled)

    return current


def diffuse(pixels: np.ndarray, mask: np.ndarray, iterations: int = 64) -> np.ndarray:
    """Fill ``mask`` with a smooth Laplacian solution, keeping the rest untouched.

    The pyramid provides the initial guess, then ``iterations`` Jacobi sweeps
    remove the residual blockiness. Only the masked bounding box plus a one pixel
    ring is processed, so cost scales with the hole, not with the page.

    >>> np = __import__("numpy")
    >>> canvas = np.full((6, 6, 3), 100, dtype=np.uint8)
    >>> m = np.zeros((6, 6), dtype=bool); m[2:4, 2:4] = True
    >>> diffuse(canvas, m, iterations=8)[2, 2, 0]
    100
    """
    if not mask.any():
        return pixels

    height, width = mask.shape
    ys, xs = np.nonzero(mask)
    top, bottom = max(0, int(ys.min()) - 1), min(height, int(ys.max()) + 2)
    left, right = max(0, int(xs.min()) - 1), min(width, int(xs.max()) + 2)

    crop_pixels = pixels[top:bottom, left:right]
    crop_mask = mask[top:bottom, left:right]
    crop = pyramid_fill(crop_pixels, crop_mask)

    for _ in range(max(0, iterations)):
        padded = np.pad(crop, ((1, 1), (1, 1), (0, 0)), mode="edge")
        average = (
            padded[:-2, 1:-1] + padded[2:, 1:-1] + padded[1:-1, :-2] + padded[1:-1, 2:]
        ) / 4.0
        crop[crop_mask] = average[crop_mask]

    out = pixels.copy()
    out[top:bottom, left:right] = np.clip(crop, 0, 255).astype(np.uint8)
    if out.shape[2] == 4:
        # Erasing glyphs must never alter the page transparency.
        out[..., 3] = pixels[..., 3]
    return out


class DiffusionInpainter:
    """Fill every block via diffusion; no model, no weights, CPU only."""

    name = "diffusion"

    def __init__(self, config: DiffusionConfig | None = None) -> None:
        self.config = config or DiffusionConfig()

    def erase(
        self,
        image_path: Path,
        destination: Path,
        blocks: Sequence[TextBlock] = (),
        mask=None,
    ) -> None:
        """Write ``destination`` with the blocks diffused away."""
        with Image.open(image_path) as handle:
            image = handle.convert("RGBA" if "A" in handle.getbands() else "RGB")
        pixels = np.array(image)

        mask = build_mask(pixels.shape[:2], blocks, expand=self.config.expand)
        out = diffuse(pixels, mask, iterations=self.config.iterations)

        destination.parent.mkdir(parents=True, exist_ok=True)
        mode = "RGBA" if out.shape[2] == 4 else "RGB"
        Image.fromarray(out, mode=mode).save(destination)
