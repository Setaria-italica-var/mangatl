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

from PIL import Image, ImageOps

from mangatl.domain.block import TextBlock

DEFAULT_MODEL = "kha-white/manga-ocr-base"
NEUTRAL_CONFIDENCE = 0.6


def local_snapshot(model_name: str = DEFAULT_MODEL) -> str | None:
    """Resolve a cached snapshot directory for ``model_name``.

    Every candidate root is checked, in order: the project cache (``data/hf``),
    ``HF_HOME``/``HUGGINGFACE_HUB_CACHE``, then the user cache. Returning a real
    directory is what keeps the library offline: given a repo id it always issues
    HEAD requests, whatever the environment says.
    """
    roots: list[Path] = [Path("data/hf")]
    for variable in ("HF_HOME", "HUGGINGFACE_HUB_CACHE"):
        value = os.environ.get(variable)
        if value:
            roots.append(Path(value))
    roots.append(Path.home() / ".cache" / "huggingface")

    slug = "models--" + model_name.replace("/", "--")
    for root in roots:
        for hub in (root / "hub", root):
            snapshots = hub / slug / "snapshots"
            if not snapshots.is_dir():
                continue
            candidates = sorted(
                (item for item in snapshots.iterdir() if item.is_dir()), reverse=True
            )
            for candidate in candidates:
                if (candidate / "config.json").is_file():
                    return str(candidate)
    return None


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
        # Prefer a cached snapshot unconditionally: it is the only way to avoid
        # hub probes, and a local directory behaves identically when online.
        resolved = local_snapshot(model_name)
        self._model = build_model(MangaOcr, resolved or model_name, device)

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
                    text = self._read(crop)
                    block.text = text
                    block.confidence = NEUTRAL_CONFIDENCE if text else 0.0
                except Exception:  # a single bad crop must not kill the page
                    block.text = ""
                    block.confidence = 0.0
        return list(blocks)

    def _read(self, crop: Image.Image) -> str:
        """Try the plain crop, then preprocessing variants, until text appears."""
        for candidate in variants(crop):
            text = self._model(candidate).strip()
            if text:
                return text
        return ""


def variants(crop: Image.Image) -> list[Image.Image]:
    """Preprocessing fallbacks for crops the model reads as empty.

    Small, low-contrast or inverted lettering is common in manga; upscaling with
    an autocontrast pass, then trying the negative, recovers a good share of it
    without any extra model.
    """
    enlarged = crop.resize((crop.width * 2, crop.height * 2), Image.LANCZOS)
    # The model expects some margin around a text line; a tight crop shrinks its
    # context and often yields an empty read, so padding is part of the retry set.
    border = max(8, min(crop.width, crop.height) // 8)
    padded = ImageOps.expand(crop, border=border, fill=(255, 255, 255))
    padded_large = ImageOps.expand(enlarged, border=border * 2, fill=(255, 255, 255))
    return [
        crop,
        padded,
        ImageOps.autocontrast(enlarged),
        ImageOps.autocontrast(padded_large),
        ImageOps.invert(ImageOps.autocontrast(enlarged)),
    ]


def hub_endpoint() -> str:
    """Return the configured HuggingFace endpoint (for logging and errors)."""
    return os.environ.get("HF_ENDPOINT", "https://huggingface.co")
