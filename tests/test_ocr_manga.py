"""Tests for the manga-ocr adapter using a fake model module."""

from __future__ import annotations

import sys
import types
from pathlib import Path

import pytest

pytest.importorskip("PIL")
from PIL import Image  # noqa: E402

from mangatl.adapters.ocr.manga_ocr import NEUTRAL_CONFIDENCE, MangaOcrAdapter  # noqa: E402
from mangatl.domain.block import TextBlock  # noqa: E402


class FakeModel:
    def __init__(self) -> None:
        self.calls: list[tuple[int, int]] = []

    def __call__(self, image: Image.Image) -> str:
        self.calls.append(image.size)
        return f"  text-{len(self.calls)}  "


@pytest.fixture()
def fake_module(monkeypatch: pytest.MonkeyPatch) -> FakeModel:
    model = FakeModel()

    class MangaOcr:
        def __init__(self, **_kwargs) -> None:
            self._model = model

        def __call__(self, image):
            return self._model(image)

    module = types.ModuleType("manga_ocr")
    module.MangaOcr = MangaOcr
    monkeypatch.setitem(sys.modules, "manga_ocr", module)
    return model


def make_page(path: Path) -> Path:
    Image.new("RGB", (100, 200), (250, 250, 250)).save(path)
    return path


def test_recognize_crops_and_strips(tmp_path: Path, fake_module: FakeModel) -> None:
    page = make_page(tmp_path / "page.png")
    adapter = MangaOcrAdapter()
    blocks = [TextBlock(id=0, bbox=(10, 20, 60, 120))]

    result = adapter.recognize(page, blocks)

    assert result[0].text == "text-1"
    assert result[0].confidence == NEUTRAL_CONFIDENCE
    assert fake_module.calls == [(50, 100)]


def test_vertical_blocks_are_rotated(tmp_path: Path, fake_module: FakeModel) -> None:
    page = make_page(tmp_path / "page.png")
    adapter = MangaOcrAdapter()
    blocks = [TextBlock(id=0, bbox=(10, 20, 40, 120), vertical=True)]

    adapter.recognize(page, blocks)

    assert fake_module.calls == [(100, 30)]  # width/height swapped by the rotation


def test_out_of_bounds_block_is_skipped(tmp_path: Path, fake_module: FakeModel) -> None:
    page = make_page(tmp_path / "page.png")
    adapter = MangaOcrAdapter()
    blocks = [TextBlock(id=0, bbox=(150, 20, 200, 60))]

    result = adapter.recognize(page, blocks)

    assert result[0].text == ""
    assert result[0].confidence == 0.0
    assert fake_module.calls == []


def test_constructor_variants_are_accepted(monkeypatch: pytest.MonkeyPatch) -> None:
    seen: dict[str, object] = {}

    class ForceCpuModel:
        def __init__(self, pretrained_model_name_or_path=None, force_cpu=False):
            seen["name"] = pretrained_model_name_or_path
            seen["force_cpu"] = force_cpu

        def __call__(self, image):
            return "ok"

    module = types.ModuleType("manga_ocr")
    module.MangaOcr = ForceCpuModel
    monkeypatch.setitem(sys.modules, "manga_ocr", module)

    MangaOcrAdapter(device="cpu")

    assert seen["force_cpu"] is True
    assert seen["name"] == "kha-white/manga-ocr-base"


def test_model_failure_keeps_the_page_alive(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    class Exploding:
        def __call__(self, image):
            raise RuntimeError("boom")

    module = types.ModuleType("manga_ocr")
    module.MangaOcr = lambda **_kwargs: Exploding()
    monkeypatch.setitem(sys.modules, "manga_ocr", module)

    page = make_page(tmp_path / "page.png")
    result = MangaOcrAdapter().recognize(page, [TextBlock(id=0, bbox=(10, 20, 60, 120))])

    assert result[0].text == ""
    assert result[0].confidence == 0.0


def test_local_snapshot_resolves_cached_directory(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("HF_HOME", str(tmp_path))
    snapshot = tmp_path / "hub" / "models--kha-white--manga-ocr-base" / "snapshots" / "abc"
    snapshot.mkdir(parents=True)

    from mangatl.adapters.ocr.manga_ocr import local_snapshot

    assert local_snapshot() == str(snapshot)


def test_local_snapshot_returns_none_without_cache(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("HF_HOME", str(tmp_path))

    from mangatl.adapters.ocr.manga_ocr import local_snapshot

    assert local_snapshot() is None
