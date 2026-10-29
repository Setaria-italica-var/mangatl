"""Tests for the recent-folders store (no Qt)."""

from __future__ import annotations

import shutil
import uuid
from pathlib import Path

import pytest

from mangatl.gui import recent


@pytest.fixture
def scratch():
    """Workspace scratch dir (the system temp dir is ACL-restricted here)."""
    base = (
        Path(__file__).resolve().parents[1] / ".tmp" / f"recent-{uuid.uuid4().hex[:8]}"
    )
    base.mkdir(parents=True)
    yield base
    shutil.rmtree(base, ignore_errors=True)


def _point_store(monkeypatch, scratch: Path) -> None:
    monkeypatch.setattr(recent, "store_path", lambda: scratch / "recent.json")


def test_remember_puts_newest_first(monkeypatch, scratch):
    _point_store(monkeypatch, scratch)
    first = scratch / "vol1"
    second = scratch / "vol2"
    first.mkdir()
    second.mkdir()

    recent.remember(first)
    recent.remember(second)

    assert recent.load() == [second.resolve(), first.resolve()]
    assert recent.last() == second.resolve()


def test_remember_deduplicates(monkeypatch, scratch):
    _point_store(monkeypatch, scratch)
    folder = scratch / "vol1"
    folder.mkdir()

    recent.remember(folder)
    recent.remember(folder)

    assert recent.load() == [folder.resolve()]


def test_missing_folders_are_dropped(monkeypatch, scratch):
    _point_store(monkeypatch, scratch)
    folder = scratch / "gone"
    folder.mkdir()
    recent.remember(folder)
    folder.rmdir()

    assert recent.load() == []


def test_corrupt_file_returns_empty(monkeypatch, scratch):
    _point_store(monkeypatch, scratch)
    (scratch / "recent.json").write_text("not json", encoding="utf-8")

    assert recent.load() == []
    assert recent.last() is None
