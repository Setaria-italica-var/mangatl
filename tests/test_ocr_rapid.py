"""Tests for the RapidOCR adapter (both engine API shapes, no model needed)."""

from __future__ import annotations

import sys
import types
from pathlib import Path

import numpy as np
import pytest

pytest.importorskip("numpy")
pytest.importorskip("PIL")
from PIL import Image  # noqa: E402

from mangatl.adapters.ocr.rapid import RapidOcrAdapter, overlap_ratio  # noqa: E402
from mangatl.domain.block import TextBlock  # noqa: E402


def make_page(tmp_path: Path) -> Path:
    path = tmp_path / "page.png"
    Image.new("RGB", (400, 600), (250, 250, 250)).save(path)
    return path


def test_overlap_ratio_uses_line_area() -> None:
    assert overlap_ratio((0, 0, 10, 10), (0, 0, 10, 10)) == pytest.approx(1.0)
    assert overlap_ratio((0, 0, 10, 10), (20, 20, 30, 30)) == 0.0
    assert overlap_ratio((0, 0, 10, 10), (5, 0, 15, 10)) == pytest.approx(0.5)


def install_legacy(monkeypatch: pytest.MonkeyPatch, result) -> None:
    class Engine:
        def __init__(self, **_kwargs) -> None:
            pass

        def __call__(self, _path):
            return result, 0.01

    module = types.ModuleType("rapidocr_onnxruntime")
    module.RapidOCR = Engine
    monkeypatch.setitem(sys.modules, "rapidocr_onnxruntime", module)
    monkeypatch.setitem(sys.modules, "rapidocr", None)


def install_modern(monkeypatch: pytest.MonkeyPatch, output) -> None:
    class Engine:
        def __init__(self, **_kwargs) -> None:
            pass

        def __call__(self, _path):
            return output

    module = types.ModuleType("rapidocr")
    module.RapidOCR = Engine
    monkeypatch.setitem(sys.modules, "rapidocr", module)


def test_legacy_api_attaches_lines_to_blocks(tmp_path: Path, monkeypatch) -> None:
    page = make_page(tmp_path)
    lines = [
        [[[10, 10], [110, 10], [110, 30], [10, 30]], "おはよう", 0.9],
        [[[10, 40], [110, 40], [110, 60], [10, 60]], "元気？", 0.8],
        [[[300, 10], [390, 10], [390, 30], [300, 30]], "別の吹き出し", 0.7],
    ]
    install_legacy(monkeypatch, lines)

    blocks = [
        TextBlock(id=0, bbox=(0, 0, 200, 100)),
        TextBlock(id=1, bbox=(250, 0, 400, 100)),
    ]
    result = RapidOcrAdapter().recognize(page, blocks)

    assert result[0].text == "おはよう元気？"
    assert result[0].confidence == pytest.approx(0.85)
    assert result[1].text == "別の吹き出し"
    assert result[1].confidence == pytest.approx(0.7)


def test_modern_api_is_supported(tmp_path: Path, monkeypatch) -> None:
    page = make_page(tmp_path)

    class Output:
        boxes = np.array([[[10, 10], [110, 10], [110, 30], [10, 30]]], dtype=np.float32)
        txts = ("hello",)
        scores = np.array([0.95], dtype=np.float32)

    install_modern(monkeypatch, Output())

    result = RapidOcrAdapter().recognize(page, [TextBlock(id=0, bbox=(0, 0, 200, 100))])

    assert result[0].text == "hello"
    assert result[0].confidence == pytest.approx(0.95)


def test_low_score_is_ignored(tmp_path: Path, monkeypatch) -> None:
    page = make_page(tmp_path)
    install_legacy(monkeypatch, [[[[10, 10], [110, 10], [110, 30], [10, 30]], "noise", 0.1]])

    result = RapidOcrAdapter().recognize(page, [TextBlock(id=0, bbox=(0, 0, 200, 100))])

    assert result[0].text == ""
    assert result[0].confidence == 0.0


def test_lines_outside_any_block_are_ignored(tmp_path: Path, monkeypatch) -> None:
    page = make_page(tmp_path)
    line = [[[300, 300], [390, 300], [390, 320], [300, 320]], "elsewhere", 0.9]
    install_legacy(monkeypatch, [line])

    result = RapidOcrAdapter().recognize(page, [TextBlock(id=0, bbox=(0, 0, 100, 100))])

    assert result[0].text == ""


def test_vertical_block_reads_right_to_left(tmp_path: Path, monkeypatch) -> None:
    page = make_page(tmp_path)
    lines = [
        [[[100, 10], [120, 10], [120, 60], [100, 60]], "second", 0.9],  # left column
        [[[150, 10], [170, 10], [170, 60], [150, 60]], "first", 0.9],  # right column
    ]
    install_legacy(monkeypatch, lines)

    blocks = [TextBlock(id=0, bbox=(90, 0, 180, 80), vertical=True)]
    result = RapidOcrAdapter().recognize(page, blocks)

    assert result[0].text == "firstsecond"
