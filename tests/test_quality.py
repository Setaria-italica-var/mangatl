"""Tests for the OCR quality gates."""

from __future__ import annotations

from mangatl.domain.quality import has_content, kana_ratio, latin_ratio, looks_garbled


def test_engine_noise_is_garbled() -> None:
    assert looks_garbled("ｒＪＳｍｅｔｔｅｒｄＰｌｌｙｐ")


def test_mixed_fullwidth_and_halfwidth_letters_are_garbled() -> None:
    assert looks_garbled("ＮＨＰＮＨＥＷingの保製")


def test_dates_and_numbers_are_not_garbled() -> None:
    assert not looks_garbled("２０１８年")
    assert not looks_garbled("２０１７／１２／３１")
    assert not looks_garbled("2018")


def test_normal_japanese_is_not_garbled() -> None:
    assert not looks_garbled("おはよう、元気？")
    assert not looks_garbled("そういえば、")
    assert not looks_garbled("それは、ひどい")


def test_short_blocks_are_never_garbled() -> None:
    assert not looks_garbled("！！")
    assert not looks_garbled("")


def test_ratios() -> None:
    assert latin_ratio("abc") == 1.0
    assert latin_ratio("あいう") == 0.0
    assert kana_ratio("あいう") == 1.0
    assert kana_ratio("abc") == 0.0


def test_has_content_ignores_punctuation() -> None:
    assert not has_content("……")
    assert has_content("はい")
    assert has_content("2018")


def test_hallucination_rejects_dates() -> None:
    from mangatl.domain.quality import looks_like_hallucination

    assert looks_like_hallucination("2024年1月1日", "これより")
    assert looks_like_hallucination("1/1/2024", "おはよう")
    assert not looks_like_hallucination("2024年", "2025年")


def test_hallucination_rejects_losing_japanese() -> None:
    from mangatl.domain.quality import looks_like_hallucination

    assert looks_like_hallucination("ABC 123", "あいう")
    assert not looks_like_hallucination("接下来 各位", "これより")
