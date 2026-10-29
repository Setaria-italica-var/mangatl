"""Tests for page status labels (no Qt widgets)."""

from __future__ import annotations

from mangatl.domain.block import TextBlock
from mangatl.domain.project import Page
from mangatl.gui.pages import page_status, tab_label


def page(**stage) -> Page:
    p = Page(name="001.jpg")
    p.stage.update({key: 1 for key in stage})
    return p


def test_empty_page() -> None:
    assert page_status(Page(name="001.jpg")) == "empty"


def test_partial_page() -> None:
    assert page_status(page(detect=1, ocr=1)) == "partial"


def test_done_page() -> None:
    assert page_status(page(detect=1, ocr=1, translate=1, erase=1, render=1)) == "done"


def test_review_wins_over_done() -> None:
    p = page(detect=1, ocr=1, translate=1, erase=1, render=1)
    p.blocks.append(TextBlock(id=0, bbox=(0, 0, 10, 10), needs_review=True))

    assert page_status(p) == "review"


def test_tab_label_contains_number_and_glyph() -> None:
    label = tab_label(page(detect=1))

    assert label.startswith("001")
    assert label.split()[-1] == "◐"
