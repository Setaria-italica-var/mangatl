"""How much a string looks like real Japanese, without any model.

OCR failures on decorative lettering are easy to spot statistically: the output is
dominated by half/full-width Latin noise, has almost no kana, repeats the same
glyph, or is a single stray character. A plausibility score lets the pipeline
compare two engines' candidates and refuse to letter rubbish.

The score is deliberately simple and explainable; it is a *filter*, not a
recogniser, and it never invents text.

>>> round(plausibility("おはよう、元気？"), 2) > 0.7
True
>>> plausibility("ｒＪＳｍｅｔｔｅｒｄＰｌｌｙｐ") < 0.3
True
"""

from __future__ import annotations

import unicodedata

# Decorative marks that legitimately appear in manga dialogue.
DECORATION = set("♥♡★☆♪〜～…‥・ー—―！？!?、。，．,.．「」『』（）()【】[]〈〉《》″′：；:;")

PUNCTUATION = set("、。，．,.!?！？；：:;・ー…‥〜～「」『』（）()[]【】〈〉《》\"'“”‘’")


def _script_counts(text: str) -> dict[str, int]:
    counts = {"kana": 0, "kanji": 0, "latin": 0, "digit": 0, "other": 0}
    for char in text:
        if char.isspace():
            continue
        if char in PUNCTUATION or char in DECORATION:
            continue
        name = unicodedata.name(char, "")
        if name.startswith(("HIRAGANA", "KATAKANA")):
            counts["kana"] += 1
        elif "IDEOGRAPH" in name:
            counts["kanji"] += 1
        elif char.isascii() and char.isalpha():
            counts["latin"] += 1
        elif char.isdigit():
            counts["digit"] += 1
        else:
            fullwidth = 0xFF01 <= ord(char) <= 0xFF5E
            if fullwidth and (chr(ord(char) - 0xFEE0).isalnum()):
                counts["latin"] += 1
            else:
                counts["other"] += 1
    return counts


def _longest_run(text: str) -> int:
    best, current, previous = 1, 1, ""
    for char in text:
        if char == previous:
            current += 1
            best = max(best, current)
        else:
            current, previous = 1, char
    return best


def plausibility(text: str) -> float:
    """Score in ``0..1``: how likely this is real Japanese text.

    Combines the script mix (kana/kanji versus Latin noise), repetition and
    length. Decorations and punctuation are ignored.
    """
    stripped = text.strip()
    if not stripped:
        return 0.0
    counts = _script_counts(stripped)
    letters = counts["kana"] + counts["kanji"] + counts["latin"] + counts["other"]
    if letters == 0:
        return 0.2 if any(char in DECORATION for char in stripped) else 0.0

    japanese = (counts["kana"] + counts["kanji"]) / letters
    score = 0.15 + 0.7 * japanese
    if counts["latin"] and japanese < 0.2:
        score *= 0.5
    if _longest_run(stripped) >= 3:
        score *= 0.6
    if letters < 2:
        score *= 0.5
    if counts["other"] > letters * 0.3:
        score *= 0.6

    # Full-width and half-width Latin in one string is the classic OCR-noise
    # signature, and never appears in real dialogue.
    has_full = any(0xFF21 <= ord(char) <= 0xFF5A for char in stripped)
    has_half = any(char.isascii() and char.isalpha() for char in stripped)
    if has_full and has_half:
        score *= 0.2
    fullwidth_latin = sum(1 for char in stripped if 0xFF21 <= ord(char) <= 0xFF5A)
    if letters and fullwidth_latin / letters > 0.2:
        score *= 0.5
    return max(0.0, min(1.0, score))
