"""Tests for the optional Surya adapter (fake predictor, no backend)."""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

from mangatl.adapters.ocr.surya import SuryaOcr, overlap
from mangatl.domain.block import TextBlock


class FakePredictor:
    def __init__(self, blocks) -> None:
        self._blocks = blocks

    def __call__(self, _images):
        return [SimpleNamespace(blocks=self._blocks)]


def make_ocr(blocks) -> SuryaOcr:
    ocr = SuryaOcr.__new__(SuryaOcr)  # bypass the real backend import
    ocr._predictor = FakePredictor(blocks)
    return ocr


def block(bbox) -> TextBlock:
    return TextBlock(id=0, bbox=bbox)


def test_line_inside_block_is_attached(tmp_path: Path) -> None:
    from PIL import Image

    page = tmp_path / "p.png"
    Image.new("RGB", (200, 200), (255, 255, 255)).save(page)
    ocr = make_ocr([SimpleNamespace(bbox=(10, 10, 190, 60), text="こんにちは")])

    result = ocr.recognize(page, [block((0, 0, 200, 80))])

    assert result[0].text == "こんにちは"


def test_line_outside_block_is_ignored(tmp_path: Path) -> None:
    from PIL import Image

    page = tmp_path / "p.png"
    Image.new("RGB", (200, 200), (255, 255, 255)).save(page)
    ocr = make_ocr([SimpleNamespace(bbox=(10, 120, 190, 180), text="ちがう")])

    result = ocr.recognize(page, [block((0, 0, 200, 80))])

    assert result[0].text == ""
    assert result[0].needs_review is True


def test_html_is_used_when_text_is_missing(tmp_path: Path) -> None:
    from PIL import Image

    page = tmp_path / "p.png"
    Image.new("RGB", (200, 200), (255, 255, 255)).save(page)
    ocr = make_ocr([SimpleNamespace(bbox=(10, 10, 190, 60), html="<p>おはよう</p>")])

    result = ocr.recognize(page, [block((0, 0, 200, 80))])

    assert result[0].text == "<p>おはよう</p>"


def test_overlap_is_relative_to_the_line() -> None:
    assert overlap((10, 10, 50, 30), (0, 0, 100, 100)) == 1.0
    assert overlap((90, 10, 130, 30), (0, 0, 100, 100)) == 0.25
    assert overlap((200, 200, 260, 260), (0, 0, 100, 100)) == 0.0
