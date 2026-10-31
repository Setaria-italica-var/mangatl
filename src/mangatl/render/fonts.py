"""Find a CJK font for rendering.

Fonts are looked up in this order, so a portable build can ship its own fonts and
still fall back to the system on any desktop:

1. ``data/fonts/<style>.ttf|otf|ttc`` (bundled, preferred);
2. a small list of well-known system fonts per platform.

The resolver returns a path plus an index because ``.ttc`` collections need one.
"""

from __future__ import annotations

import sys
from dataclasses import dataclass
from pathlib import Path

from mangatl import paths

BUNDLED_DIR = paths.fonts_dir()

BUNDLED_CANDIDATES: dict[str, tuple[str, ...]] = {
    "sans": ("SourceHanSansSC-Regular.otf", "SourceHanSansSC-Regular.ttf", "sans.ttf"),
    "sans-bold": ("SourceHanSansSC-Bold.otf", "sans-bold.ttf"),
    "serif": ("SourceHanSerifSC-Regular.otf", "SourceHanSerifSC-Regular.ttf", "serif.ttf"),
    "hand": ("LXGWWenKai-Regular.ttf", "hand.ttf"),
}

SYSTEM_CANDIDATES: dict[str, dict[str, tuple[tuple[str, int], ...]]] = {
    "win32": {
        "sans": (("C:/Windows/Fonts/msyh.ttc", 0), ("C:/Windows/Fonts/simhei.ttf", 0)),
        "sans-bold": (("C:/Windows/Fonts/msyhbd.ttc", 0), ("C:/Windows/Fonts/msyh.ttc", 0)),
        "serif": (("C:/Windows/Fonts/simsun.ttc", 0), ("C:/Windows/Fonts/msyh.ttc", 0)),
        "hand": (("C:/Windows/Fonts/msyh.ttc", 0),),
    },
    "darwin": {
        "sans": (("/System/Library/Fonts/PingFang.ttc", 0),),
        "sans-bold": (("/System/Library/Fonts/PingFang.ttc", 0),),
        "serif": (("/System/Library/Fonts/Supplemental/Songti.ttc", 0),),
        "hand": (("/System/Library/Fonts/PingFang.ttc", 0),),
    },
    "linux": {
        "sans": (
            ("/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc", 0),
            ("/usr/share/fonts/truetype/noto/NotoSansCJK-Regular.ttc", 0),
        ),
        "sans-bold": (
            ("/usr/share/fonts/opentype/noto/NotoSansCJK-Bold.ttc", 0),
            ("/usr/share/fonts/truetype/noto/NotoSansCJK-Bold.ttc", 0),
        ),
        "serif": (
            ("/usr/share/fonts/opentype/noto/NotoSerifCJK-Regular.ttc", 0),
            ("/usr/share/fonts/truetype/noto/NotoSerifCJK-Regular.ttc", 0),
        ),
        "hand": (("/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc", 0),),
    },
}


@dataclass(frozen=True)
class FontRef:
    """A resolved font file plus the face index inside a collection."""

    path: Path
    index: int = 0


def resolve(category: str = "sans", weight: str = "regular") -> FontRef | None:
    """Return the best font for a category/weight, or ``None`` when none exists."""
    key = f"{category}-{weight}" if weight == "bold" and category == "sans" else category
    if key not in BUNDLED_CANDIDATES:
        key = "sans"

    for name in BUNDLED_CANDIDATES.get(key, ()):
        candidate = BUNDLED_DIR / name
        if candidate.is_file():
            return FontRef(candidate, 0)

    platform = sys.platform if sys.platform in SYSTEM_CANDIDATES else "linux"
    for raw_path, index in SYSTEM_CANDIDATES[platform].get(key, ()):
        path = Path(raw_path)
        if path.is_file():
            return FontRef(path, index)
    return None


def load(font: FontRef, size: int):
    """Load a PIL font; separated so layout stays testable with a fake measure."""
    from PIL import ImageFont

    return ImageFont.truetype(str(font.path), size=size, index=font.index)
