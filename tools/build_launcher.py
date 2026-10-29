"""Build the one-click launcher: ``dist/mangatl-launcher.exe``.

The exe only contains the launcher script (stdlib), not Python or Qt: it detects the
runtime, installs what is missing, downloads models and then starts the editor.
Keeping it small is what makes the project portable.

    python tools/build_launcher.py
"""

from __future__ import annotations

import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
NAME = "mangatl-launcher"


def main() -> int:
    entry = ROOT / "tools" / "launcher.py"
    if not entry.is_file():
        print(f"missing {entry}")
        return 1

    dist = ROOT / "dist"
    build = ROOT / "build"
    for folder in (dist, build):
        shutil.rmtree(folder, ignore_errors=True)

    onedir = "--onedir" in sys.argv
    command = [
        sys.executable,
        "-m",
        "PyInstaller",
        "--noconfirm",
        "--clean",
        "--onedir" if onedir else "--onefile",
        "--console",
        "--name",
        NAME,
        "--distpath",
        str(dist),
        "--workpath",
        str(build),
        "--specpath",
        str(ROOT / "build"),
        str(entry),
    ]
    print(" ".join(command))
    completed = subprocess.run(command, cwd=str(ROOT), check=False)
    if completed.returncode != 0:
        return completed.returncode

    exe = dist / f"{NAME}.exe"
    if not exe.is_file():
        exe = dist / NAME / f"{NAME}.exe"
    if not exe.is_file():
        print("\nbuild finished but the exe was not found")
        return 1
    print(f"\nbuilt: {exe} ({exe.stat().st_size / 1e6:.1f} MB)")
    print("copy it next to the project folder and double-click.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
