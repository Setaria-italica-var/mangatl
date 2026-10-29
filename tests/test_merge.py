"""Tests for merging OCR fragments that belong to one bubble."""

from __future__ import annotations

from mangatl.domain.block import TextBlock
from mangatl.domain.merge import merge_blocks


def block(index: int, bbox, text: str, vertical: bool = False, **kwargs) -> TextBlock:
    return TextBlock(id=index, bbox=bbox, text=text, vertical=vertical, **kwargs)


def test_adjacent_fragments_merge() -> None:
    blocks = [block(0, (10, 10, 100, 40), "こんにちは"), block(1, (10, 44, 100, 70), "元気？")]

    merged = merge_blocks(blocks)

    assert len(merged) == 1
    assert merged[0].text == "こんにちは元気？"
    assert merged[0].bbox == (10, 10, 100, 70)


def test_distant_blocks_stay_separate() -> None:
    blocks = [block(0, (10, 10, 100, 40), "ひとつめ"), block(1, (10, 300, 100, 330), "ふたつめ")]

    assert len(merge_blocks(blocks)) == 2


def test_different_orientation_never_merges() -> None:
    blocks = [
        block(0, (10, 10, 100, 40), "横"),
        block(1, (10, 44, 100, 70), "縦", vertical=True),
    ]

    assert len(merge_blocks(blocks)) == 2


def test_blocks_in_different_bubbles_never_merge() -> None:
    blocks = [
        block(0, (10, 10, 100, 40), "A", bubble_bbox=(0, 0, 120, 60)),
        block(1, (10, 44, 100, 70), "B", bubble_bbox=(0, 200, 120, 260)),
    ]

    assert len(merge_blocks(blocks)) == 2


def test_vertical_fragments_read_right_to_left() -> None:
    left = block(0, (10, 10, 40, 100), "左", vertical=True)
    right = block(1, (50, 10, 80, 100), "右", vertical=True)

    merged = merge_blocks([left, right])

    assert len(merged) == 1
    assert merged[0].text == "右左"
    assert merged[0].vertical is True


def test_merge_keeps_translation_and_flags() -> None:
    first = block(0, (10, 10, 100, 40), "A", translation="甲", needs_review=True)
    second = block(1, (10, 44, 100, 70), "B", translation="乙")

    merged = merge_blocks([first, second])[0]

    assert merged.translation == "甲乙"
    assert merged.needs_review is True
