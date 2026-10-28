"""RapidOCR adapter: PP-OCR models through onnxruntime, with real confidences.

Why a second OCR engine: ``manga-ocr`` is more accurate on Japanese lettering but
returns no score, which leaves the role classifier guessing between "no text" and
"decoration". RapidOCR returns ``score`` per line, costs a few tens of
milliseconds on CPU and handles Latin text, so it is used as the confidence
provider and the English engine.

Both package generations are supported, because the import path changed:

* ``rapidocr`` (2.x): the call returns an object with ``boxes``/``txts``/``scores``;
* ``rapidocr_onnxruntime`` (1.x): the call returns ``(result, elapsed)`` where each
  item is ``[box, text, score]``.

The engine runs once per page and its lines are matched to the detector blocks by
overlap, which is faster and more stable than cropping each block.
"""

from __future__ import annotations

from collections.abc import Sequence
from pathlib import Path
from typing import Any

import numpy as np

from mangatl.domain.block import TextBlock

MIN_LINE_SCORE = 0.3
MIN_OVERLAP = 0.15


def _bbox(box: Any) -> tuple[float, float, float, float]:
    """Convert a 4-point polygon (or an xyxy box) to ``(x1, y1, x2, y2)``."""
    array = np.asarray(box, dtype=np.float32).reshape(-1, 2)
    return (
        float(array[:, 0].min()),
        float(array[:, 1].min()),
        float(array[:, 0].max()),
        float(array[:, 1].max()),
    )


def _intersection(
    a: tuple[float, float, float, float], b: tuple[float, float, float, float]
) -> float:
    width = min(a[2], b[2]) - max(a[0], b[0])
    height = min(a[3], b[3]) - max(a[1], b[1])
    if width <= 0 or height <= 0:
        return 0.0
    return width * height


def overlap_ratio(
    line: tuple[float, float, float, float], block: tuple[float, float, float, float]
) -> float:
    """Intersection over the *line* area: how much of the line sits in the block."""
    area = max(1.0, (line[2] - line[0]) * (line[3] - line[1]))
    return _intersection(line, block) / area


class RapidOcrAdapter:
    """Recognise text with RapidOCR and attach line texts to detected blocks."""

    name = "rapidocr"

    def __init__(self, **engine_kwargs: Any) -> None:
        try:
            from rapidocr import RapidOCR  # 2.x
        except ImportError:
            try:
                from rapidocr_onnxruntime import RapidOCR  # 1.x
            except ImportError as exc:  # pragma: no cover - depends on the install
                raise ImportError(
                    "RapidOCR is not installed: uv pip install rapidocr onnxruntime\n"
                    "(or: uv pip install rapidocr-onnxruntime)"
                ) from exc
            self._legacy = True
        else:
            self._legacy = False
        self._engine = RapidOCR(**engine_kwargs)

    # -- engine output normalisation -------------------------------------
    def _run(self, image_path: Path) -> list[tuple[tuple[float, float, float, float], str, float]]:
        output = self._engine(str(image_path))
        lines: list[tuple[tuple[float, float, float, float], str, float]] = []

        if self._legacy:
            result = output[0] if isinstance(output, tuple) else output
            for item in result or []:
                box, text, score = item[0], item[1], item[2]
                lines.append((_bbox(box), str(text), float(score)))
            return lines

        boxes = getattr(output, "boxes", None)
        texts = getattr(output, "txts", None)
        scores = getattr(output, "scores", None)
        if boxes is None or texts is None:
            return lines
        for index, box in enumerate(boxes):
            text = texts[index] if index < len(texts) else ""
            score = float(scores[index]) if scores is not None and index < len(scores) else 0.0
            lines.append((_bbox(box), str(text), score))
        return lines

    # -- block matching ---------------------------------------------------
    def recognize(self, image_path: Path, blocks: Sequence[TextBlock]) -> list[TextBlock]:
        """Attach recognised lines to blocks; unmatched blocks keep empty text."""
        lines = self._run(image_path)
        assigned: dict[int, list[tuple[tuple[float, float, float, float], str, float]]] = {
            index: [] for index in range(len(blocks))
        }

        for line_box, text, score in lines:
            if score < MIN_LINE_SCORE or not text.strip():
                continue
            best_index, best_ratio = -1, 0.0
            for index, block in enumerate(blocks):
                ratio = overlap_ratio(line_box, block.bbox)
                if ratio > best_ratio:
                    best_index, best_ratio = index, ratio
            if best_index >= 0 and best_ratio >= MIN_OVERLAP:
                assigned[best_index].append((line_box, text, score))

        for index, block in enumerate(blocks):
            entries = assigned[index]
            if not entries:
                block.text = ""
                block.confidence = 0.0
                continue
            if block.vertical:
                entries.sort(key=lambda entry: (-(entry[0][0] + entry[0][2]) / 2, entry[0][1]))
            else:
                entries.sort(key=lambda entry: ((entry[0][1] + entry[0][3]) / 2, entry[0][0]))
            block.text = "".join(entry[1].strip() for entry in entries)
            block.confidence = float(np.mean([entry[2] for entry in entries]))
        return list(blocks)
