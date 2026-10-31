"""Path policy: no repo-specific absolute paths, portable recent list."""

from __future__ import annotations

import json
import re
from pathlib import Path

from mangatl import paths
from mangatl.gui import recent

ROOT = Path(__file__).resolve().parents[1]
ABSOLUTE = re.compile(r"[A-Za-z]:\\\\")


def test_app_root_is_the_checkout() -> None:
    root = paths.app_root()
    assert (root / "pyproject.toml").is_file()
    assert paths.data_dir() == root / "data"
    assert paths.models_dir() == root / "data" / "models"


def test_source_has_no_drive_letter_paths() -> None:
    offenders = []
    for file in (ROOT / "src").rglob("*.py"):
        for number, line in enumerate(
            file.read_text(encoding="utf-8").splitlines(), 1
        ):
            if ABSOLUTE.search(line):
                offenders.append(f"{file}:{number}: {line.strip()}")
    assert not offenders, "\n".join(offenders[:5])


def test_recent_list_stores_paths_relative(tmp_path, monkeypatch) -> None:
    store = tmp_path / "recent.json"
    monkeypatch.setenv("MANGATL_RECENT", str(store))
    folder = paths.app_root() / "samples" / "vol1"
    if not folder.is_dir():
        return
    recent.remember(folder)
    payload = json.loads(store.read_text(encoding="utf-8"))
    assert payload["folders"][0] == "samples/vol1"
    assert recent.last() == folder
