"""Optional Surya OCR backend.

Surya 2 is a 650M vision-language OCR model from Datalab. It is strong on printed
documents (86%+ on their multilingual benchmark, Japanese at 86.2%) but it is
*not* a manga model, and it needs a separate inference backend: vLLM (Docker +
NVIDIA toolkit) on GPU, or a ``llama-server`` binary on CPU. That is a poor fit for
a portable one-folder desktop app, so it stays an opt-in extra for pages the
light models cannot read.

Licensing: the Surya *code* is Apache-2.0, the *weights* use a modified OpenRAIL-M
licence (free for research, personal use and companies under a revenue cap;
commercial use needs a licence). Weights are therefore never bundled: they are
downloaded by the user, and this module only talks to a locally installed backend.
"""

from __future__ import annotations

from collections.abc import Sequence
from pathlib import Path

from mangatl.domain.block import TextBlock

MIN_MATCH = 0.2


def _block_text(result) -> str:
    """Surya returns ``html`` in v2 and ``text`` in older releases."""
    for attribute in ("text", "html", "markdown"):
        value = getattr(result, attribute, None)
        if isinstance(value, str) and value.strip():
            return value.strip()
    if isinstance(result, dict):
        for key in ("text", "html", "markdown"):
            value = result.get(key)
            if isinstance(value, str) and value.strip():
                return value.strip()
    return ""


def _bbox(result) -> tuple[float, float, float, float] | None:
    box = getattr(result, "bbox", None)
    if box is None and isinstance(result, dict):
        box = result.get("bbox")
    if not box or len(box) < 4:
        return None
    return (float(box[0]), float(box[1]), float(box[2]), float(box[3]))


def overlap(line: tuple[float, float, float, float], block: tuple[int, int, int, int]) -> float:
    """Share of the recognised line that falls inside a block box."""
    area = max(1.0, (line[2] - line[0]) * (line[3] - line[1]))
    width = min(line[2], block[2]) - max(line[0], block[0])
    height = min(line[3], block[3]) - max(line[1], block[1])
    if width <= 0 or height <= 0:
        return 0.0
    return width * height / area


class SuryaOcr:
    """Recognise pages with Surya, attaching its lines to detected blocks."""

    name = "surya"

    def __init__(self, **options) -> None:
        try:
            from surya.inference import SuryaInferenceManager
            from surya.recognition import RecognitionPredictor
        except ImportError as exc:  # pragma: no cover - optional dependency
            raise ImportError(
                "Surya is not installed: uv pip install surya-ocr\n"
                "Surya also needs an inference backend: vLLM (Docker + NVIDIA "
                "toolkit) on GPU, or a llama-server binary on CPU. See "
                "docs/bubble-and-inpaint-plan.md."
            ) from exc
        self._predictor = RecognitionPredictor(SuryaInferenceManager())

    def recognize(self, image_path: Path, blocks: Sequence[TextBlock]) -> list[TextBlock]:
        """Fill block text from Surya's page OCR result."""
        from PIL import Image

        with Image.open(image_path) as handle:
            page = handle.convert("RGB")
        predictions = self._predictor([page])
        if not predictions:
            return list(blocks)
        results = getattr(predictions[0], "blocks", None) or []

        for block in blocks:
            best_text, best_score = "", 0.0
            for result in results:
                box = _bbox(result)
                if box is None:
                    continue
                score = overlap(box, block.bbox)
                if score > best_score:
                    best_text, best_score = _block_text(result), score
            if best_score >= MIN_MATCH and best_text:
                block.text = best_text
                confidence = getattr(results[0], "confidence", None) if results else None
                block.confidence = float(confidence) if confidence is not None else 0.6
            elif not block.text.strip():
                block.needs_review = True
        return list(blocks)
