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
