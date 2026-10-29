"""Quality gates for OCR and translated text.

Two failure modes ruin a page even when detection is perfect:

* the OCR engine invents Latin-looking noise on stylised lettering
  (``ｒＪＳｍｅｔｔｅｒｄＰｌｌｙｐ``) and the translator faithfully translates the noise;
* a block is erased although nothing will be drawn back, leaving an empty bubble.

The helpers here are small, pure and easy to tune from real pages.
"""

from __future__ import annotations

import unicodedata

GARBLED_LATIN_RATIO = 0.5
GARBLED_KANA_RATIO = 0.1


def _fullwidth_latin(char: str) -> bool:
    code = ord(char)
    return 0xFF21 <= code <= 0xFF3A or 0xFF41 <= code <= 0xFF5A or 0xFF10 <= code <= 0xFF19


def _halfwidth_letter(char: str) -> bool:
    return char.isascii() and char.isalpha()


def _kanji(char: str) -> bool:
    return "IDEOGRAPH" in unicodedata.name(char, "")


def _counts(text: str) -> tuple[int, int, int, int]:
    """``(fullwidth latin, halfwidth letters, kanji, visible)`` character counts."""
    visible = [char for char in text if not char.isspace()]
    full = sum(1 for char in visible if _fullwidth_latin(char))
    half = sum(1 for char in visible if _halfwidth_letter(char))
    kanji = sum(1 for char in visible if _kanji(char))
    return full, half, kanji, len(visible)


def latin_ratio(text: str) -> float:
    """Share of characters that are Latin letters/digits (half or full width)."""
    full, half, _kanji_count, visible = _counts(text)
    return (full + half) / visible if visible else 0.0


def kana_ratio(text: str) -> float:
    """Share of hiragana/katakana characters."""
    visible = [char for char in text if not char.isspace()]
    if not visible:
        return 0.0
    count = sum(
        1
        for char in visible
        if unicodedata.name(char, "").startswith(("HIRAGANA", "KATAKANA"))
    )
    return count / len(visible)


def looks_garbled(text: str) -> bool:
    """Whether a recognition result looks like engine noise rather than a sentence.

    The reliable signature is a mix of full-width and half-width Latin letters, or
    a Latin-dominated string with no kana and no kanji. Numbers alone (``２０１８年``)
    must never match: dates and names are legitimate dialogue.

    >>> looks_garbled("ｒＪＳｍｅｔｔｅｒｄＰｌｌｙｐ")
    True
    >>> looks_garbled("２０１８年")
    False
    >>> looks_garbled("おはよう、元気？")
    False
    """
    stripped = text.strip()
    if len(stripped) < 4:
        return False
    visible = [char for char in stripped if not char.isspace()]
    if sum(1 for char in visible if char.isalpha()) < 2:
        return False  # pure numbers and punctuation (dates, page marks)
    full, half, kanji, _visible = _counts(stripped)
    if full >= 1 and half >= 2:
        return True
    return (
        latin_ratio(stripped) >= GARBLED_LATIN_RATIO
        and kana_ratio(stripped) <= GARBLED_KANA_RATIO
        and kanji == 0
    )


def has_content(text: str) -> bool:
    """Whether there is something worth lettering back (not just punctuation)."""
    visible = [char for char in text if not char.isspace()]
    return any(char.isalnum() for char in visible)
