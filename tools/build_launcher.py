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

    onedir = "--onedir" in sys.argv
    name = f"{NAME}-folder" if onedir else NAME

    dist = ROOT / "dist"
    build = ROOT / "build"
    dist.mkdir(exist_ok=True)
    shutil.rmtree(build, ignore_errors=True)
    # Only clear this build's own artifacts: the other variant may live beside it.
    for stale in (dist / f"{name}.exe", dist / name):
        if stale.is_dir():
            shutil.rmtree(stale, ignore_errors=True)
        elif stale.exists():
            stale.unlink()

    command = [
        sys.executable,
        "-m",
        "PyInstaller",
        "--noconfirm",
        "--clean",
        "--onedir" if onedir else "--onefile",
        "--console",
        "--name",
        name,
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

    exe = dist / f"{name}.exe"
    if not exe.is_file():
        exe = dist / name / f"{name}.exe"
    if not exe.is_file():
        print("\nbuild finished but the exe was not found")
        return 1
    print(f"\nbuilt: {exe} ({exe.stat().st_size / 1e6:.1f} MB)")
    print("copy it next to the project folder and double-click.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
