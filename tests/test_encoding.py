"""Guard against mojibake: every text file must be valid UTF-8 without PUA chars.

Background: editing a UTF-8 file with a tool that decodes it using the system
code page (GBK on a Chinese Windows) silently rewrites Chinese into private-use
characters. The damage is invisible to ``git diff`` and to the interpreter, so it
needs its own test.
"""

from __future__ import annotations

from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
TEXT_SUFFIXES = frozenset(
    {".md", ".txt", ".py", ".toml", ".yml", ".yaml", ".cfg", ".ini", ".json", ".css", ".html"}
)
SKIP_PARTS = frozenset(
    {
        ".git",
        ".venv",
        ".tmp",
        ".pytest-tmp",
        ".acl-reports",
        "__pycache__",
        "samples",
        "wheels",
        "data",
    }
)


def iter_text_files() -> list[Path]:
    """Return every text file that belongs to the repository."""
    files: list[Path] = []
    for path in ROOT.rglob("*"):
        if not path.is_file() or path.suffix.lower() not in TEXT_SUFFIXES:
            continue
        relative = path.relative_to(ROOT)
        if any(part in SKIP_PARTS for part in relative.parts):
            continue
        files.append(path)
    return sorted(files)


@pytest.mark.parametrize("path", iter_text_files(), ids=lambda p: str(p.relative_to(ROOT)))
def test_text_file_is_clean_utf8(path: Path) -> None:
    """Decoding must succeed and no private-use character may appear."""
    text = path.read_text(encoding="utf-8")
    private_use = [char for char in text if 0xE000 <= ord(char) <= 0xF8FF]
    assert not private_use, (
        f"{path.relative_to(ROOT)} contains private-use characters "
        f"(likely a GBK round-trip): {private_use[:5]}"
    )
