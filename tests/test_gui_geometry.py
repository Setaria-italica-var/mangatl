"""Tests for the editor geometry helpers (no Qt)."""

from __future__ import annotations

from mangatl.gui.geometry import (
    bbox_contains,
    bbox_intersects,
    clamp_bbox,
    move_bbox,
    polygon_bbox,
    polygon_mask,
    resize_bbox,
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


def test_move_bbox_keeps_box_inside_page() -> None:
    assert move_bbox((10, 10, 50, 40), 5, 5, 200, 200) == (15, 15, 55, 45)
    assert move_bbox((10, 10, 50, 40), -500, -500, 200, 200) == (0, 0, 40, 30)
    assert move_bbox((10, 10, 50, 40), 500, 500, 200, 200) == (160, 170, 200, 200)


def test_resize_bbox_corner_and_sides() -> None:
    assert resize_bbox((10, 10, 60, 50), "se", 10, 5) == (10, 10, 70, 55)
    assert resize_bbox((10, 10, 60, 50), "nw", 10, 5) == (20, 15, 60, 50)
    assert resize_bbox((10, 10, 60, 50), "e", 10, 0) == (10, 10, 70, 50)
    assert resize_bbox((10, 10, 60, 50), "s", 0, 10) == (10, 10, 60, 60)


def test_resize_bbox_never_collapses() -> None:
    collapsed = resize_bbox((10, 10, 60, 50), "nw", 500, 500)
    assert collapsed[2] - collapsed[0] >= 8
    assert collapsed[3] - collapsed[1] >= 8
