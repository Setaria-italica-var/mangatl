"""Tests for the bubble-level re-read of implausibly short text."""

from __future__ import annotations

from pathlib import Path

from mangatl.core.pipeline import PipelineService
from mangatl.domain.block import TextBlock
from mangatl.domain.project import Page


class FakeOcr:
    name = "fake"

    def __init__(self, text: str) -> None:
        self.text = text
        self.calls = 0

    def recognize(self, image_path, blocks):
        self.calls += 1
        for block in blocks:
            block.text = self.text
            block.ocr_source = self.name
        return list(blocks)


def service(ocr) -> PipelineService:
    return PipelineService(
        project=None, detector=None, ocr=ocr, inpainter=None  # type: ignore[arg-type]
    )


def page_with(block: TextBlock) -> Page:
    return Page(name="p", blocks=[block])


def test_short_text_in_a_large_bubble_is_reread() -> None:
    block = TextBlock(
        id=0,
        bbox=(100, 100, 147, 300),
        text="た",
        vertical=True,
        in_bubble=True,
        bubble_bbox=(60, 80, 250, 400),
        ocr_source="fake",
    )
    ocr = FakeOcr("これは長い文章です")
    service(ocr)._recheck_short_blocks(page_with(block), Path("x.png"))

    assert ocr.calls == 1
    assert block.text == "これは長い文章です"
    assert block.ocr_source.endswith("+bubble")


def test_long_text_is_not_reread() -> None:
    block = TextBlock(
        id=0,
        bbox=(100, 100, 147, 300),
        text="これは十分に長い文章です",
        vertical=True,
        in_bubble=True,
        bubble_bbox=(60, 80, 250, 400),
        ocr_source="fake",
    )
    ocr = FakeOcr("別の文章")
    service(ocr)._recheck_short_blocks(page_with(block), Path("x.png"))

    assert ocr.calls == 0
