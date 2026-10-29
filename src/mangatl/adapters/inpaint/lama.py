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
    def _run(self, pixels: np.ndarray, erase: np.ndarray) -> np.ndarray:
        session = self._get_session()
        height, width = pixels.shape[:2]
        pad_h = (-height) % self.multiple
        pad_w = (-width) % self.multiple
        image = np.pad(pixels, ((0, pad_h), (0, pad_w), (0, 0)), mode="symmetric")
        hole = np.pad(erase, ((0, pad_h), (0, pad_w)), mode="constant", constant_values=False)

        tensor = image.transpose(2, 0, 1)[None].astype(np.float32) / 255.0
        mask_tensor = hole[None, None].astype(np.float32)
        outputs = session.run(
            None,
            {session.get_inputs()[0].name: tensor, session.get_inputs()[1].name: mask_tensor},
        )
        result = np.clip(outputs[0][0], 0, 1)
        if result.shape[0] == 3:
            result = result.transpose(1, 2, 0)
        result = (result * 255.0).round().astype(np.uint8)
        return result[:height, :width]

    def _get_session(self):
        if self._session is None:
            import onnxruntime as ort

            self._session = ort.InferenceSession(
                str(self.model_path), providers=["CPUExecutionProvider"]
            )
        return self._session
