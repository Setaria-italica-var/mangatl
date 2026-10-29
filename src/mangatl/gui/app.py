"""Entry point for the desktop editor."""

from __future__ import annotations

import sys
from pathlib import Path

_IGNORED_QT_WARNINGS = (
    # Qt's style engine re-derives a font from a widget that already uses a pixel
    # size, then reports the missing point size. It is noise, not a failure.
    "Point size <= 0",
)


def _install_qt_log_filter() -> None:
    """Drop harmless Qt font-metric warnings from the console."""
    from PySide6.QtCore import QtMsgType, qInstallMessageHandler

    def handler(mode, context, message: str) -> None:
        if any(fragment in message for fragment in _IGNORED_QT_WARNINGS):
            return
        prefix = {
            QtMsgType.QtDebugMsg: "Qt:",
            QtMsgType.QtInfoMsg: "Qt:",
            QtMsgType.QtWarningMsg: "Qt warning:",
            QtMsgType.QtCriticalMsg: "Qt error:",
            QtMsgType.QtFatalMsg: "Qt fatal:",
        }.get(mode, "Qt:")
        print(f"{prefix} {message}", file=sys.stderr)

    qInstallMessageHandler(handler)


def run(project_dir: Path | str | None = None) -> int:
    """Open the last book, or the welcome page, and return the exit code."""
    try:
        from PySide6.QtWidgets import QApplication
    except ImportError:
        print(
            "PySide6 is not installed: uv pip install 'mangatl[gui]'",
            file=sys.stderr,
        )
        return 2

    _install_qt_log_filter()
    from mangatl.gui.fluent import init_fluent
    from mangatl.gui.home import HomeWindow, welcome_or_folder
    from mangatl.gui.main_window import MainWindow

    application = QApplication.instance() or QApplication(sys.argv[:1])
    init_fluent(application)

    folder = welcome_or_folder(Path(project_dir) if project_dir else None)
    window = MainWindow(folder) if folder is not None else HomeWindow()
    window.showMaximized()
    return application.exec()
