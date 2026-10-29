"""LLM as a text judge for ambiguous OCR candidates.

Two OCR engines disagree most often exactly where lettering is decorative. The
candidates are both text, so a language model can often tell which one is real
Japanese without seeing the image at all — that keeps this layer cheap enough to
run on every suspicious block.

The judge only *chooses*. It never writes new text, so a bad model can at worst
pick the wrong candidate, which the plausibility score and the human review can
still catch.
"""

from __future__ import annotations

import json
from collections.abc import Sequence
from typing import Any

from mangatl.adapters.translators.openai_compat import LlmConfig, TranslationError, _Transport

SYSTEM_PROMPT = (
    "You are reviewing OCR candidates from a Japanese manga page. "
    "Each item lists the same text box read by different OCR engines. "
    "Pick the candidate that is real, grammatical Japanese; if all are noise, "
    "pick -1. Never rewrite, merge or translate the text. "
    'Reply with JSON only: {"picks":[{"id":<int>,"pick":<int>,"confidence":<0-1>}]}'
)


class LlmJudge:
    """Ask an OpenAI-compatible model which OCR candidate to trust."""

    name = "llm_judge"

    def __init__(self, config: LlmConfig | None = None, transport: Any = None) -> None:
        self.config = config or LlmConfig.from_env()
        self._transport = transport or _Transport()

    @property
    def available(self) -> bool:
        """Whether a provider is configured."""
        return bool(self.config.api_key)

    def choose_many(
        self,
        items: Sequence[tuple[int, list[tuple[str, str]]]],
        context: Sequence[str] = (),
    ) -> dict[int, tuple[int, float]]:
        """Decide per block: ``{block_id: (candidate_index, confidence)}``.

        ``items`` is ``(block_id, [(engine, text), ...])``. Unparseable replies and
        provider errors return an empty dict so the caller keeps current text.
        """
        if not items or not self.available:
            return {}

        payload = {
            "context": list(context)[:6],
            "items": [
                {
                    "id": block_id,
                    "candidates": [
                        {"engine": engine, "text": text} for engine, text in candidates
                    ],
                }
                for block_id, candidates in items
            ],
        }
        body = {
            "model": self.config.model,
            "temperature": 0.0,
            "messages": [
                {"role": "system", "content": SYSTEM_PROMPT},
                {"role": "user", "content": json.dumps(payload, ensure_ascii=False)},
            ],
        }
        try:
            response = self._transport.post(
                f"{self.config.base_url.rstrip('/')}/chat/completions",
                body,
                self.config.api_key,
                self.config.timeout,
            )
            content = response["choices"][0]["message"]["content"]
        except (TranslationError, KeyError, IndexError, TypeError):
            return {}
        return _parse_picks(content)


def _parse_picks(content: str) -> dict[int, tuple[int, float]]:
    """Extract picks from a reply, ignoring anything malformed."""
    start, end = content.find("{"), content.rfind("}")
    if start < 0 or end <= start:
        return {}
    try:
        data = json.loads(content[start : end + 1])
    except json.JSONDecodeError:
        return {}
    picks = data.get("picks")
    if not isinstance(picks, list):
        return {}
    result: dict[int, tuple[int, float]] = {}
    for item in picks:
        try:
            block_id = int(item["id"])
            choice = int(item["pick"])
            confidence = float(item.get("confidence", 0.5))
        except (KeyError, TypeError, ValueError):
            continue
        result[block_id] = (choice, max(0.0, min(1.0, confidence)))
    return result
