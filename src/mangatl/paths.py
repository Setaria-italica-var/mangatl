"""Project-relative paths.

Nothing here may depend on the current working directory or on a Windows user name:
the app has to work from the repo, from a moved folder and from a frozen/portable
bundle. ``MANGATL_HOME`` and ``MANGATL_DATA_DIR`` override the two roots.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path


def app_root() -> Path:
    """Folder that contains ``pyproject.toml`` (or the exe when frozen)."""
    override = os.environ.get("MANGATL_HOME")
    if override:
        return Path(override).expanduser().resolve()
    if getattr(sys, "frozen", False):
        return Path(sys.executable).resolve().parent
    executable = Path(sys.executable).resolve()
    if executable.parent.name.lower() == "runtime":
        # Portable layout: <root>\runtime\python.exe with the package installed below.
        return executable.parent.parent
    here = Path(__file__).resolve()
    for parent in here.parents:
        if (parent / "pyproject.toml").is_file():
            return parent
    return here.parents[2]


def data_dir() -> Path:
    """Writable state directory (models, caches, settings)."""
    override = os.environ.get("MANGATL_DATA_DIR")
    if override:
        return Path(override).expanduser().resolve()
    return app_root() / "data"


def data_path(*parts: str) -> Path:
    return data_dir().joinpath(*parts)


def data_file(*parts: str) -> str:
    """Absolute string for a file under ``data/``."""
    return str(data_path(*parts))


def models_dir() -> Path:
    return data_path("models")


def models_file(*parts: str) -> str:
    return str(models_dir().joinpath(*parts))


def hf_dir() -> Path:
    return data_path("hf")


def fonts_dir() -> Path:
    return data_path("fonts")


def settings_path() -> Path:
    return data_path("settings.json")


def secrets_path() -> Path:
    return data_path("secrets.bin")


def recent_path() -> Path:
    return data_path("recent.json")


def error_log_path() -> Path:
    return data_path("error.log")


def project_path(relative: str | Path) -> Path:
    """Resolve a path stored relative to the app root."""
    candidate = Path(relative)
    return candidate if candidate.is_absolute() else app_root() / candidate


def display_path(path: Path | str) -> str:
    """Prefer a path relative to the app root for messages and saved state."""
    candidate = Path(path).resolve()
    try:
        return candidate.relative_to(app_root()).as_posix()
    except ValueError:
        return str(candidate)
