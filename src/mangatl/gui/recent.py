"""Recently opened manga folders, stored next to the program.

The file is deliberately tiny and portable: no registry, no ``%APPDATA%``. It only
records folder paths so the next launch can reopen the last book.
"""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path

MAX_ENTRIES = 8


def app_root() -> Path:
    """Directory that holds ``data/`` (repo root in source, exe folder when frozen)."""
    if getattr(sys, "frozen", False):
        return Path(sys.executable).resolve().parent
    return Path(__file__).resolve().parents[3]


def store_path() -> Path:
    """Location of the recent-folders file (``MANGATL_RECENT`` overrides it)."""
    override = os.environ.get("MANGATL_RECENT")
    if override:
        return Path(override)
    return app_root() / "data" / "recent.json"


def load() -> list[Path]:
    """Return remembered folders, newest first, dropping ones that vanish."""
    path = store_path()
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return []
    entries = raw.get("folders", []) if isinstance(raw, dict) else []
    folders = []
    for item in entries:
        candidate = Path(str(item))
        if candidate.is_dir():
            folders.append(candidate)
    return folders[:MAX_ENTRIES]


def remember(folder: Path | str) -> Path:
    """Put ``folder`` at the front of the recent list and save it."""
    resolved = Path(folder).resolve()
    folders = [item for item in load() if item != resolved]
    folders.insert(0, resolved)
    _save(folders[:MAX_ENTRIES])
    return resolved


def last() -> Path | None:
    """The folder to reopen on launch, if any."""
    folders = load()
    return folders[0] if folders else None


def _save(folders: list[Path]) -> None:
    path = store_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {"folders": [str(item) for item in folders]}
    temp = path.with_suffix(".tmp")
    temp.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    os.replace(temp, path)
