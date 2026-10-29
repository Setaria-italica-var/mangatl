"""A transformed frame keeps its glyph size ("free transform" semantics)."""

from __future__ import annotations

import os
import uuid
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest

pytest.importorskip("PIL")

from PIL import Image

from mangatl.domain.block import TextBlock
from mangatl.render.renderer import PageRenderer


@pytest.fixture
def page(tmp_path=None):
    scratch = Path(__file__).resolve().parents[1] / ".tmp" / f"font-{uuid.uuid4().hex[:8]}"
    scratch.mkdir(parents=True)
    image = scratch / "page.png"
    Image.new("RGB", (300, 300), "white").save(image)
    yield image
    for item in scratch.glob("*"):
        item.unlink(missing_ok=True)
    scratch.rmdir()


def test_locked_size_survives_box_shrink(page):
    block = TextBlock(
        id=0,
        bbox=(20, 20, 220, 120),
        translation="固定字号测试",
        style={"font_size": 24},
    )
    renderer = PageRenderer()

    renderer.render(page, [block], page.with_name("out1.png"))
    first = block.rendered_size

    block.bbox = (20, 20, 120, 60)  # much smaller frame
    renderer.render(page, [block], page.with_name("out2.png"))

    assert first == 24
    assert block.rendered_size == 24


def test_rendered_size_is_not_serialised(page):
    block = TextBlock(id=0, bbox=(0, 0, 10, 10), translation="x")
    block.rendered_size = 99

    assert "rendered_size" not in block.to_dict()
