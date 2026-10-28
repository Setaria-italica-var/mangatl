"""Tests for the translate stage: roles decide what is sent."""

from __future__ import annotations

from pathlib import Path

import pytest

from mangatl.adapters.stubs import CopyInpainter, GridDetector
from mangatl.core.config import RunConfig
from mangatl.core.pipeline import PipelineService
from mangatl.domain.project import Project


class RoleOcr:
    """OCR double that returns one text per block, cycling through roles."""

    name = "fake"

    TEXTS = ["おはよう、元気？", "ゴゴゴ", "！！", ""]

    def recognize(self, image_path, blocks):
        for index, block in enumerate(blocks):
            block.text = self.TEXTS[index % len(self.TEXTS)]
            block.confidence = 0.9
        return list(blocks)


class RecordingTranslator:
    name = "recording"

    def __init__(self) -> None:
        self.seen: list[tuple[int, str]] = []

    def translate(self, blocks, context=None):
        for block in blocks:
            self.seen.append((block.id, block.text))
            block.translation = f"译:{block.text}"
        return list(blocks)


@pytest.fixture()
def project(tmp_path: Path) -> Project:
    for name in ("001.png", "002.png", "003.png", "004.png"):
        (tmp_path / name).write_bytes(b"\x89PNG\r\n\x1a\n")
    return Project.open(tmp_path)


def test_only_translatable_roles_are_sent(project: Project) -> None:
    translator = RecordingTranslator()
    service = PipelineService(
        project,
        GridDetector(columns=4, rows=1),
        RoleOcr(),
        CopyInpainter(),
        translator=translator,
    )

    service.run(RunConfig(stages=("detect", "ocr", "translate")))

    texts = [text for _id, text in translator.seen]
    assert "おはよう、元気？" in texts  # dialogue
    assert "ゴゴゴ" in texts  # SFX is translated too now
    assert "！！" not in texts  # symbol is copied, not translated
    assert "" not in texts  # empty block is never sent

    page = project.pages["001.png"]
    symbol = next(block for block in page.blocks if block.text == "！！")
    assert symbol.translation == "！！"
    dialogue = next(block for block in page.blocks if block.text.startswith("おはよう"))
    assert dialogue.translation.startswith("译:")


def test_translate_stage_respects_sfx_keep(project: Project) -> None:
    translator = RecordingTranslator()
    service = PipelineService(
        project,
        GridDetector(columns=4, rows=1),
        RoleOcr(),
        CopyInpainter(),
        translator=translator,
    )

    service.run(
        RunConfig(stages=("detect", "ocr", "translate"), sfx_policy="keep")
    )

    assert "ゴゴゴ" not in [text for _id, text in translator.seen]
