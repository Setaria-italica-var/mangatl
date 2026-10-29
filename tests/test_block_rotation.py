"""Rotation survives project serialisation (pure, no Qt)."""

from __future__ import annotations

from mangatl.domain.block import TextBlock


def test_rotation_roundtrip() -> None:
    block = TextBlock(id=3, bbox=(10, 10, 60, 60), rotation=-12.5)

    restored = TextBlock.from_dict(block.to_dict())

    assert restored.rotation == -12.5
    assert restored.to_dict()["rotation"] == -12.5


def test_missing_rotation_defaults_to_zero() -> None:
    data = TextBlock(id=0, bbox=(0, 0, 10, 10)).to_dict()
    data.pop("rotation")

    assert TextBlock.from_dict(data).rotation == 0.0
