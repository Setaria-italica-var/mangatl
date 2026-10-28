"""manga-ocr adapter: Japanese text recognition, CPU friendly.

``manga-ocr`` is a third-party model (about 400 MB of weights) and is imported
lazily so the pipeline still runs without it. Weights are fetched from the
HuggingFace hub on first use; behind a slow link set ``HF_ENDPOINT`` to a mirror
(``https://hf-mirror.com``) and ``HF_HOME`` to a writable cache directory before
constructing the adapter.

The model returns text but no confidence, so blocks are tagged with a neutral
score; the role classifier still rejects empty results as ``texture``.
"""

from __future__ import annotations

import inspect
import os
from collections.abc import Sequence
from pathlib import Path

from PIL import Image

from mangatl.domain.block import TextBlock

DEFAULT_MODEL = "kha-white/manga-ocr-base"
NEUTRAL_CONFIDENCE = 0.6


def build_model(factory, model_name: str, device: str):
    """Instantiate ``MangaOcr`` whatever its constructor accepts.

    Released versions take ``(pretrained_model_name_or_path, force_cpu)``; some
    builds expose ``device`` instead. Reading the signature avoids a hard failure
    on either.
    """
    parameters = inspect.signature(factory.__init__).parameters
    kwargs: dict[str, object] = {}
    if "pretrained_model_name_or_path" in parameters:
        kwargs["pretrained_model_name_or_path"] = model_name
    if "force_cpu" in parameters:
        kwargs["force_cpu"] = device.startswith("cpu")
    elif "device" in parameters:
        kwargs["device"] = device
    return factory(**kwargs)


class MangaOcrAdapter:
    """Recognise Japanese text line by line with ``manga-ocr``."""

    name = "manga_ocr"

    def __init__(self, model_name: str = DEFAULT_MODEL, device: str = "cpu") -> None:
        try:
            from manga_ocr import MangaOcr
        except ImportError as exc:  # pragma: no cover - depends on the install
            raise ImportError(
                "manga-ocr is not installed: uv pip install manga-ocr\n"
                "downloads weights on first use; set HF_ENDPOINT=https://hf-mirror.com"
            ) from exc
        self.model_name = model_name
        self._model = build_model(MangaOcr, model_name, device)

    def recognize(self, image_path: Path, blocks: Sequence[TextBlock]) -> list[TextBlock]:
        """Fill ``text`` for every block; vertical blocks are rotated first."""
        with Image.open(image_path) as handle:
            page = handle.convert("RGB")
            width, height = page.size
            for block in blocks:
                x1, y1, x2, y2 = block.bbox
                x1, y1 = max(0, x1), max(0, y1)
                x2, y2 = min(width, x2), min(height, y2)
                if x2 <= x1 or y2 <= y1:
                    block.text = ""
                    block.confidence = 0.0
                    continue
                crop = page.crop((x1, y1, x2, y2))
                if block.vertical:
                    crop = crop.transpose(Image.Transpose.ROTATE_90)
                try:
                    block.text = self._model(crop).strip()
                    block.confidence = NEUTRAL_CONFIDENCE
                except Exception:  # a single bad crop must not kill the page
                    block.text = ""
                    block.confidence = 0.0
        return list(blocks)


def hub_endpoint() -> str:
    """Return the configured HuggingFace endpoint (for logging and errors)."""
    return os.environ.get("HF_ENDPOINT", "https://huggingface.co")
