"""Tests for the vision OCR adapter (fake transport, no images)."""

from __future__ import annotations

from mangatl.adapters.ocr.vision import VisionConfig, VisionOcr, parse_reply


class FakeTransport:
    def __init__(self, content: str) -> None:
        self.content = content
        self.calls: list[dict] = []

    def post(self, url, payload, api_key, timeout):
        self.calls.append(payload)
        return {"choices": [{"message": {"content": self.content}}]}


def make_ocr(content: str) -> tuple[VisionOcr, FakeTransport]:
    transport = FakeTransport(content)
    config = VisionConfig(base_url="http://x/v1", api_key="k", model="vl")
    return VisionOcr(config, transport=transport), transport


def test_reply_is_trimmed() -> None:
    assert parse_reply("  「おはよう」\n") == "「おはよう」"


def test_notext_means_empty() -> None:
    assert parse_reply("NOTEXT") == ""
    assert parse_reply("") == ""


def test_read_returns_text(monkeypatch) -> None:
    ocr, transport = make_ocr("こんにちは")
    monkeypatch.setattr(
        VisionOcr, "_data_uri", lambda self, path, bbox: "data:image/png;base64,AA=="
    )

    text = ocr.read(__import__("pathlib").Path("x.png"), (0, 0, 10, 10))

    assert text == "こんにちは"
    assert transport.calls[0]["messages"][0]["content"][1]["type"] == "image_url"


def test_unavailable_without_model() -> None:
    ocr = VisionOcr(VisionConfig(base_url="http://x/v1", api_key="k", model=""))

    assert ocr.available is False
    assert ocr.read(__import__("pathlib").Path("x.png"), (0, 0, 1, 1)) == ""


def test_provider_error_returns_empty(monkeypatch) -> None:
    class Boom:
        def post(self, *args, **kwargs):
            raise RuntimeError("down")

    ocr = VisionOcr(VisionConfig(base_url="http://x", api_key="k", model="vl"), transport=Boom())
    monkeypatch.setattr(VisionOcr, "_data_uri", lambda self, path, bbox: "data:,")

    assert ocr.read(__import__("pathlib").Path("x.png"), (0, 0, 1, 1)) == ""
