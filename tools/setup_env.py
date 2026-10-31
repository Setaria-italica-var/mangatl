"""Install or update the project runtime from ``requirements.txt``.

Uses a normal (non-embedded) Python 3.12 with pip as the installer, but installs into
``runtime\\Lib\\site-packages`` so the portable folder keeps working. The launchers never
change when dependencies change: edit ``requirements.txt``, run ``setup.bat``.
"""

from __future__ import annotations

import argparse
import os
import shutil
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
RUNTIME = ROOT / "runtime"
TARGET = RUNTIME / "Lib" / "site-packages"


def _works(command: list[str]) -> tuple[int, int] | None:
    try:
        completed = subprocess.run(
            [*command, "-c", "import sys; print(*sys.version_info[:2])"],
            capture_output=True,
            text=True,
            timeout=30,
        )
    except (OSError, subprocess.TimeoutExpired):
        return None
    if completed.returncode != 0:
        return None
    parts = completed.stdout.strip().split()
    if len(parts) != 2 or not all(part.isdigit() for part in parts):
        return None
    return int(parts[0]), int(parts[1])


def find_bootstrap() -> tuple[list[str], str] | None:
    """A Python 3.12 with pip, used only as the installer."""
    override = os.environ.get("MANGATL_BOOTSTRAP_PYTHON")
    if override:
        candidate = [override]
        if _works(candidate):
            return candidate, override

    launcher = shutil.which("py")
    if launcher:
        candidate = [launcher, "-3.12"]
        version = _works(candidate)
        if version == (3, 12):
            return candidate, "py -3.12"

    for name in ("python3.12", "python"):
        found = shutil.which(name)
        if found and _works([found]) == (3, 12):
            return [found], found
    return None


def main() -> int:
    parser = argparse.ArgumentParser(description="install/update mangatl runtime")
    parser.add_argument("--dev", action="store_true", help="also install pytest/ruff")
    parser.add_argument("--check", action="store_true", help="only report what would run")
    args = parser.parse_args()

    bootstrap = find_bootstrap()
    if bootstrap is None:
        print("找不到可用的 Python 3.12（安装时需要它来执行 pip）。")
        print("请安装 Python 3.12，或用 MANGATL_BOOTSTRAP_PYTHON 指向 python.exe。")
        return 2
    command, label = bootstrap
    requirements = "requirements-dev.txt" if args.dev else "requirements.txt"

    if not RUNTIME.is_dir():
        print(f"缺少 runtime 目录：{RUNTIME}")
        print("请重新解压便携包，或先运行 tools/build_portable_bat.py。")
        return 2
    TARGET.mkdir(parents=True, exist_ok=True)

    install = [
        *command,
        "-m",
        "pip",
        "install",
        "--upgrade",
        "--target",
        str(TARGET),
        "-r",
        str(ROOT / requirements),
    ]
    print(f"安装器：{label}")
    print(f"目标目录：{TARGET}")
    print(f"依赖清单：{requirements}")
    if args.check:
        print("将执行：", subprocess.list2cmdline(install))
        return 0

    code = subprocess.call(install, cwd=ROOT)
    if code != 0:
        print("依赖安装失败；请检查网络或 pip 输出。")
        return code

    sync = subprocess.call(
        [str(RUNTIME / "python.exe"), str(ROOT / "tools" / "sync_runtime.py")],
        cwd=ROOT,
    )
    if sync != 0:
        print("依赖已安装，但同步 mangatl 包失败。")
        return sync
    print("完成：运行 启动.bat / launch.bat 启动。")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
