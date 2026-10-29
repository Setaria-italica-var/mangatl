"""Offline stubs used by the M0 spike and by tests.

They deliberately avoid every third-party dependency: no Pillow, no numpy, no
torch. That keeps the pipeline runnable on a freshly created venv and makes the
orchestration testable before the real models are wired in.

>>> stub = GridDetector(columns=2, rows=2, page_size=(200, 400))
>>> len(stub.detect(__import__("pathlib").Path("page.png")))
4
"""

from __future__ import annotations

import shutil
from collections.abc import Sequence
from pathlib import Path

from mangatl.domain.block import TextBlock


class GridDetector:
    """Split the page into a fixed grid, ignoring the image content."""

    name = "grid"

    def __init__(
        self,
        columns: int = 2,
        rows: int = 2,
        page_size: tuple[int, int] = (1200, 1600),
    ) -> None:
        self.columns = columns
        self.rows = rows
        self.page_size = page_size

    def detect(self, image_path: Path) -> list[TextBlock]:
        """Return ``columns * rows`` blocks covering the assumed page size."""
        width, height = self.page_size
        cell_w, cell_h = width // self.columns, height // self.rows
        blocks: list[TextBlock] = []
        for row in range(self.rows):
            for column in range(self.columns):
                x1, y1 = column * cell_w, row * cell_h
                corners = [
                    (x1, y1),
                    (x1 + cell_w, y1),
                    (x1 + cell_w, y1 + cell_h),
                    (x1, y1 + cell_h),
                ]
                blocks.append(
                    TextBlock(
                        id=len(blocks),
                        bbox=(x1, y1, x1 + cell_w, y1 + cell_h),
                        lines=[corners],
                    )
                )
        return blocks


class EchoOcr:
    """Fill ``text`` with a deterministic placeholder instead of reading pixels."""

    name = "echo"

    def recognize(self, image_path: Path, blocks: Sequence[TextBlock]) -> list[TextBlock]:
        """Return blocks whose text encodes the page and block id."""
        stem = Path(image_path).stem
        for block in blocks:
            block.text = f"{stem}#{block.id}"
            block.confidence = 0.5
            block.needs_review = True
        return list(blocks)


class CopyInpainter:
    """Copy the page unchanged; stands in for LaMa until models are wired in."""

    name = "copy"

    def erase(
        self,
        image_path: Path,
        destination: Path,
        blocks: Sequence[TextBlock] = (),
        mask=None,
    ) -> None:
        """Copy ``image_path`` to ``destination``, creating parents as needed."""
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(image_path, destination)


class CopyTranslator:
    """Deterministic stand-in used when the translate stage is not requested."""

    name = "copy"

    def translate(self, blocks, context=None):
        for block in blocks:
            block.translation = block.text
        return list(blocks)
