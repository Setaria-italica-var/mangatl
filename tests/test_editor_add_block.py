"""Manual blocks stay dialogue so their translation is lettered."""

from __future__ import annotations

import shutil
import uuid
from pathlib import Path

from mangatl.domain.project import Project
from mangatl.gui.editor import PageEditor

SAMPLE = Path(__file__).resolve().parents[1] / "samples" / "vol1"


def test_added_block_is_dialogue_even_over_artwork():
    scratch = (
        Path(__file__).resolve().parents[1] / ".tmp" / f"add-{uuid.uuid4().hex[:8]}"
    )
    shutil.copytree(SAMPLE, scratch)
    try:
        project = Project.open(scratch)
        page = next(p for p in project if p.name == "001.jpg")
        editor = PageEditor(project, page)
        # A busy area would be classified as "texture" by the role classifier.
        block = editor.add_block((700, 150, 850, 340), text="", translation="测试")

        assert block.role == "dialogue"
        assert block.ocr_source == "manual"
    finally:
        shutil.rmtree(scratch, ignore_errors=True)
