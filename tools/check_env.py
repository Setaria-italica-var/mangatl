"""Validate the runtime before the GUI starts.

The bat files only call this script and then ``mangatl gui``; dependency versions live
in ``requirements.txt`` so they can be updated without touching the launchers.
"""

from __future__ import annotations

import contextlib
import importlib
import importlib.metadata as metadata
import re
import sys

from mangatl import paths

# distribution name -> module that has to import
CHECKS = {
    "PySide6": "PySide6",
    "PySide6-Fluent-Widgets": "qfluentwidgets",
    "numpy": "numpy",
    "pillow": "PIL",
    "opencv-python-headless": "cv2",
    "onnxruntime": "onnxruntime",
    "torch": "torch",
    "transformers": "transformers",
    "manga-ocr": "manga_ocr",
    "rapidocr": "rapidocr",
    "pywin32": "win32api",
}

REQUIRED_FILES = (
    "data/models/comictextdetector.pt.onnx",
    "data/models/bubble_detector.onnx",
    "data/models/mit/ocr-ctc.ckpt",
    "data/models/mit/alphabet-all-v5.txt",
)
OPTIONAL_FILES = ("data/models/lama.onnx",)


def _requirements() -> dict[str, str]:
    """Parse ``name==version`` lines; comment and option lines are ignored."""
    path = paths.app_root() / "requirements.txt"
    pinned: dict[str, str] = {}
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except OSError:
        return pinned
    for line in lines:
        line = line.strip()
        if not line or line.startswith(("#", "-")):
            continue
        match = re.match(r"([A-Za-z0-9_.-]+)\s*==\s*([^\s;]+)", line)
        if match:
            pinned[match.group(1).lower()] = match.group(2)
    return pinned


def _base_version(value: str) -> str:
    return value.split("+", 1)[0]


def main() -> int:
    with contextlib.suppress(Exception):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    problems: list[str] = []
    print(f"mangatl runtime check — {sys.version.split()[0]} — {paths.app_root()}")
    pinned = _requirements()

    for distribution, module in CHECKS.items():
        try:
            importlib.import_module(module)
        except Exception as exc:  # noqa: BLE001 - report any import failure
            problems.append(f"缺少 {distribution}（{module}: {exc}）")
            continue
        expected = pinned.get(distribution.lower())
        if not expected:
            continue
        try:
            installed = metadata.version(distribution)
        except metadata.PackageNotFoundError:
            problems.append(f"{distribution} 未安装（需要 {expected}）")
            continue
        if _base_version(installed) != _base_version(expected):
            problems.append(f"{distribution} 版本 {installed}，需要 {expected}")

    for relative in REQUIRED_FILES:
        if not (paths.app_root() / relative).is_file():
            problems.append(f"缺少模型文件：{relative}")
    for relative in OPTIONAL_FILES:
        if not (paths.app_root() / relative).is_file():
            print(f"  · 可选模型未安装：{relative}")

    if problems:
        print("\n环境不完整：")
        for item in problems:
            print("  ✗", item)
        print("\n运行 setup.bat 更新依赖，或重新解压便携包。")
        return 1
    print("✓ 依赖与模型齐全")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
