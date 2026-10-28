"""Decide what a detected block *is*, using the OCR result as evidence.

Three roles matter downstream:

``dialogue``
    Speech that should be translated and replaced.
``sfx``
    Onomatopoeia (``ゴゴゴ``, ``ドン``, ``!!``). Kept by default: replacing it with
    translated text usually ruins the page.
``texture``
    Anything that is not text: screentone, hatch marks, a decorative pattern, or
    a block the OCR could not read at all. Erasing it would destroy artwork.

The heuristics are deliberately conservative: when the evidence is weak the block
stays ``texture``, because keeping original pixels is recoverable and erasing
them is not.

>>> classify("おはよう、元気？").role.value
'dialogue'
>>> classify("ゴゴゴ").role.value
'sfx'
>>> classify("", confidence=0.1).role.value
'texture'
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from enum import StrEnum

KATAKANA = re.compile(r"[\u30a0-\u30ff\u31f0-\u31ff]")
KANA_OR_KANJI = re.compile(r"[\u3040-\u30ff\u3400-\u4dbf\u4e00-\u9fff]")
LATIN_OR_DIGIT = re.compile(r"[0-9A-Za-z]")
SENTENCE_PUNCT = re.compile(r"[。．、，,.!！?？…‥]")
ELONGATION = "ー〜~"
PUNCTUATION = re.compile(r"[\s\u3000・･ー〜～~…‥．。、，,.!！?？「」『』（）()\[\]【】]")



class BlockRole(StrEnum):
    """What a block contains, as far as the pipeline can tell."""

    DIALOGUE = "dialogue"
    SFX = "sfx"
    SYMBOL = "symbol"
    TEXTURE = "texture"


@dataclass(frozen=True)
class RoleDecision:
    """The verdict plus the evidence that produced it."""

    role: BlockRole
    reasons: tuple[str, ...] = ()

    @property
    def should_translate(self) -> bool:
        return self.role is BlockRole.DIALOGUE

    @property
    def should_erase(self) -> bool:
        """Everything that is text is erased; only decoration is left alone."""
        return self.role is not BlockRole.TEXTURE

    @property
    def should_translate_text(self) -> bool:
        """Dialogue and SFX are translated; symbols are copied verbatim."""
        return self.role in (BlockRole.DIALOGUE, BlockRole.SFX)


@dataclass(frozen=True)
class RoleConfig:
    """Thresholds for :func:`classify`."""

    max_sfx_length: int = 6
    katakana_ratio: float = 0.6
    repeat_ratio: float = 0.5
    low_confidence: float = 0.3
    min_mask_coverage: float = 0.01


TRANSLATABLE_ROLES = (BlockRole.DIALOGUE, BlockRole.SFX)


def is_translatable(role: str) -> bool:
    """Whether a stored role string should be sent to the translator."""
    try:
        return BlockRole(role) in TRANSLATABLE_ROLES
    except ValueError:
        return False


def _katakana_ratio(text: str) -> float:
    letters = [char for char in text if KANA_OR_KANJI.match(char) or LATIN_OR_DIGIT.match(char)]
    if not letters:
        return 0.0
    return sum(1 for char in letters if KATAKANA.match(char)) / len(letters)


def _repeated_motif(text: str, max_len: int) -> bool:
    """Whether a short text repeats a 2-3 character motif (``ざわ…ざわ``)."""
    if len(text) < 4 or len(text) > max_len + 2:
        return False
    for size in (2, 3):
        motif = text[:size]
        if text.count(motif) >= 2:
            return True
    return False


def _repeat_ratio(text: str) -> float:
    if len(text) < 2:
        return 0.0
    pairs = zip(text, text[1:], strict=False)
    return sum(1 for previous, current in pairs if previous == current) / (len(text) - 1)


def classify(
    text: str,
    *,
    confidence: float = 1.0,
    mask_coverage: float = 1.0,
    config: RoleConfig | None = None,
) -> RoleDecision:
    """Classify one block from its OCR text and the detector's mask coverage."""
    settings = config or RoleConfig()
    stripped = text.strip()

    if not stripped:
        if confidence < settings.low_confidence or mask_coverage < settings.min_mask_coverage:
            return RoleDecision(BlockRole.TEXTURE, ("empty-text", "weak-evidence"))
        return RoleDecision(BlockRole.TEXTURE, ("empty-text",))

    # Punctuation and the katakana middle dot carry no reading; strip them
    # before judging "is there text here at all".
    content = PUNCTUATION.sub("", stripped)
    if not content:
        # Punctuation still has to be removed from the page, but it is not
        # translated; keep it in its original form.
        return RoleDecision(BlockRole.SYMBOL, ("punctuation-only",))

    if not (KANA_OR_KANJI.search(content) or LATIN_OR_DIGIT.search(content)):
        return RoleDecision(BlockRole.SYMBOL, ("no-letters",))

    if confidence < settings.low_confidence and mask_coverage < settings.min_mask_coverage:
        return RoleDecision(BlockRole.TEXTURE, ("weak-evidence",))

    short = len(content) <= settings.max_sfx_length
    katakana = _katakana_ratio(content) >= settings.katakana_ratio
    repeated = _repeat_ratio(content) >= settings.repeat_ratio
    repeated_motif = _repeated_motif(content, max_len=settings.max_sfx_length)
    elongated = sum(stripped.count(char) for char in ELONGATION) >= 2
    no_sentence_punct = SENTENCE_PUNCT.search(stripped) is None

    if short and (katakana or repeated or repeated_motif or (elongated and no_sentence_punct)):
        reasons = ["short"]
        if katakana:
            reasons.append("katakana")
        if repeated or repeated_motif:
            reasons.append("repeated")
        if elongated:
            reasons.append("elongation")
        return RoleDecision(BlockRole.SFX, tuple(reasons))

    return RoleDecision(BlockRole.DIALOGUE, ("sentence-like",))
