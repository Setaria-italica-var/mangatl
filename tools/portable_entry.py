"""Frozen-app entry point: run from the bundle directory, then start the editor.

``MANGATL_SMOKE=1`` opens the project in ``MANGATL_SMOKE_PROJECT`` and quits after a
few seconds, so a build can be verified without a human at the keyboard.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

from mangatl.gui.app import run


def _base_dir() -> Path:
    if getattr(sys, "frozen", False):
        return Path(sys.executable).resolve().parent
    return Path(__file__).resolve().parents[1]


def main() -> int:
    base = _base_dir()
    os.chdir(base)
    sys.path.insert(0, str(base))
    project = os.environ.get("MANGATL_SMOKE_PROJECT")
    if os.environ.get("MANGATL_SMOKE"):
        from PySide6.QtCore import QTimer
        from PySide6.QtWidgets import QApplication

        application = QApplication.instance() or QApplication(sys.argv[:1])
        QTimer.singleShot(4000, application.quit)
        return run(Path(project) if project else None)
    return run(Path(project) if project else None)


if __name__ == "__main__":
    raise SystemExit(main())
