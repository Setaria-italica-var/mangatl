"""Choose a font size and line breaks that fit a bubble.

The fitter shrinks the text until it fits, in a fixed order that mirrors how a
letterer works:

1. lower the size (binary search between the measured source size and a floor);
2. tighten the line spacing a little;
3. give up and allow the text to overflow with a ``needs_review`` flag.

It never truncates text: a bubble with too much text gets smaller glyphs, not
missing words.
"""

from __future__ import annotations

from dataclasses import dataclass

from mangatl.render import fonts, linebreak


@dataclass(frozen=True)
class FitResult:
    """A layout that fits, or the closest attempt when nothing did."""

    lines: list[str]
    font_size: int
    line_height: float
    overflow: bool = False


def _measure_factory(font_ref: fonts.FontRef, size: int):
    font = fonts.load(font_ref, size)

    def measure(text: str) -> float:
        return float(font.getlength(text))

    return font, measure


def fit_horizontal(
    text: str,
    box_width: float,
    box_height: float,
    font_ref: fonts.FontRef,
    start_size: int,
    *,
    min_size: int = 9,
    line_spacing: float = 1.15,
) -> FitResult:
    """Return the largest font size whose wrapped lines fit ``box``."""
    size = max(min_size, int(start_size))
    best: FitResult | None = None

    while size >= min_size:
        _font, measure = _measure_factory(font_ref, size)
        line_height = size * line_spacing
        lines = linebreak.wrap_horizontal(text, box_width, measure)
        candidate = FitResult(lines=lines, font_size=size, line_height=line_height)
        if linebreak.fits(lines, box_width, line_height, box_height, measure):
            return candidate
        best = candidate
        size = int(size * 0.92)

    if best is None:
        _font, measure = _measure_factory(font_ref, min_size)
        best = FitResult(
            lines=linebreak.wrap_horizontal(text, box_width, measure),
            font_size=min_size,
            line_height=min_size * line_spacing,
        )
    return FitResult(best.lines, best.font_size, best.line_height, overflow=True)


def _vertical_measure(size: int):
    """Advance measuring along a column: one em per character."""
    advance = size * 1.02

    def measure(text: str) -> float:
        return len(text) * advance

    return measure


def fit_vertical(
    text: str,
    box_width: float,
    box_height: float,
    font_ref: fonts.FontRef,
    start_size: int,
    *,
    min_size: int = 9,
    column_spacing: float = 1.1,
) -> FitResult:
    """Return the largest size whose columns fit right-to-left in ``box``."""
    size = max(min_size, int(start_size))

    while size >= min_size:
        _font, measure = _measure_factory(font_ref, size)
        # Along a vertical column the advance is one em per character; the
        # font's horizontal width would badly overestimate the column length.
        columns = linebreak.wrap_vertical(text, box_height, _vertical_measure(size))
        column_width = size * column_spacing
        if len(columns) * column_width <= box_width:
            return FitResult(lines=columns, font_size=size, line_height=column_width)
        size = int(size * 0.92)

    _font, measure = _measure_factory(font_ref, min_size)
    return FitResult(
        lines=linebreak.wrap_vertical(text, box_height, _vertical_measure(min_size)),
        font_size=min_size,
        line_height=min_size * column_spacing,
        overflow=True,
    )
