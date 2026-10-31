"""Copy the working tree package into runtime\\Lib\\site-packages for dev runs."""

from __future__ import annotations

import shutil
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / "src" / "mangatl"
TARGET = ROOT / "runtime" / "Lib" / "site-packages" / "mangatl"


def main() -> int:
    if not (ROOT / "runtime" / "python.exe").is_file():
        print("runtime/python.exe missing")
        return 2
    if TARGET.exists():
        shutil.rmtree(TARGET)
    shutil.copytree(SOURCE, TARGET)
    print(f"synced {SOURCE} -> {TARGET}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
