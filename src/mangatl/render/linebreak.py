"""Line breaking for horizontal and vertical Chinese/Japanese text.

Two rules matter for comic lettering:

* **kinsoku** - a line must not start with closing punctuation (``。、」``) and
  must not end with opening punctuation (``「（``);
* **no mid-word breaks** for Latin runs - "don't" stays whole.

Measurement is injected (``measure`` returns a width in pixels), so the same code
works for any font and stays testable without one.

>>> wrap_horizontal("你好世界", 100, lambda text: len(text) * 10)
['你好世界']
>>> wrap_horizontal("你好世界", 20, lambda text: len(text) * 10)
['你好', '世界']
"""

from __future__ import annotations

from collections.abc import Callable, Sequence

NO_LINE_START = set(
    "、。，．,.!?！？；：:;）)]」』】〕〉》”’ー"
    "ぁぃぅぇぉっゃゅょゎァィゥェォッャュョヮ…"
)
NO_LINE_END = set("（(「『【〔〈《“‘")

Measure = Callable[[str], float]


def _tokens(text: str) -> list[str]:
    """Split into CJK characters and whole Latin/number words."""
    tokens: list[str] = []
    buffer = ""
    for char in text:
        if char.isascii() and (char.isalnum() or char in "'-"):
            buffer += char
            continue
        if buffer:
            tokens.append(buffer)
            buffer = ""
        tokens.append(char)
    if buffer:
        tokens.append(buffer)
    return tokens


def _kinsoku(lines: list[list[str]]) -> list[list[str]]:
    """Push punctuation off the start/end of lines where possible."""
    for index in range(len(lines) - 1):
        line, following = lines[index], lines[index + 1]
        while line and following and following[0] in NO_LINE_START and len(line) > 1:
            following.insert(0, line.pop())
        while line and len(line) > 1 and line[-1] in NO_LINE_END:
            following.insert(0, line.pop())
    return lines


def wrap_horizontal(text: str, max_width: float, measure: Measure) -> list[str]:
    """Greedy wrap that respects kinsoku and never splits a Latin word."""
    paragraphs = text.split("\n")
    result: list[str] = []

    for paragraph in paragraphs:
        if not paragraph:
            result.append("")
            continue
        lines: list[list[str]] = [[]]
        for token in _tokens(paragraph):
            if not lines[-1] and token.isspace():
                continue  # never start a line with the space left by a wrap
            candidate = "".join(lines[-1]) + token
            if lines[-1] and measure(candidate) > max_width:
                if token.isspace():
                    continue  # dropping the space is what a wrap means
                lines.append([token])
            else:
                lines[-1].append(token)
        result.extend("".join(line).strip() for line in _kinsoku(lines))
    return result


def wrap_vertical(text: str, max_height: float, measure: Measure) -> list[str]:
    """Split into columns: each column is a string rendered top to bottom."""
    paragraphs = text.split("\n")
    columns: list[str] = []

    for paragraph in paragraphs:
        if not paragraph:
            columns.append("")
            continue
        current: list[str] = []
        for token in _tokens(paragraph):
            if current and measure("".join(current) + token) > max_height:
                columns.append("".join(current))
                current = [token]
            else:
                current.append(token)
        columns.append("".join(current))
    return columns


def fits(
    lines: Sequence[str],
    max_width: float,
    line_height: float,
    max_height: float,
    measure: Measure,
) -> bool:
    """Whether a wrapped block still fits the box."""
    if not lines:
        return True
    if len(lines) * line_height > max_height:
        return False
    return all(measure(line) <= max_width for line in lines)
