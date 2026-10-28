"""Tests for the synthetic page generator."""

from __future__ import annotations

from pathlib import Path

import pytest

pytest.importorskip("PIL")

from PIL import Image  # noqa: E402

from mangatl.tools.demo import PAGE_SIZE, generate  # noqa: E402


def test_generate_writes_pages(tmp_path: Path) -> None:
    paths = generate(tmp_path / "vol1", pages=3, seed=1)

    assert len(paths) == 3
    assert all(path.is_file() for path in paths)
    with Image.open(paths[0]) as page:
        assert page.size == PAGE_SIZE


def test_generate_is_deterministic(tmp_path: Path) -> None:
    first = generate(tmp_path / "a", pages=2, seed=5)
    second = generate(tmp_path / "b", pages=2, seed=5)

    assert [p.read_bytes() for p in first] == [p.read_bytes() for p in second]


def test_generate_all_variants(tmp_path: Path) -> None:
    paths = generate(tmp_path / "v", pages=3, seed=2)
    assert len({path.stat().st_size for path in paths}) > 1  # variants differ
