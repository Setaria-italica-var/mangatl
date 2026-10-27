"""Smoke test: package is importable and carries a version."""

import mangatl


def test_version() -> None:
    assert mangatl.__version__.startswith("0.3.")