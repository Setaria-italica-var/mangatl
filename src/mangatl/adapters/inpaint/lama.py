"""LaMa inpainting through ONNX, with a graceful fallback.

LaMa reconstructs plausible texture instead of smearing neighbouring pixels, so
glyph areas over screentone stop looking like mosaic. It needs weights (about
200 MB); without them the inpainter delegates to the mask-constrained filler.

The mask is built exactly like :mod:`mangatl.adapters.inpaint.masked` - only glyph
pixels are replaced, bubble outlines and artwork stay untouched.
"""

from __future__ import annotations

from collections.abc import Sequence
from pathlib import Path

import numpy as np
from PIL import Image

from mangatl.adapters.inpaint.masked import MaskedConfig, MaskedInpainter, erased_mask
from mangatl.domain.block import TextBlock

DEFAULT_MODEL = "data/models/lama.onnx"


class LamaInpainter:
    """Erase glyph pixels and let LaMa rebuild the background."""

    name = "lama"

    def __init__(
        self,
        model_path: Path | str = DEFAULT_MODEL,
        fallback: MaskedInpainter | None = None,
        config: MaskedConfig | None = None,
        multiple: int = 8,
    ) -> None:
        self.model_path = Path(model_path)
        self.config = config or MaskedConfig()
        self.fallback = fallback or MaskedInpainter(self.config)
        self.multiple = multiple
        self._session = None

    @property
    def available(self) -> bool:
        """Whether the LaMa weights exist."""
        return self.model_path.is_file()

    def erase(
        self,
        image_path: Path,
        destination: Path,
        blocks: Sequence[TextBlock] = (),
        mask: np.ndarray | None = None,
    ) -> Path:
        """Inpaint the glyph mask; fall back when LaMa is unavailable."""
        if not self.available or mask is None:
            return self.fallback.erase(image_path, destination, blocks, mask=mask)

        with Image.open(image_path) as handle:
            page = handle.convert("RGB")
        pixels = np.asarray(page)
        erase = erased_mask(np.asarray(mask), pixels, self.config, blocks)
        if not erase.any():
            return self.fallback.erase(image_path, destination, blocks, mask=mask)

        try:
            filled = self._run(pixels, erase)
        except Exception:  # noqa: BLE001 - drop to the local filler on model errors
            return self.fallback.fill_region(image_path, destination, mask)
        result = pixels.copy()
        result[erase] = filled[erase]
        destination.parent.mkdir(parents=True, exist_ok=True)
        Image.fromarray(result).save(destination)
        return destination

    def fill_region(
        self, image_path: Path, destination: Path, mask: np.ndarray
    ) -> Path:
        """Photoshop-style fill of the whole selection, LaMa when available."""
        if not self.available:
            return self.fallback.fill_region(image_path, destination, mask)
        with Image.open(image_path) as handle:
            pixels = np.asarray(handle.convert("RGB"))
        erase = np.asarray(mask, dtype=bool)
        if erase.shape != pixels.shape[:2]:
            erase = erase[: pixels.shape[0], : pixels.shape[1]]
        if not erase.any():
            return destination
        try:
            filled = self._run(pixels, erase)
        except Exception:  # noqa: BLE001 - drop to the local filler on model errors
            return self.fallback.fill_region(image_path, destination, mask)
        result = pixels.copy()
        result[erase] = filled[erase]
        destination.parent.mkdir(parents=True, exist_ok=True)
        Image.fromarray(result).save(destination)
        return destination

    # -- internals --------------------------------------------------------
    def _input_size(self) -> int | None:
        """Fixed square input size of the graph, or ``None`` when dynamic."""
        shape = self._get_session().get_inputs()[0].shape
        if len(shape) == 4 and all(isinstance(dim, int) and dim > 0 for dim in shape[2:]):
            return int(shape[2])
        return None

    def _run(self, pixels: np.ndarray, erase: np.ndarray) -> np.ndarray:
        session = self._get_session()
        size = self._input_size()
        if size is None:
            return self._run_dynamic(session, pixels, erase)
        return self._run_tiled(session, pixels, erase, size)

    def _run_dynamic(self, session, pixels: np.ndarray, erase: np.ndarray) -> np.ndarray:
        height, width = pixels.shape[:2]
        pad_h = (-height) % self.multiple
        pad_w = (-width) % self.multiple
        image = np.pad(pixels, ((0, pad_h), (0, pad_w), (0, 0)), mode="symmetric")
        hole = np.pad(
            erase, ((0, pad_h), (0, pad_w)), mode="constant", constant_values=False
        )
        tensor = image.transpose(2, 0, 1)[None].astype(np.float32) / 255.0
        mask_tensor = hole[None, None].astype(np.float32)
        outputs = session.run(
            None,
            {
                session.get_inputs()[0].name: tensor,
                session.get_inputs()[1].name: mask_tensor,
            },
        )
        return self._to_pixels(outputs[0], height, width)

    def _run_tiled(
        self, session, pixels: np.ndarray, erase: np.ndarray, size: int
    ) -> np.ndarray:
        """Run a fixed-size graph tile by tile around the erased area."""
        height, width = pixels.shape[:2]
        rows = np.where(erase.any(axis=1))[0]
        cols = np.where(erase.any(axis=0))[0]
        if rows.size == 0 or cols.size == 0:
            return pixels.copy()
        top, bottom = int(rows[0]), int(rows[-1]) + 1
        left, right = int(cols[0]), int(cols[-1]) + 1
        stride = max(1, size // 2)
        result = pixels.copy()

        margin = size // 4
        top = max(0, top - margin)
        left = max(0, left - margin)
        bottom = min(height, bottom + margin)
        right = min(width, right + margin)
        if right - left <= size and bottom - top <= size:
            # One 512 tile covers the whole selection: do not pay for overlaps.
            y0 = max(0, min(top, height - size))
            x0 = max(0, min(left, width - size))
            tile_image, tile_mask = self._pad_tile(
                pixels[y0 : y0 + size, x0 : x0 + size],
                erase[y0 : y0 + size, x0 : x0 + size],
                size,
            )
            tensor = tile_image.transpose(2, 0, 1)[None].astype(np.float32) / 255.0
            mask_tensor = tile_mask[None, None].astype(np.float32)
            outputs = session.run(
                None,
                {
                    session.get_inputs()[0].name: tensor,
                    session.get_inputs()[1].name: mask_tensor,
                },
            )
            filled = self._to_pixels(outputs[0], size, size)
            h = min(size, height - y0)
            w = min(size, width - x0)
            result[y0 : y0 + h, x0 : x0 + w][tile_mask[:h, :w]] = filled[:h, :w][
                tile_mask[:h, :w]
            ]
            return result
        for y0 in range(top, max(top + 1, bottom), stride):
            for x0 in range(left, max(left + 1, right), stride):
                tile_image = pixels[y0 : y0 + size, x0 : x0 + size]
                tile_mask = erase[y0 : y0 + size, x0 : x0 + size]
                tile_image, tile_mask = self._pad_tile(tile_image, tile_mask, size)
                if not tile_mask.any():
                    continue
                tensor = tile_image.transpose(2, 0, 1)[None].astype(np.float32) / 255.0
                mask_tensor = tile_mask[None, None].astype(np.float32)
                outputs = session.run(
                    None,
                    {
                        session.get_inputs()[0].name: tensor,
                        session.get_inputs()[1].name: mask_tensor,
                    },
                )
                filled = self._to_pixels(outputs[0], size, size)
                h = min(size, height - y0)
                w = min(size, width - x0)
                patch = filled[:h, :w]
                mask = tile_mask[:h, :w]
                result[y0 : y0 + h, x0 : x0 + w][mask] = patch[mask]
        return result

    @staticmethod
    def _pad_tile(image: np.ndarray, mask: np.ndarray, size: int):
        pad_h = size - image.shape[0]
        pad_w = size - image.shape[1]
        if pad_h or pad_w:
            image = np.pad(
                image, ((0, max(0, pad_h)), (0, max(0, pad_w)), (0, 0)), mode="edge"
            )
            mask = np.pad(
                mask, ((0, max(0, pad_h)), (0, max(0, pad_w))), mode="constant"
            )
        return image[:size, :size], mask[:size, :size]

    @staticmethod
    def _to_pixels(output: np.ndarray, height: int, width: int) -> np.ndarray:
        array = output[0]
        # Some exports emit 0..255 instead of 0..1; detect it instead of clipping
        # the image into black-and-white poster.
        if float(array.max()) > 1.5:
            array = array / 255.0
        result = np.clip(array, 0, 1)
        if result.shape[0] == 3:
            result = result.transpose(1, 2, 0)
        result = (result * 255.0).round().astype(np.uint8)
        return result[:height, :width]

    def _get_session(self):
        if self._session is None:
            import onnxruntime as ort

            options = ort.SessionOptions()
            # LaMa uses FFC blocks whose DFT nodes fail shape inference when ORT
            # fuses them; disabling optimisation keeps the graph usable.
            options.graph_optimization_level = (
                ort.GraphOptimizationLevel.ORT_DISABLE_ALL
            )
            self._session = ort.InferenceSession(
                str(self.model_path),
                options,
                providers=["CPUExecutionProvider"],
            )
        return self._session
