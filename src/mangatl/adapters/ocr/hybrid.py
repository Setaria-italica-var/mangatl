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
        self.primary.recognize(image_path, blocks)
        suspects = [block for block in blocks if weak(block.text)]
        if not suspects:
            return list(blocks)

        before = {id(block): block.text for block in suspects}
        with contextlib.suppress(Exception):  # a broken fallback must not fail the page
            self.fallback.recognize(image_path, suspects)

        for block in suspects:
            # Keep whichever engine produced more text; never let the fallback
            # blank a block that the primary engine did read.
            if weak(block.text):
                block.text = before[id(block)]
            if not block.text.strip():
                block.needs_review = True
                block.confidence = 0.0
        return list(blocks)
