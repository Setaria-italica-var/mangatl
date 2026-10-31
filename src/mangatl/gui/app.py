"""Entry point for the desktop editor."""

from __future__ import annotations

import sys
import threading
import traceback
from pathlib import Path

from mangatl import paths

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


def _append_error(text: str) -> None:
    """Keep a crash log next to the portable app; harmless in a normal install."""
    try:
        path = paths.error_log_path()
        path.parent.mkdir(parents=True, exist_ok=True)
        if path.is_file() and path.stat().st_size > 2 * 1024 * 1024:
            path.replace(path.with_suffix(".log.old"))
        with path.open("a", encoding="utf-8") as handle:
            handle.write(traceback.format_exc() if text else "")
    except OSError:
        pass


def _install_error_hooks() -> None:
    """Record uncaught exceptions so a bat window that closes is not a dead end."""

    def hook(exc_type, exc, tb) -> None:
        try:
            path = paths.error_log_path()
            path.parent.mkdir(parents=True, exist_ok=True)
            with path.open("a", encoding="utf-8") as handle:
                handle.write("\n--- uncaught exception ---\n")
                handle.write("".join(traceback.format_exception(exc_type, exc, tb)))
        except OSError:
            pass
        sys.__excepthook__(exc_type, exc, tb)

    sys.excepthook = hook
    threading.excepthook = lambda args: hook(
        args.exc_type, args.exc_value, args.exc_traceback
    )


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
    _install_error_hooks()
    from mangatl.io.settings import apply_saved_settings

    apply_saved_settings()
    from mangatl.gui.fluent import init_fluent
    from mangatl.gui.home import HomeWindow, welcome_or_folder
    from mangatl.gui.main_window import MainWindow

    application = QApplication.instance() or QApplication(sys.argv[:1])
    init_fluent(application)

    folder = welcome_or_folder(Path(project_dir) if project_dir else None)
    window = MainWindow(folder) if folder is not None else HomeWindow()
    window.showMaximized()
    return application.exec()
