"""Tests for the editor geometry helpers (no Qt)."""

from __future__ import annotations

from mangatl.gui.geometry import (
    bbox_contains,
    bbox_intersects,
    clamp_bbox,
    polygon_bbox,
    polygon_mask,
    scale_bbox,
)


def test_polygon_bbox_rounds_to_box() -> None:
    assert polygon_bbox([(10, 12), (60, 12), (60, 48), (10, 48)]) == (10, 12, 60, 48)


def test_clamp_bbox_clips_to_page() -> None:
    assert clamp_bbox((-5, -5, 150, 120), 100, 100) == (0, 0, 100, 100)


def test_bbox_intersects_and_contains() -> None:
    assert bbox_intersects((0, 0, 10, 10), (5, 5, 15, 15))
    assert not bbox_intersects((0, 0, 10, 10), (10, 0, 20, 10))
    assert bbox_contains((0, 0, 100, 100), (10, 10, 20, 20))
    assert not bbox_contains((0, 0, 100, 100), (90, 90, 120, 120))


def test_polygon_mask_marks_inside() -> None:
    mask = polygon_mask([(10, 10), (30, 10), (30, 30), (10, 30)], 40, 40)

    assert mask.getpixel((20, 20)) == 255
    assert mask.getpixel((5, 5)) == 0


def test_scale_bbox_applies_factor_and_offset() -> None:
    assert scale_bbox((10, 10, 20, 20), 2.0, (5, 5)) == (25, 25, 45, 45)
