"""Tests for block role classification (dialogue / SFX / texture)."""

from __future__ import annotations

import pytest

from mangatl.domain.roles import BlockRole, RoleConfig, classify


@pytest.mark.parametrize(
    "text",
    [
        "おはよう、元気？",
        "I'll be back before sunrise.",
        "待って！",
        "そうか……",
    ],
)
def test_sentences_are_dialogue(text: str) -> None:
    decision = classify(text)

    assert decision.role is BlockRole.DIALOGUE
    assert decision.should_translate
    assert decision.should_erase


@pytest.mark.parametrize("text", ["ゴゴゴ", "ドン！", "!!", "ざわ…ざわ"])
def test_onomatopoeia_is_sfx(text: str) -> None:
    decision = classify(text)

    assert decision.role is BlockRole.SFX
    assert not decision.should_translate
    assert decision.should_erase  # SFX is redrawn as artwork, not translated


def test_empty_text_is_texture_and_kept() -> None:
    decision = classify("", confidence=0.2, mask_coverage=0.0)

    assert decision.role is BlockRole.TEXTURE
    assert not decision.should_erase


def test_pure_symbols_are_texture() -> None:
    decision = classify("—— ~~~ ***")

    assert decision.role is BlockRole.TEXTURE
    assert decision.should_erase is False


def test_long_text_with_elongation_stays_dialogue() -> None:
    decision = classify("ちょっと待ってくださいよーー！")

    assert decision.role is BlockRole.DIALOGUE


def test_short_kana_with_punctuation_is_dialogue() -> None:
    decision = classify("え？")

    assert decision.role is BlockRole.DIALOGUE


def test_low_confidence_without_mask_is_texture() -> None:
    decision = classify("なにか", confidence=0.1, mask_coverage=0.0)

    assert decision.role is BlockRole.TEXTURE
    assert "weak-evidence" in decision.reasons


def test_thresholds_are_configurable() -> None:
    config = RoleConfig(max_sfx_length=2)

    assert classify("ドド", config=config).role is BlockRole.SFX
    assert classify("ドドド", config=config).role is BlockRole.DIALOGUE
