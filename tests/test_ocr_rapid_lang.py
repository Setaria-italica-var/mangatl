"""Tests that the Japanese recognition model is selected (fake engine)."""

from __future__ import annotations

import sys
import types

from mangatl.adapters.ocr.rapid import RapidOcrAdapter


def install_fake(monkeypatch, captured: dict) -> None:
    class FakeRapid:
        def __init__(self, **kwargs) -> None:
            captured.update(kwargs)

        def __call__(self, _path):
            return None

    module = types.ModuleType("rapidocr")
    module.RapidOCR = FakeRapid
    monkeypatch.setitem(sys.modules, "rapidocr", module)
    monkeypatch.delitem(sys.modules, "rapidocr_onnxruntime", raising=False)


def test_japan_is_the_default_language(monkeypatch) -> None:
    captured: dict = {}
    install_fake(monkeypatch, captured)
    monkeypatch.delenv("MANGATL_OCR_LANG", raising=False)

    RapidOcrAdapter()

    assert captured["params"]["Rec.lang_type"] == "japan"


def test_language_can_be_overridden_by_argument(monkeypatch) -> None:
    captured: dict = {}
    install_fake(monkeypatch, captured)

    RapidOcrAdapter(lang="en")

    assert captured["params"]["Rec.lang_type"] == "en"


def test_environment_sets_the_language(monkeypatch) -> None:
    captured: dict = {}
    install_fake(monkeypatch, captured)
    monkeypatch.setenv("MANGATL_OCR_LANG", "korean")

    RapidOcrAdapter()

    assert captured["params"]["Rec.lang_type"] == "korean"


def test_existing_params_are_preserved(monkeypatch) -> None:
    captured: dict = {}
    install_fake(monkeypatch, captured)

    RapidOcrAdapter(params={"Global.text_score": 0.7})

    assert captured["params"]["Global.text_score"] == 0.7
    assert captured["params"]["Rec.lang_type"] == "japan"
