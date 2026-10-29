"""Tests for the two-engine OCR combiner (fake engines, no models)."""

from __future__ import annotations

from pathlib import Path

from mangatl.adapters.ocr.hybrid import HybridOcr, weak
from mangatl.domain.block import TextBlock


class FakeOcr:
    def __init__(self, mapping: dict[int, str]) -> None:
        self.mapping = mapping
        self.calls = 0

    def recognize(self, image_path: Path, blocks):
        self.calls += 1
        for block in blocks:
            block.text = self.mapping.get(block.id, "")
        return list(blocks)


def make_blocks(count: int) -> list[TextBlock]:
    return [TextBlock(id=index, bbox=(0, 0, 10, 10)) for index in range(count)]


def test_weak_detects_empty_short_and_garbled() -> None:
    assert weak("")
    assert weak("と")
    assert weak("ｒＪＳｍｅｔｔｅｒｄＰｌｌｙｐ")
    assert not weak("おはよう")


def test_fallback_reads_what_primary_missed() -> None:
    primary = FakeOcr({0: "おはよう", 1: ""})
    fallback = FakeOcr({1: "こんばんは"})
    hybrid = HybridOcr(primary, fallback)

    blocks = hybrid.recognize(Path("x.png"), make_blocks(2))

    assert blocks[0].text == "おはよう"
    assert blocks[1].text == "こんばんは"


def test_fallback_never_blanks_a_good_read() -> None:
    primary = FakeOcr({0: "おはよう"})
    fallback = FakeOcr({0: ""})
    hybrid = HybridOcr(primary, fallback)

    blocks = hybrid.recognize(Path("x.png"), make_blocks(1))

    assert blocks[0].text == "おはよう"


def test_unreadable_block_is_flagged_not_invented() -> None:
    hybrid = HybridOcr(FakeOcr({0: ""}), FakeOcr({0: ""}))

    blocks = hybrid.recognize(Path("x.png"), make_blocks(1))

    assert blocks[0].text == ""
    assert blocks[0].needs_review is True


def test_good_primary_skips_the_fallback() -> None:
    fallback = FakeOcr({})
    hybrid = HybridOcr(FakeOcr({0: "おはよう"}), fallback)

    hybrid.recognize(Path("x.png"), make_blocks(1))

    assert fallback.calls == 0
