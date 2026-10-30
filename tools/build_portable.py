"""Build the portable Windows folder (``dist/mangatl/``) with PyInstaller.

The bundle is a *folder*, not a single file: torch and Qt are large and the single-file
launcher used to die silently. ``data/models`` and ``data/hf`` are copied next to the exe
afterwards so the app finds them with its normal relative paths.

    python tools/build_portable.py            # build + copy models
    python tools/build_portable.py --no-models
"""

from __future__ import annotations

import argparse
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DIST = ROOT / "dist" / "mangatl"
PYINSTALLER_ARGS = [
    "--noconfirm",
    "--clean",
    "--windowed",
    "--name",
    "mangatl",
    "--onedir",
    "--paths",
    str(ROOT / "src"),
    "--collect-submodules",
    "manga_ocr",
    "--collect-submodules",
    "transformers",
    "--collect-submodules",
    "qfluentwidgets",
    "--collect-data",
    "qfluentwidgets",
    "--exclude-module",
    "tkinter",
    "--exclude-module",
    "matplotlib",
    "--exclude-module",
    "IPython",
    str(ROOT / "tools" / "portable_entry.py"),
]


def build() -> int:
    command = [sys.executable, "-m", "PyInstaller", *PYINSTALLER_ARGS]
    print("running:", " ".join(command[2:]))
    return subprocess.call(command, cwd=ROOT)


def copy_payload(with_models: bool) -> None:
    target = DIST / "data"
    target.mkdir(parents=True, exist_ok=True)
    (DIST / "项目").mkdir(exist_ok=True)
    if not with_models:
        return
    for name in ("models", "hf"):
        source = ROOT / "data" / name
        if not source.is_dir():
            print(f"skip missing {source}")
            continue
        destination = target / name
        if destination.exists():
            shutil.rmtree(destination)
        print(f"copying {name} …")
        shutil.copytree(source, destination)


def write_readme() -> None:
    text = """mangatl 便携版

1. 双击 mangatl.exe 启动。
2. data/models 与 data/hf 已随包携带，无需联网下载模型。
3. 项目文件请放在任意可写目录；翻译 Key 在「设置」里填写，
   勾选「记住 Key」后会用 Windows DPAPI 加密保存在 data/secrets.bin。
4. 本包使用相对路径，整个文件夹可以拷到别的 Windows 电脑（模型与 Key 绑定本机用户）。
"""
    (DIST / "使用说明.txt").write_text(text, encoding="utf-8")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--no-models", action="store_true", help="skip model/hf copy")
    args = parser.parse_args()
    code = build()
    if code != 0:
        return code
    copy_payload(not args.no_models)
    write_readme()
    size = sum(path.stat().st_size for path in DIST.rglob("*") if path.is_file())
    print(f"done: {DIST} ({size / 1024 / 1024:.0f} MB)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
