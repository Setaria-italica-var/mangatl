"""Two-engine OCR: read with manga-ocr, rescue weak blocks with RapidOCR.

manga-ocr is excellent on clean dialogue but hallucinates or returns nothing on
stylised lettering, small furigana and inverted (white-on-black) text. RapidOCR
uses a different architecture and preprocessing, so it fails differently.

The hybrid keeps the stronger result per block:

* empty or one-character results count as weak and are re-read;
* a RapidOCR result replaces a garbled manga-ocr one;
* when both fail the block is flagged ``needs_review`` and, because the pipeline
  refuses to erase without a translation, the original text stays on the page.
"""

from __future__ import annotations

import contextlib
from collections.abc import Sequence
from pathlib import Path

from mangatl.domain.block import TextBlock
from mangatl.domain.plausibility import plausibility
from mangatl.domain.quality import looks_garbled

MIN_LENGTH = 2


def weak(text: str) -> bool:
    """Whether a result is too poor to translate."""
    stripped = text.strip()
    return len(stripped) < MIN_LENGTH or looks_garbled(stripped)


class HybridOcr:
    """manga-ocr first, RapidOCR for the blocks it cannot read."""

    name = "hybrid"

    def __init__(self, primary=None, fallback=None) -> None:
        if primary is None:
            from mangatl.adapters.ocr.manga_ocr import MangaOcrAdapter

            primary = MangaOcrAdapter()
        if fallback is None:
            from mangatl.adapters.ocr.rapid import RapidOcrAdapter

            fallback = RapidOcrAdapter()
        self.primary = primary
        self.fallback = fallback

    def recognize(self, image_path: Path, blocks: Sequence[TextBlock]) -> list[TextBlock]:
        """Fill block text, preferring whichever engine reads more."""
        primary_name = getattr(self.primary, "name", "primary")
        fallback_name = getattr(self.fallback, "name", "fallback")
        self.primary.recognize(image_path, blocks)
        for block in blocks:
            if block.text.strip():
                block.ocr_candidates = [(primary_name, block.text.strip())]
                block.ocr_source = primary_name
        suspects = [block for block in blocks if weak(block.text)]
        if not suspects:
            return list(blocks)

        before = {id(block): block.text for block in suspects}
        with contextlib.suppress(Exception):  # a broken fallback must not fail the page
            self.fallback.recognize(image_path, suspects)

        for block in suspects:
            # Keep whichever candidate looks more like Japanese; never let the
            # fallback blank a block the primary engine did read.
            primary_text = before[id(block)]
            fallback_text = block.text
            if plausibility(fallback_text) < plausibility(primary_text):
                block.text = primary_text
            candidates = [(primary_name, primary_text.strip())]
            if fallback_text.strip() and fallback_text.strip() != primary_text.strip():
                candidates.append((fallback_name, fallback_text.strip()))
            block.ocr_candidates = candidates
            block.ocr_source = (
                fallback_name if block.text == fallback_text else primary_name
            )
            if plausibility(block.text) < 0.5:
                block.needs_review = True
            if not block.text.strip():
                block.confidence = 0.0
        return list(blocks)


class FusionOcr:
    """Run two engines on every block and keep the more plausible reading.

    Unlike :class:`HybridOcr`, the second engine is not gated by a heuristic: both
    models are strong but fail on different lettering, so comparing their outputs
    directly is the most reliable rule.
    """

    name = "fusion"

    def __init__(self, primary=None, fallback=None) -> None:
        if primary is None or fallback is None:
            raise ValueError("FusionOcr needs two engines")
        self.primary = primary
        self.fallback = fallback

    def recognize(self, image_path: Path, blocks: Sequence[TextBlock]) -> list[TextBlock]:
        """Read with both engines and pick per block by plausibility."""
        self.primary.recognize(image_path, blocks)
        first = {id(block): block.text for block in blocks}
        self.fallback.recognize(image_path, blocks)

        primary_name = getattr(self.primary, "name", "primary")
        fallback_name = getattr(self.fallback, "name", "fallback")
        for block in blocks:
            left = first[id(block)].strip()
            right = block.text.strip()
            left_score = plausibility(left)
            right_score = plausibility(right)
            # A two-character reading of a wide block is usually a model failure;
            # the other engine saw more text.
            if len(left) < 0.5 * len(right) and right_score >= 0.6:
                left_score = min(left_score, right_score - 0.2)
            elif len(right) < 0.5 * len(left) and left_score >= 0.6:
                right_score = min(right_score, left_score - 0.2)
            if left_score >= right_score:
                block.text, block.ocr_score = left, left_score
                block.ocr_source = primary_name
            else:
                block.text, block.ocr_score = right, right_score
                block.ocr_source = fallback_name
            candidates = []
            if left:
                candidates.append((primary_name, left))
            if right and right != left:
                candidates.append((fallback_name, right))
            block.ocr_candidates = candidates
            if block.ocr_score < 0.45:
                block.needs_review = True
        return list(blocks)
