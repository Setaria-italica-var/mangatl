"""Region fill repaints the whole selection, independent of the text detector."""

from __future__ import annotations

import uuid
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw

from mangatl.adapters.inpaint.masked import MaskedInpainter


def test_fill_region_removes_everything_inside(tmp_path=None):
    scratch = Path(__file__).resolve().parents[1] / ".tmp" / f"fill-{uuid.uuid4().hex[:8]}"
    scratch.mkdir(parents=True)
    page = scratch / "page.png"
    image = Image.new("RGB", (200, 200), "white")
    draw = ImageDraw.Draw(image)
    draw.rectangle((50, 50, 90, 70), fill="black")  # "text" the detector could miss
    draw.rectangle((150, 150, 180, 180), fill="black")  # outside the selection
    image.save(page)

    mask = np.zeros((200, 200), dtype=bool)
    mask[40:80, 40:100] = True
    out = scratch / "out.png"
    MaskedInpainter().fill_region(page, out, mask)

    pixels = np.asarray(Image.open(out).convert("L"))
    assert pixels[50:70, 50:90].mean() > 200
    assert pixels[160:170, 160:170].mean() < 60

    for item in scratch.glob("*"):
        item.unlink(missing_ok=True)
    scratch.rmdir()
