"""MIT48px CTC OCR: a line-level engine for stylised manga lettering.

The model is 48-pixel line recogniser from manga-image-translator. It only works
when it receives **one text line per crop**: feeding a whole speech bubble with
several columns produces noise. This module therefore splits a block into its
columns (vertical text) or rows (horizontal text) before running the model, then
joins the results in reading order.

It is an optional engine: ``torch`` and ``einops`` are imported lazily, and the
weights must be downloaded by the user (see ``docs/mit48px-plan.md``).
"""

from __future__ import annotations

import os
from collections.abc import Sequence
from pathlib import Path

import numpy as np
from PIL import Image

from mangatl import paths
from mangatl.domain.block import TextBlock

MODEL_ENV = "MANGATL_MIT48_MODEL"
ALPHABET_ENV = "MANGATL_MIT48_ALPHABET"
DEFAULT_MODEL = paths.models_file("mit", "ocr-ctc.ckpt")
DEFAULT_ALPHABET = paths.models_file("mit", "alphabet-all-v5.txt")
TEXT_HEIGHT = 48
MIN_LINE = 8


def split_lines(
    pixels: np.ndarray,
    bbox: tuple[int, int, int, int],
    vertical: bool,
    min_gap: int = 4,
) -> list[tuple[int, int, int, int]]:
    """Split a block into single lines by finding blank gaps between them.

    Vertical Japanese stacks several columns; horizontal lines stack rows. The ink
    projection shows those gaps, so a block of two columns becomes two crops, each
    of which the line model can actually read.

    >>> import numpy as np
    >>> page = np.full((60, 120, 3), 255, dtype=np.uint8)
    >>> page[10:50, 10:40] = 0
    >>> page[10:50, 70:100] = 0
    >>> split_lines(page, (0, 0, 120, 60), vertical=True)
    [(10, 10, 40, 50), (70, 10, 100, 50)]
    """
    height, width = pixels.shape[:2]
    x1, y1, x2, y2 = bbox
    x1, y1 = max(0, min(x1, width)), max(0, min(y1, height))
    x2, y2 = max(0, min(x2, width)), max(0, min(y2, height))
    if x2 - x1 < MIN_LINE or y2 - y1 < MIN_LINE:
        return [(x1, y1, x2, y2)] if x2 > x1 and y2 > y1 else []

    region = pixels[y1:y2, x1:x2, :3].astype(np.float32).mean(axis=2)
    intervals = _ink_intervals(region < 120, vertical, max_span=0.6)
    if not intervals:
        return [(x1, y1, x2, y2)]

    spans = [[intervals[0][0], intervals[0][1]]]
    for begin, stop in intervals[1:]:
        if begin - spans[-1][1] <= min_gap:
            spans[-1][1] = max(spans[-1][1], stop)
        else:
            spans.append([begin, stop])

    lines: list[tuple[int, int, int, int]] = []
    for begin, stop in spans:
        if stop - begin < MIN_LINE:
            continue
        if vertical:
            lines.append((x1 + begin, y1, x1 + stop, y2))
        else:
            lines.append((x1, y1 + begin, x2, y1 + stop))
    return lines or [(x1, y1, x2, y2)]


def _ink_intervals(
    ink: np.ndarray, vertical: bool, max_span: float = 0.0
) -> list[tuple[int, int]]:
    """X (or Y) extents of connected glyph clusters, merged into lines.

    Grouping components by their projection axis is much more robust than a
    density threshold: an isolated speck cannot erase a whole column, and a thin
    column is not mistaken for a gap.
    """
    from mangatl.adapters.imaging import label_components

    _labels, stats = label_components(ink)
    axis = ink.shape[1] if vertical else ink.shape[0]
    limit = max_span * axis if max_span else axis
    intervals: list[tuple[int, int]] = []
    for item in stats:
        if item.area < 8:
            continue
        x1, y1, x2, y2 = item.bbox
        begin, stop = (x1, x2) if vertical else (y1, y2)
        # A border line spans the whole block; keeping it would glue every column
        # into one "line".
        if stop - begin > limit:
            continue
        intervals.append((begin, stop))
    intervals.sort()
    return intervals


def order_lines(
    lines: Sequence[tuple[int, int, int, int]], vertical: bool
) -> list[tuple[int, int, int, int]]:
    """Sort split lines the way they are read."""
    if vertical:
        return sorted(lines, key=lambda box: -box[2])
    return sorted(lines, key=lambda box: box[1])


def prepare_line(crop: Image.Image, vertical: bool) -> np.ndarray:
    """Rotate a vertical line and scale it to the model's 48 px height."""
    if vertical:
        crop = crop.transpose(Image.Transpose.ROTATE_90)
    scale = TEXT_HEIGHT / max(1, crop.height)
    resized = crop.resize((max(2, int(crop.width * scale)), TEXT_HEIGHT), Image.LANCZOS)
    return np.asarray(resized.convert("RGB"))


class Mit48pxOcr:
    """Line-level OCR with the MIT48px CTC model."""

    name = "mit48px_ctc"

    def __init__(
        self,
        model_path: str | None = None,
        alphabet_path: str | None = None,
        device: str = "cpu",
    ) -> None:
        self.model_path = Path(model_path or os.environ.get(MODEL_ENV, DEFAULT_MODEL))
        self.alphabet_path = Path(
            alphabet_path or os.environ.get(ALPHABET_ENV, DEFAULT_ALPHABET)
        )
        if not self.model_path.is_file():
            raise FileNotFoundError(
                f"MIT48px weights not found: {self.model_path}\n"
                "see docs/mit48px-plan.md for the download command"
            )
        self.device = device
        self._model = None
        self._dictionary: list[str] = []

    def recognize(self, image_path: Path, blocks: Sequence[TextBlock]) -> list[TextBlock]:
        """Read every block line by line; vertical blocks are split into columns."""
        self._load()
        with Image.open(image_path) as handle:
            page = handle.convert("RGB")
        pixels = np.asarray(page)

        jobs: list[tuple[int, int, tuple[int, int, int, int], bool]] = []
        for block_index, block in enumerate(blocks):
            lines = order_lines(split_lines(pixels, block.bbox, block.vertical), block.vertical)
            for line_index, line in enumerate(lines):
                jobs.append((block_index, line_index, line, block.vertical))

        texts = self._decode_batch(page, jobs)
        grouped: dict[int, list[tuple[int, str]]] = {}
        for (block_index, line_index, _line, _vertical), text in zip(jobs, texts, strict=True):
            grouped.setdefault(block_index, []).append((line_index, text))

        for block_index, block in enumerate(blocks):
            parts = [text for _index, text in sorted(grouped.get(block_index, []))]
            block.text = "\n".join(part for part in parts if part).strip()
            block.confidence = 0.6 if block.text else 0.0
            if not block.text:
                block.needs_review = True
        return list(blocks)

    # -- internals --------------------------------------------------------
    def _load(self) -> None:
        if self._model is not None:
            return
        try:
            import torch
        except ImportError as exc:  # pragma: no cover - optional dependency
            raise ImportError(
                "MIT48px needs torch and einops: uv pip install torch einops"
            ) from exc

        import warnings

        from mangatl.adapters.ocr import mit48px_model as model_module

        self._dictionary = [
            line.rstrip("\n")
            for line in self.alphabet_path.read_text(encoding="utf-8").splitlines()
            if line
        ]
        skip = {f"encoders.layers.{index}.pe.pe" for index in range(3)}
        state = torch.load(str(self.model_path), map_location="cpu")
        for key in skip:
            state.pop(key, None)
        weights = state.get("model", state)
        # torch warns about nested tensors for the vendored custom encoder layer;
        # it is a tuning hint, not a problem, and it repeats on every start.
        with warnings.catch_warnings():
            warnings.filterwarnings("ignore", message="enable_nested_tensor")
            model = model_module.OCR(self._dictionary, 768)
        model.load_state_dict(weights, strict=False)
        model.eval()
        if self.device != "cpu":
            model = model.to(self.device)
        self._model = model

    def _decode_batch(
        self, page: Image.Image, jobs: Sequence[tuple[int, int, tuple[int, int, int, int], bool]]
    ) -> list[str]:
        if not jobs:
            return []
        crops = [prepare_line(page.crop(line), vertical) for _b, _l, line, vertical in jobs]
        widths = [crop.shape[1] for crop in crops]
        batch_width = (4 * (max(widths) + 7) // 4) + 128
        batch = np.zeros((len(crops), TEXT_HEIGHT, batch_width, 3), dtype=np.uint8)
        for index, crop in enumerate(crops):
            batch[index, :, : crop.shape[1], :] = crop

        import torch

        images = (torch.from_numpy(batch).float() - 127.5) / 127.5
        images = images.permute(0, 3, 1, 2)
        if self.device != "cpu":
            images = images.to(self.device)
        with torch.inference_mode():
            decoded = self._model.decode(images, widths, 0)
        texts: list[str] = []
        for line in decoded:
            texts.append("".join(self._dictionary[item[0]] for item in line) if line else "")
        return texts
