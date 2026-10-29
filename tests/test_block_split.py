"""Tests for splitting a block that spans two nested bubbles."""

from __future__ import annotations

from mangatl.core.pipeline import _split_straddling_blocks
from mangatl.domain.block import TextBlock
from mangatl.domain.project import Page


def test_straddling_block_is_split_per_bubble() -> None:
    outer = (0, 0, 200, 300)
    inner = (100, 150, 200, 300)
    block = TextBlock(
        id=0,
        bbox=(0, 0, 200, 300),
        vertical=True,
        in_bubble=True,
        bubble_boxes=(outer, inner),
        bubble_bbox=outer,
    )
    page = Page(name="p", blocks=[block])

    _split_straddling_blocks(page)

    assert len(page.blocks) == 2
    assert [item.id for item in page.blocks] == [0, 1]
    assert all(item.in_bubble for item in page.blocks)


def test_normal_block_is_untouched() -> None:
    block = TextBlock(id=0, bbox=(0, 0, 50, 100), vertical=True, in_bubble=True)
    page = Page(name="p", blocks=[block])

    _split_straddling_blocks(page)

    assert page.blocks == [block]
