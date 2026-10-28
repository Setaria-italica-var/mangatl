"""Tests for bubble decoding, NMS and containment (no model weights needed)."""

from __future__ import annotations

import numpy as np

from mangatl.adapters.detectors.bubbles import (
    Bubble,
    coverage,
    decode,
    letterbox,
    nms,
)


def test_letterbox_keeps_aspect_ratio() -> None:
    image = np.zeros((100, 200, 3), dtype=np.uint8)

    canvas, scale, (pad_x, pad_y) = letterbox(image, size=640)

    assert canvas.shape == (640, 640, 3)
    assert scale == 3.2
    assert pad_y == 160
    assert pad_x == 0


def test_decode_maps_boxes_back_to_page_space() -> None:
    # One anchor: centre (320, 320), size 64x64 in a 640 canvas, score 0.9.
    output = np.array([[[320.0], [320.0], [64.0], [64.0], [0.9]]])

    bubbles = decode(output, 0.3, 0.45, scale=1.0, padding=(0, 0), page_size=(640, 640))

    assert len(bubbles) == 1
    assert bubbles[0].bbox == (288, 288, 352, 352)
    assert bubbles[0].score > 0.8


def test_decode_accepts_channel_first_and_channel_last() -> None:
    boxes = np.array([[320.0, 320.0, 64.0, 64.0, 0.9]])

    channel_last = decode(boxes[None], 0.3, 0.45, 1.0, (0, 0), (640, 640))
    channel_first = decode(boxes.T[None], 0.3, 0.45, 1.0, (0, 0), (640, 640))

    assert channel_last[0].bbox == channel_first[0].bbox


def test_low_confidence_anchor_is_dropped() -> None:
    output = np.array([[[320.0], [320.0], [64.0], [64.0], [0.05]]])

    assert decode(output, 0.3, 0.45, 1.0, (0, 0), (640, 640)) == []


def test_class_index_selects_the_bubble_class() -> None:
    # Two classes: text 0.95, bubble 0.2 -> picking class 1 drops the anchor.
    output = np.array([[[320.0], [320.0], [64.0], [64.0], [0.95], [0.2]]])

    assert decode(output, 0.3, 0.45, 1.0, (0, 0), (640, 640), class_index=1) == []
    assert len(decode(output, 0.3, 0.45, 1.0, (0, 0), (640, 640), class_index=0)) == 1


def test_nms_keeps_the_best_of_overlapping_boxes() -> None:
    boxes = np.array(
        [
            [10, 10, 110, 110],
            [12, 12, 108, 108],
            [400, 400, 500, 500],
        ],
        dtype=float,
    )
    scores = np.array([0.9, 0.8, 0.7])

    keep = nms(boxes, scores, 0.5)

    assert keep == [0, 2]


def test_coverage_measures_how_much_of_a_block_is_inside() -> None:
    bubble = Bubble((0, 0, 100, 100), 0.9)

    assert coverage((10, 10, 90, 90), [bubble]) == 1.0
    assert coverage((50, 0, 150, 100), [bubble]) == 0.5
    assert coverage((150, 150, 250, 250), [bubble]) == 0.0


def test_decode_ignores_malformed_output() -> None:
    assert decode(np.zeros((1, 3, 3)), 0.3, 0.45, 1.0, (0, 0), (640, 640)) == []
