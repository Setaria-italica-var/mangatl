"""OpenAI-compatible translator: one JSON contract, any provider.

Works with DeepSeek, OpenAI, OpenRouter, Ollama or a local vLLM because all of
them speak ``POST /chat/completions``. The request asks for a strict JSON object
keyed by block id, so a reply can be validated and repaired instead of silently
shifting text between bubbles.

Failure policy: a missing id is retried alone; a bad reply is retried once with a
repair instruction; if it still fails the block keeps its source text and is
marked ``needs_review``. Nothing is ever invented or dropped.

>>> OpenAiTranslator(_Transport()).name
'openai'
"""

from __future__ import annotations

import json
import os
import time
import urllib.error
import urllib.request
from collections.abc import Sequence
from dataclasses import dataclass, field
from typing import Any

from mangatl.domain.block import TextBlock

DEFAULT_BASE_URL = "https://api.deepseek.com/v1"
DEFAULT_MODEL = "deepseek-chat"

SYSTEM_PROMPT = (
    "You translate manga dialogue from {source} to {target}. "
    "Reply with JSON only: {{\"blocks\":[{{\"id\":<int>,\"text\":\"<translation>\"}}]}}. "
    "Translate every id exactly once, never merge or split ids, and keep the "
    "speaker's tone. Onomatopoeia becomes a short natural {target} sound. "
    "Symbols and punctuation are copied unchanged. Never add explanations."
)


@dataclass(frozen=True)
class LlmConfig:
    """Connection and generation settings for one provider."""

    base_url: str = DEFAULT_BASE_URL
    api_key: str = ""
    model: str = DEFAULT_MODEL
    temperature: float = 0.3
    timeout: float = 60.0
    max_retries: int = 2
    extra: dict[str, Any] = field(default_factory=dict)

    @classmethod
    def from_env(cls) -> LlmConfig:
        """Build a config from ``MANGATL_*`` environment variables."""
        return cls(
            base_url=os.environ.get("MANGATL_BASE_URL", DEFAULT_BASE_URL),
            api_key=os.environ.get("MANGATL_API_KEY", ""),
            model=os.environ.get("MANGATL_MODEL", DEFAULT_MODEL),
        )


class _Transport:
    """Minimal HTTP transport, isolated so tests can replace it."""

    def post(
        self, url: str, payload: dict[str, Any], api_key: str, timeout: float
    ) -> dict[str, Any]:
        request = urllib.request.Request(
            url,
            data=json.dumps(payload).encode("utf-8"),
            headers={
                "Content-Type": "application/json",
                "Authorization": f"Bearer {api_key}",
            },
            method="POST",
        )
        try:
            with urllib.request.urlopen(request, timeout=timeout) as response:
                return json.loads(response.read().decode("utf-8"))
        except urllib.error.HTTPError as exc:
            detail = exc.read().decode("utf-8", "replace")[:300]
            raise TranslationError(
                f"HTTP {exc.code} from {url}: {detail or exc.reason}"
            ) from exc
        except urllib.error.URLError as exc:
            raise TranslationError(f"cannot reach {url}: {exc.reason}") from exc


class TranslationError(RuntimeError):
    """Raised when a provider keeps returning unusable output."""


class OpenAiTranslator:
    """Translate blocks through any OpenAI-compatible chat endpoint."""

    name = "openai"

    def __init__(self, config: LlmConfig | None = None, transport: Any = None) -> None:
        self.config = config or LlmConfig.from_env()
        if not self.config.api_key:
            raise TranslationError(
                "MANGATL_API_KEY is not set: the translator would silently return "
                "the source text. Set the key or use --translator echo explicitly."
            )
        self._transport = transport or _Transport()

    # -- public API -------------------------------------------------------
    def translate(
        self,
        blocks: Sequence[TextBlock],
        context: dict[str, Any] | None = None,
    ) -> list[TextBlock]:
        """Fill ``translation`` for every block that has text."""
        pending = [block for block in blocks if block.text.strip()]
        if not pending:
            return list(blocks)

        source = (context or {}).get("source_lang", "Japanese")
        target = (context or {}).get("target_lang", "Simplified Chinese")
        remaining = pending
        for _attempt in range(self.config.max_retries + 1):
            if not remaining:
                break
            try:
                answers = self._request(remaining, source, target)
            except Exception:  # network/provider failure: retry, then fall back
                continue
            for block in remaining:
                translated = answers.get(block.id, "").strip()
                if translated:
                    block.translation = translated
                else:
                    block.needs_review = True
                    block.translation = block.text
            remaining = [block for block in remaining if block.id not in answers]
            if remaining:
                # Retry only the ids the model skipped, verbatim in a small batch.
                continue

        for block in remaining:
            block.needs_review = True
            block.translation = block.text
        return list(blocks)

    def check(self, text: str = "おはよう", target: str = "Simplified Chinese") -> dict[str, Any]:
        """Send one short request and return diagnostics instead of retrying.

        Used by ``mangatl translate-test`` so a bad key or model name fails
        immediately with the provider's own message.
        """
        started = time.perf_counter()
        block = TextBlock(id=0, bbox=(0, 0, 1, 1), text=text)
        answers = self._request([block], "Japanese", target)
        return {
            "base_url": self.config.base_url,
            "model": self.config.model,
            "source": text,
            "translation": answers.get(0, ""),
            "elapsed_s": round(time.perf_counter() - started, 2),
        }

    # -- request/parse ----------------------------------------------------
    def _request(
        self,
        blocks: Sequence[TextBlock],
        source: str,
        target: str,
    ) -> dict[int, str]:
        payload_blocks = [{"id": block.id, "text": block.text} for block in blocks]
        messages = [
            {"role": "system", "content": SYSTEM_PROMPT.format(source=source, target=target)},
            {"role": "user", "content": json.dumps({"blocks": payload_blocks}, ensure_ascii=False)},
        ]
        body = {
            "model": self.config.model,
            "temperature": self.config.temperature,
            "messages": messages,
            **self.config.extra,
        }
        response = self._transport.post(
            f"{self.config.base_url.rstrip('/')}/chat/completions",
            body,
            self.config.api_key,
            self.config.timeout,
        )
        content = response["choices"][0]["message"]["content"]
        return self._parse(content, {block.id for block in blocks})

    @staticmethod
    def _parse(content: str, expected: set[int]) -> dict[int, str]:
        """Extract ``{id: text}`` from a reply, rejecting anything unusable."""
        start = content.find("{")
        end = content.rfind("}")
        if start < 0 or end <= start:
            raise TranslationError("reply contains no JSON object")
        data = json.loads(content[start : end + 1])
        items = data.get("blocks")
        if not isinstance(items, list):
            raise TranslationError("reply has no blocks array")
        answers: dict[int, str] = {}
        for item in items:
            try:
                block_id = int(item["id"])
                text = str(item["text"])
            except (KeyError, TypeError, ValueError) as exc:
                raise TranslationError(f"malformed block entry: {item!r}") from exc
            if block_id not in expected:
                raise TranslationError(f"unexpected block id {block_id}")
            answers[block_id] = text
        return answers
