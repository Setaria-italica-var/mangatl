"""Collect environment facts when the portable build misbehaves on another PC."""

from __future__ import annotations

import platform
import sys
import traceback
from pathlib import Path

import os

BASE = Path(__file__).resolve().parent


def check_import(name: str) -> str:
    try:
        module = __import__(name)
        version = getattr(module, "__version__", "")
        return f"OK   {name} {version}"
    except Exception as exc:  # noqa: BLE001 - diagnostics must never crash
        return f"FAIL {name}: {type(exc).__name__}: {exc}"


def main() -> int:
    print("mangatl portable diagnostics")
    print("=" * 60)
    print("python  :", sys.version.replace("\n", " "))
    print("exe     :", sys.executable)
    print("cwd     :", os.getcwd())
    print("base    :", BASE)
    print("platform:", platform.platform())
    print("arch    :", platform.machine())
    print("MANGATL_API_KEY set:", bool(os.environ.get("MANGATL_API_KEY")))
    print("MANGATL_BASE_URL   :", os.environ.get("MANGATL_BASE_URL", ""))
    print("MANGATL_MODEL      :", os.environ.get("MANGATL_MODEL", ""))
    print()

    print("imports")
    for name in (
        "PySide6",
        "qfluentwidgets",
        "numpy",
        "PIL",
        "onnxruntime",
        "torch",
        "transformers",
        "manga_ocr",
        "mangatl",
    ):
        print(" ", check_import(name))
    print()

    print("models")
    for relative in (
        "data/models/comictextdetector.pt.onnx",
        "data/models/bubble_detector.onnx",
        "data/models/lama.onnx",
        "data/models/mit/ocr-ctc.ckpt",
        "data/hf/hub/models--kha-white--manga-ocr-base",
    ):
        path = BASE / relative
        if path.is_dir():
            count = sum(1 for _ in path.rglob("*") if _.is_file())
            print(f"  OK   {relative} (dir, {count} files)")
        elif path.is_file():
            print(f"  OK   {relative} ({path.stat().st_size / 1024 / 1024:.1f} MB)")
        else:
            print(f"  MISS {relative}")
    print()

    print("writable data dir")
    try:
        probe = BASE / "data" / ".diagnose_probe"
        probe.write_text("ok", encoding="utf-8")
        probe.unlink()
        print("  OK")
    except Exception as exc:  # noqa: BLE001
        print("  FAIL:", exc)
    print()

    print("notes")
    print("  - Windows 10/11 64-bit is required.")
    print("  - If torch fails: install the Microsoft VC++ 2015-2022 x64 runtime.")
    print("  - If qfluentwidgets fails on win32api: check python312._pth.")
    print("  - Send this file together with the error screenshot.")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except SystemExit:
        raise
    except Exception:  # noqa: BLE001 - keep the file useful even on a hard crash
        traceback.print_exc()
        raise SystemExit(1)
