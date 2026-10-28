"""Tests for the OpenAI-compatible translator (no network, fake transport)."""

from __future__ import annotations

import json

from mangatl.adapters.translators.openai_compat import LlmConfig, OpenAiTranslator
from mangatl.domain.block import TextBlock


class FakeTransport:
    """Returns queued reply bodies and records the payloads."""

    def __init__(self, replies: list[str]) -> None:
        self.replies = list(replies)
        self.calls: list[dict] = []

    def post(self, url, payload, api_key, timeout):
        self.calls.append(payload)
        content = self.replies.pop(0)
        return {"choices": [{"message": {"content": content}}]}


def reply(*pairs: tuple[int, str]) -> str:
    return json.dumps({"blocks": [{"id": i, "text": t} for i, t in pairs]}, ensure_ascii=False)


def blocks(*texts: str) -> list[TextBlock]:
    return [TextBlock(id=index, bbox=(0, 0, 10, 10), text=text) for index, text in enumerate(texts)]


def test_translates_every_block() -> None:
    transport = FakeTransport([reply((0, "早上好"), (1, "我回来了"))])
    translator = OpenAiTranslator(LlmConfig(api_key="k"), transport=transport)

    result = translator.translate(blocks("おはよう", "ただいま"))

    assert [block.translation for block in result] == ["早上好", "我回来了"]
    assert not any(block.needs_review for block in result)
    assert transport.calls[0]["model"] == LlmConfig().model


def test_missing_id_is_retried_alone() -> None:
    transport = FakeTransport([reply((0, "早上好")), reply((1, "我回来了"))])
    translator = OpenAiTranslator(LlmConfig(api_key="k"), transport=transport)

    result = translator.translate(blocks("おはよう", "ただいま"))

    assert [block.translation for block in result] == ["早上好", "我回来了"]
    second_request = transport.calls[1]["messages"][1]["content"]
    assert json.loads(second_request)["blocks"] == [{"id": 1, "text": "ただいま"}]


def test_garbage_reply_falls_back_to_source() -> None:
    transport = FakeTransport(["not json", "still not json", "nope"])
    translator = OpenAiTranslator(
        LlmConfig(api_key="k", max_retries=2), transport=transport
    )

    result = translator.translate(blocks("おはよう"))

    assert result[0].translation == "おはよう"
    assert result[0].needs_review is True


def test_unexpected_id_is_rejected_not_applied() -> None:
    transport = FakeTransport([reply((7, "错的"), (0, "对的"))])
    translator = OpenAiTranslator(LlmConfig(api_key="k", max_retries=0), transport=transport)

    result = translator.translate(blocks("おはよう"))

    assert result[0].translation == "おはよう"  # rejected wholesale
    assert result[0].needs_review is True


def test_empty_blocks_are_skipped_without_a_request() -> None:
    transport = FakeTransport([])
    translator = OpenAiTranslator(LlmConfig(api_key="k"), transport=transport)

    result = translator.translate([TextBlock(id=0, bbox=(0, 0, 1, 1), text="   ")])

    assert transport.calls == []
    assert result[0].translation == ""
