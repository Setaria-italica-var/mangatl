"""Tests for the CTD adapter's pure parts (no model, no onnxruntime required)."""

from __future__ import annotations

import numpy as np
import pytest

pytest.importorskip("numpy")

from mangatl.adapters.detectors.ctd import (  # noqa: E402
    CtdConfig,
    dilate_mask,
    letterbox,
    mask_to_boxes,
    merge_lines,
    resolve_model_path,
)

pil = pytest.importorskip("PIL")
from PIL import Image  # noqa: E402


def test_mask_to_boxes_finds_separate_components() -> None:
    mask = np.zeros((20, 20), dtype=bool)
    mask[2:6, 2:8] = True
    mask[12:16, 10:18] = True

    boxes = sorted(mask_to_boxes(mask, min_area=1))

    assert boxes == [(2, 2, 8, 6), (10, 12, 18, 16)]


def test_mask_to_boxes_filters_small_specks() -> None:
    mask = np.zeros((10, 10), dtype=bool)
    mask[1, 1] = True
    mask[5:8, 5:8] = True

    assert mask_to_boxes(mask, min_area=4) == [(5, 5, 8, 8)]


def test_dilate_mask_bridges_a_one_pixel_gap() -> None:
    mask = np.zeros((9, 9), dtype=bool)
    mask[4, 1] = True
    mask[4, 6] = True

    grown = dilate_mask(mask, radius=2)

    assert grown[4, 3] and grown[4, 4]  # gap closed in the middle


def test_merge_lines_joins_stacked_rows() -> None:
    rows = [(10, 10, 110, 30), (10, 34, 110, 54), (10, 58, 110, 78)]

    merged = merge_lines(rows)

    assert merged == [(10, 10, 110, 78)]


def test_merge_lines_keeps_distant_blocks_apart() -> None:
    left = (10, 10, 110, 30)
    far_right = (400, 10, 500, 30)

    assert len(merge_lines([left, far_right])) == 2


def test_letterbox_keeps_aspect_and_pads() -> None:
    image = Image.new("RGB", (400, 800), (255, 255, 255))

    blob, scale, content_w, content_h = letterbox(image, 1024)

    assert blob.shape == (1, 3, 1024, 1024)
    assert content_w == 512 and content_h == 1024
    assert scale == pytest.approx(1.28)
    assert blob[0, :, 0, 900].max() == 0  # padding stays black


def test_model_path_env_override(monkeypatch: pytest.MonkeyPatch, tmp_path) -> None:
    target = tmp_path / "custom.onnx"
    monkeypatch.setenv("MANGATL_CTD_MODEL", str(target))

    assert resolve_model_path(CtdConfig()) == target
