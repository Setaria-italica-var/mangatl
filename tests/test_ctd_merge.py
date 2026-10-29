"""Tests for CTD line merging (geometry, no model)."""

from __future__ import annotations

from mangatl.adapters.detectors.ctd import merge_lines


def test_stacked_lines_of_one_bubble_merge() -> None:
    lines = [(0, 0, 80, 20), (0, 24, 80, 44)]

    assert merge_lines(lines) == [(0, 0, 80, 44)]


def test_sound_effect_beside_a_bubble_is_not_glued() -> None:
    bubble = (0, 0, 80, 20)
    effect = (10, 40, 90, 260)

    assert merge_lines([bubble, effect]) == [bubble, effect]


def test_vertical_columns_of_one_block_merge() -> None:
    left = (0, 0, 30, 120)
    right = (36, 0, 66, 120)

    assert merge_lines([left, right]) == [(0, 0, 66, 120)]


def test_distant_lines_stay_separate() -> None:
    first = (0, 0, 80, 20)
    second = (0, 90, 80, 110)

    assert merge_lines([first, second]) == [first, second]


def test_empty_input() -> None:
    assert merge_lines([]) == []


def test_merge_is_capped_by_page_area() -> None:
    page = (1000, 1000)
    # Many same-height lines stacked could chain into a page-sized block.
    lines = [(0, index * 30, 100, index * 30 + 20) for index in range(20)]

    merged = merge_lines(lines, page_size=page, max_area_ratio=0.05)

    assert all(
        (box[2] - box[0]) * (box[3] - box[1]) <= 0.05 * 1000 * 1000 for box in merged
    )
    assert len(merged) > 1


def test_growth_cap_stops_chaining() -> None:
    first = (0, 0, 100, 20)
    second = (0, 25, 100, 45)
    tall = (0, 50, 100, 250)

    merged = merge_lines([first, second, tall])

    assert (0, 0, 100, 250) not in merged
