"""Adapter contracts and the registry that keeps implementations swappable.

Every heavy dependency (torch, onnxruntime, the model weights) lives behind one
of these protocols, so ``core`` never imports a backend directly.

>>> registry: Registry[object] = Registry("demo")
>>> @registry.register("alpha")
... class Alpha:
...     pass
>>> registry.get("alpha").__name__
'Alpha'
>>> registry.names()
['alpha']
"""

from __future__ import annotations

from collections.abc import Callable, Sequence
from pathlib import Path
from typing import Generic, Protocol, TypeVar, runtime_checkable

from mangatl.domain.block import TextBlock

T = TypeVar("T")


@runtime_checkable
class Detector(Protocol):
    """Finds text regions on one page."""

    name: str

    def detect(self, image_path: Path) -> list[TextBlock]:
        """Return blocks in reading order; ``bbox`` must be in image pixels."""


@runtime_checkable
class Ocr(Protocol):
    """Recognises text inside already-detected blocks."""

    name: str

    def recognize(self, image_path: Path, blocks: Sequence[TextBlock]) -> list[TextBlock]:
        """Return blocks with ``text`` and ``confidence`` filled in."""


@runtime_checkable
class Inpainter(Protocol):
    """Removes the original glyphs and writes the cleaned page."""

    name: str

    def erase(
        self,
        image_path: Path,
        destination: Path,
        blocks: Sequence[TextBlock] = (),
    ) -> None:
        """Write the erased page to ``destination``."""


class Registry(Generic[T]):
    """A small name -> factory registry.

    Registration is explicit (decorator or call); there is no import-time magic
    and no global instance, so tests can build an isolated registry.
    """

    def __init__(self, kind: str) -> None:
        self.kind = kind
        self._items: dict[str, T] = {}

    def register(self, name: str) -> Callable[[T], T]:
        """Register ``item`` under ``name``; usable as a decorator."""

        def _register(item: T) -> T:
            if name in self._items:
                raise KeyError(f"{self.kind} already registered: {name}")
            self._items[name] = item
            return item

        return _register

    def add(self, name: str, item: T) -> None:
        """Register ``item`` under ``name`` in one call."""
        if name in self._items:
            raise KeyError(f"{self.kind} already registered: {name}")
        self._items[name] = item

    def get(self, name: str) -> T:
        """Return the item registered under ``name``."""
        try:
            return self._items[name]
        except KeyError as exc:
            available = ", ".join(sorted(self._items)) or "<empty>"
            raise KeyError(f"unknown {self.kind}: {name} (available: {available})") from exc

    def names(self) -> list[str]:
        """Return registered names, sorted."""
        return sorted(self._items)
