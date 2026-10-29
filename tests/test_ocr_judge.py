"""Tests for the LLM OCR judge (fake transport, no provider)."""

from __future__ import annotations

import json

from mangatl.adapters.ocr.judge import LlmJudge
from mangatl.adapters.translators.openai_compat import LlmConfig


class FakeTransport:
    def __init__(self, reply: str) -> None:
        self.reply = reply
        self.calls = 0

    def post(self, url, payload, api_key, timeout):
        self.calls += 1
        return {"choices": [{"message": {"content": self.reply}}]}


def judge_with(reply: str) -> tuple[LlmJudge, FakeTransport]:
    transport = FakeTransport(reply)
    return LlmJudge(LlmConfig(api_key="k"), transport=transport), transport


def test_picks_are_parsed() -> None:
    reply = json.dumps({"picks": [{"id": 3, "pick": 1, "confidence": 0.9}]})
    judge, _ = judge_with(reply)

    picks = judge.choose_many([(3, [("manga_ocr", "ａｂ"), ("rapidocr", "こんにちは")])])

    assert picks[3] == (1, 0.9)


def test_malformed_reply_returns_nothing() -> None:
    judge, _ = judge_with("not json")

    assert judge.choose_many([(3, [("a", "x"), ("b", "y")])]) == {}


def test_missing_key_disables_the_judge() -> None:
    judge = LlmJudge(LlmConfig(api_key=""))

    assert judge.available is False
    assert judge.choose_many([(1, [("a", "x")])]) == {}


def test_reject_pick_is_preserved() -> None:
    reply = json.dumps({"picks": [{"id": 1, "pick": -1, "confidence": 0.8}]})
    judge, _ = judge_with(reply)

    assert judge.choose_many([(1, [("a", "x"), ("b", "y")])])[1] == (-1, 0.8)


def test_repair_parses_texts() -> None:
    reply = json.dumps({"items": [{"id": 2, "text": "おはようございます"}]})
    judge, _ = judge_with(reply)

    assert judge.repair_many([(2, "ｒＪＳｍ")]) == {2: "おはようございます"}


def test_repair_ignores_empty_text() -> None:
    reply = json.dumps({"items": [{"id": 2, "text": ""}]})
    judge, _ = judge_with(reply)

    assert judge.repair_many([(2, "???")]) == {}


def test_repair_without_key_does_nothing() -> None:
    judge = LlmJudge(LlmConfig(api_key=""))

    assert judge.repair_many([(1, "x")]) == {}
