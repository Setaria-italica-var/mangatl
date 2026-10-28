"""Passthrough translator: keeps the original text.

It exists so the pipeline can run end to end without an API key (tests, CI, and
the "only detect and erase" workflow).
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import Any

from mangatl.domain.block import TextBlock


class EchoTranslator:
    """Copy ``text`` into ``translation``."""

    name = "echo"

    def translate(
        self,
        blocks: Sequence[TextBlock],
        context: dict[str, Any] | None = None,
    ) -> list[TextBlock]:
        """Return blocks with the translation equal to the source text."""
        for block in blocks:
            block.translation = block.text
        return list(blocks)
