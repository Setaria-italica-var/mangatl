"""Tests for the model-free Japanese plausibility score."""

from __future__ import annotations

from mangatl.domain.plausibility import plausibility


def test_dialogue_scores_high() -> None:
    assert plausibility("おはよう、元気？") >= 0.7
    assert plausibility("そういえば、") >= 0.7


def test_latin_noise_scores_low() -> None:
    assert plausibility("ｒＪＳｍｅｔｔｅｒｄＰｌｌｙｐ") < 0.2
    assert plausibility("ＭＳＣＲＭＡＮＡＰ聖Ｖに懸册一") < 0.4


def test_punctuation_only_scores_low() -> None:
    assert plausibility("。。") < 0.3
    assert plausibility("") == 0.0


def test_single_character_is_penalised() -> None:
    assert plausibility("あ") < 0.5


def test_hearts_do_not_ruin_plausibility() -> None:
    assert plausibility("無理っ♥") >= 0.6


def test_katakana_sfx_is_acceptable() -> None:
    assert plausibility("ゴゴゴ") >= 0.5
