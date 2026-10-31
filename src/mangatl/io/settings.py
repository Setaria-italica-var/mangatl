"""Persist non-secret translator settings and apply them to the environment.

Layout under ``data/``:

* ``settings.json`` - base URL, model and chosen profile (plain text, no secrets);
* ``secrets.bin``  - DPAPI-encrypted API key (see :mod:`mangatl.io.secrets`).

Environment variables always win, so CI or a shell can override the saved values.
"""

from __future__ import annotations

import json
import os
from pathlib import Path

from mangatl import paths
from mangatl.io import secrets

SETTINGS_PATH = paths.settings_path()
SECRETS_PATH = paths.secrets_path()


def load_settings(root: Path | None = None) -> dict:
    """Read saved settings; an empty dict when missing or broken."""
    path = (root / SETTINGS_PATH) if root else SETTINGS_PATH
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    return data if isinstance(data, dict) else {}


def save_settings(values: dict, root: Path | None = None) -> None:
    """Write settings atomically (tmp + replace)."""
    path = (root / SETTINGS_PATH) if root else SETTINGS_PATH
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_name(path.name + ".tmp")
    temp.write_text(
        json.dumps(values, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    os.replace(temp, path)


def save_api_key(api_key: str, root: Path | None = None) -> bool:
    """Store the key encrypted; False when DPAPI is unavailable."""
    path = (root / SECRETS_PATH) if root else SECRETS_PATH
    return secrets.save_key(path, api_key)


def load_api_key(root: Path | None = None) -> str | None:
    path = (root / SECRETS_PATH) if root else SECRETS_PATH
    return secrets.load_key(path)


def clear_api_key(root: Path | None = None) -> None:
    path = (root / SECRETS_PATH) if root else SECRETS_PATH
    secrets.clear_key(path)


def apply_saved_settings(root: Path | None = None) -> None:
    """Fill ``MANGATL_*`` variables from disk without overriding the shell."""
    values = load_settings(root)
    mapping = {
        "base_url": "MANGATL_BASE_URL",
        "model": "MANGATL_MODEL",
    }
    for key, variable in mapping.items():
        if values.get(key) and not os.environ.get(variable):
            os.environ[variable] = str(values[key])
    if not os.environ.get("MANGATL_API_KEY"):
        key = load_api_key(root)
        if key:
            os.environ["MANGATL_API_KEY"] = key
