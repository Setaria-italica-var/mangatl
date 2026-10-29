"""Tests for manual style overrides (pure, no Qt)."""

from __future__ import annotations

from mangatl.render.style import TextStyle, apply_overrides


def base() -> TextStyle:
    return TextStyle(
        fg=(10, 10, 10),
        bg=(250, 250, 250),
        font_size=30,
        stroke_width=2,
        weight="regular",
        category="sans",
        italic=False,
        align="center",
    )


def test_empty_override_keeps_estimate() -> None:
    assert apply_overrides(base(), {}) == base()


def test_size_and_colours_override() -> None:
    style = apply_overrides(base(), {"font_size": 44, "fg": "#ff0000", "bg": "#00ff00"})

    assert style.font_size == 44
    assert style.fg == (255, 0, 0)
    assert style.bg == (0, 255, 0)


def test_bold_italic_align_and_font() -> None:
    style = apply_overrides(
        base(), {"bold": True, "italic": True, "align": "left", "font": "serif"}
    )

    assert style.weight == "bold"
    assert style.italic is True
    assert style.align == "left"
    assert style.category == "serif"


def test_stroke_can_be_zero() -> None:
    style = apply_overrides(base(), {"stroke": 0})

    assert style.stroke_width == 0


def test_invalid_colour_falls_back_to_black() -> None:
    style = apply_overrides(base(), {"fg": "not-a-colour"})

    assert style.fg == (0, 0, 0)
