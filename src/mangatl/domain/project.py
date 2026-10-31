"""Project state: pages, blocks and per-stage progress.

The project file is the single source of truth for resumability. It is written
atomically (``<file>.tmp`` then :func:`os.replace`) so a crash never leaves a
half-written ``project.json``.

>>> import tempfile, pathlib
>>> tmp = pathlib.Path(tempfile.mkdtemp())
>>> project = Project.open(tmp)
>>> project.save()
>>> (tmp / "project.json").exists()
True
"""

from __future__ import annotations

import json
import os
from collections.abc import Iterator
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from mangatl.domain.block import TextBlock

SCHEMA = 3
STAGES: tuple[str, ...] = ("detect", "ocr", "erase")
IMAGE_SUFFIXES = frozenset({".png", ".jpg", ".jpeg", ".webp", ".bmp"})
PROJECT_FILENAME = "project.json"


@dataclass
class Page:
    """One page: its blocks plus a completion flag per stage."""

    name: str
    blocks: list[TextBlock] = field(default_factory=list)
    stage: dict[str, int] = field(default_factory=lambda: dict.fromkeys(STAGES, 0))
    # Transient per-run data: the detector's text probability, handed to the
    # inpainter without being persisted (it is large and derived).
    text_mask: Any = field(default=None, repr=False, compare=False)
    size: tuple[int, int] | None = None

    def is_done(self, stage: str) -> bool:
        """Return whether ``stage`` has already been completed for this page."""
        return bool(self.stage.get(stage, 0))

    def mark(self, stage: str) -> None:
        """Record ``stage`` as completed."""
        self.stage[stage] = 1

    def to_dict(self) -> dict[str, Any]:
        """Return a JSON-ready mapping."""
        payload: dict[str, Any] = {
            "stage": dict(self.stage),
            "blocks": [block.to_dict() for block in self.blocks],
        }
        if self.size is not None:
            payload["size"] = list(self.size)
        return payload

    @classmethod
    def from_dict(cls, name: str, data: dict[str, Any]) -> Page:
        """Rebuild a page from :meth:`to_dict` output."""
        stage = dict.fromkeys(STAGES, 0)
        stage.update({key: int(value) for key, value in data.get("stage", {}).items()})
        size = data.get("size")
        return cls(
            name=name,
            blocks=[TextBlock.from_dict(item) for item in data.get("blocks", [])],
            stage=stage,
            size=(int(size[0]), int(size[1])) if size else None,
        )


class Project:
    """A directory of page images plus their text blocks."""

    def __init__(self, directory: Path, pages: dict[str, Page] | None = None) -> None:
        self.directory = Path(directory)
        self.pages: dict[str, Page] = pages or {}

    @property
    def path(self) -> Path:
        """Path of the project file."""
        return self.directory / PROJECT_FILENAME

    @classmethod
    def open(cls, directory: str | Path) -> Project:
        """Open an existing project or create one by scanning ``directory``."""
        root = Path(directory)
        if not root.is_dir():
            raise FileNotFoundError(f"project directory does not exist: {root}")
        project = cls(root)
        if project.path.is_file():
            project._load()
        else:
            project.scan()
        return project

    def _load(self) -> None:
        data = json.loads(self.path.read_text(encoding="utf-8"))
        self.pages = {
            name: Page.from_dict(name, payload)
            for name, payload in data.get("pages", {}).items()
        }

    def reload(self) -> None:
        """Re-read ``project.json`` after a background worker changed it."""
        if self.path.is_file():
            self._load()
        else:
            self.scan()

    def scan(self) -> list[str]:
        """Add pages for every image in the directory, preserving existing ones."""
        found = sorted(
            item.name
            for item in self.directory.iterdir()
            if item.is_file() and item.suffix.lower() in IMAGE_SUFFIXES
        )
        for name in found:
            self.pages.setdefault(name, Page(name))
        return found

    def __iter__(self) -> Iterator[Page]:
        return iter(self.pages.values())

    def __len__(self) -> int:
        return len(self.pages)

    def to_dict(self) -> dict[str, Any]:
        """Return a JSON-ready mapping of the whole project."""
        return {
            "schema": SCHEMA,
            "pages": {name: page.to_dict() for name, page in sorted(self.pages.items())},
        }

    def save(self) -> None:
        """Write ``project.json`` atomically."""
        payload = json.dumps(self.to_dict(), ensure_ascii=False, indent=2)
        temporary = self.path.with_suffix(".json.tmp")
        temporary.write_text(payload, encoding="utf-8")
        os.replace(temporary, self.path)
