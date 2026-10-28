"""Tests for line breaking and font fitting (no fonts required for wrapping)."""

from __future__ import annotations

import pytest

from mangatl.render import fonts
from mangatl.render.layout import fit_horizontal, fit_vertical
from mangatl.render.linebreak import fits, wrap_horizontal, wrap_vertical


def measure(text: str) -> float:
    """One monospaced cell per character, so expectations stay exact."""
    return len(text) * 10.0


def test_wrap_breaks_on_width() -> None:
    assert wrap_horizontal("你好世界", 20, measure) == ["你好", "世界"]


def test_wrap_keeps_latin_words_whole() -> None:
    assert wrap_horizontal("hello world", 50, measure) == ["hello", "world"]
    assert wrap_horizontal("don't stop", 30, measure) == ["don't", "stop"]


def test_closing_punctuation_never_starts_a_line() -> None:
    lines = wrap_horizontal("你好，世界。", 30, measure)

    assert lines == ["你好，", "世界。"]
    assert all(line[0] not in "，。" for line in lines)


def test_opening_punctuation_never_ends_a_line() -> None:
    lines = wrap_horizontal("「你好世界」", 20, measure)

    assert all(line[-1] not in "「" for line in lines)


def test_explicit_newlines_are_kept() -> None:
    assert wrap_horizontal("第一行\n第二行", 100, measure) == ["第一行", "第二行"]


def test_vertical_wrap_produces_columns() -> None:
    columns = wrap_vertical("竖排测试文字", 30, measure)

    assert columns == ["竖排测", "试文字"]


def test_fits_detects_overflow() -> None:
    assert fits(["你好"], 20, 12, 20, measure)
    assert not fits(["你好", "世界"], 20, 12, 20, measure)


@pytest.mark.skipif(fonts.resolve("sans") is None, reason="no CJK font installed")
def test_fit_shrinks_until_it_fits() -> None:
    font = fonts.resolve("sans")
    assert font is not None

    result = fit_horizontal("这是一句很长的中文台词，需要自动断行才能放进气泡。", 120, 90, font, 40)

    assert not result.overflow
    assert result.font_size < 40
    assert len(result.lines) >= 2


@pytest.mark.skipif(fonts.resolve("sans") is None, reason="no CJK font installed")
def test_vertical_fit_uses_columns() -> None:
    font = fonts.resolve("sans")
    assert font is not None

    result = fit_vertical("竖排测试文字", 200, 200, font, 24)

    assert len(result.lines) == 1
    assert result.font_size >= 9
