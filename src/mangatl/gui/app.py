"""Entry point for the desktop editor."""

from __future__ import annotations

import sys
from pathlib import Path


def run(project_dir: Path | str) -> int:
    """Open the editor on a project directory and return the exit code."""
    try:
        from PySide6.QtWidgets import QApplication
    except ImportError:
        print(
            "PySide6 is not installed: uv pip install 'mangatl[gui]'",
            file=sys.stderr,
        )
        return 2

    from mangatl.gui.fluent import init_fluent
    from mangatl.gui.main_window import MainWindow

    application = QApplication.instance() or QApplication(sys.argv[:1])
    init_fluent(application)
    window = MainWindow(Path(project_dir))
    window.show()
    return application.exec()
