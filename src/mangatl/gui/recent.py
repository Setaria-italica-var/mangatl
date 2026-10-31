"""Recently opened manga folders, stored next to the program.

The file is deliberately tiny and portable: no registry, no ``%APPDATA%``. Folders under
the app root are saved **relative** to it, so moving the project does not break the list;
external folders stay absolute.
"""

from __future__ import annotations

import json
import os
from pathlib import Path

from mangatl import paths

MAX_ENTRIES = 8


def store_path() -> Path:
    """Location of the recent-folders file (``MANGATL_RECENT`` overrides it)."""
    override = os.environ.get("MANGATL_RECENT")
    if override:
        return Path(override)
    return paths.recent_path()


def _decode(item: object) -> Path:
    candidate = Path(str(item))
    return candidate if candidate.is_absolute() else paths.app_root() / candidate


def load() -> list[Path]:
    """Return remembered folders, newest first, dropping ones that vanish."""
    try:
        raw = json.loads(store_path().read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return []
    entries = raw.get("folders", []) if isinstance(raw, dict) else []
    folders: list[Path] = []
    for item in entries:
        candidate = _decode(item)
        if candidate.is_dir() and candidate not in folders:
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
    payload = {"folders": [paths.display_path(item) for item in folders]}
    temp = path.with_suffix(".tmp")
    temp.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    os.replace(temp, path)
