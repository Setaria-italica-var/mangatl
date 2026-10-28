"""Tests for the erase policy (roles, confidence gates, no images needed)."""

from __future__ import annotations

from mangatl.core.config import RunConfig
from mangatl.core.pipeline import should_erase
from mangatl.domain.block import TextBlock


def make_block(**kwargs) -> TextBlock:
    values: dict = {"id": 0, "bbox": (0, 0, 100, 100)}
    values.update(kwargs)
    return TextBlock(**values)


def test_dialogue_is_erased() -> None:
    assert should_erase(make_block(role="dialogue", mask_coverage=0.4), RunConfig())


def test_texture_is_kept() -> None:
    assert not should_erase(make_block(role="texture", mask_coverage=0.4), RunConfig())


def test_symbol_is_erased() -> None:
    assert should_erase(make_block(role="symbol", mask_coverage=0.4), RunConfig())


def test_sfx_follows_policy() -> None:
    item = make_block(role="sfx", mask_coverage=0.4)

    assert should_erase(item, RunConfig(sfx_policy="erase"))
    assert not should_erase(item, RunConfig(sfx_policy="keep"))


def test_empty_box_is_skipped_even_if_dialogue() -> None:
    # Detector artefact: OCR returned text, but almost no text pixels inside.
    assert not should_erase(make_block(role="dialogue", mask_coverage=0.005), RunConfig())


def test_oversized_block_erases_mask_only() -> None:
    item = make_block(role="dialogue", mask_coverage=0.05, area_fraction=0.8, bbox_erase=False)

    assert should_erase(item, RunConfig())
    assert not item.bbox_erase  # the artwork underneath must survive
