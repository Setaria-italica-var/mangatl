"""Fluent Design setup: dark theme, accent colour and consistent fonts."""

from __future__ import annotations

from PySide6.QtGui import QColor, QFont, QPalette
from PySide6.QtWidgets import QApplication
from qfluentwidgets import Theme, setTheme, setThemeColor

ACCENT = "#4f9cf9"
FONT_FAMILY = "Microsoft YaHei UI"

# Fluent themes its own widgets, but the plain Qt chrome (main window, docks,
# toolbar, status bar) still needs explicit colours to join the dark workspace.
CHROME_QSS = """
QMainWindow, QDialog { background: #202020; }
QDockWidget { color: #d6d6d6; }
QDockWidget::title {
    background: #2b2b2b;
    padding: 6px 10px;
    border-bottom: 1px solid #3a3a3a;
}
QToolBar {
    background: #2b2b2b;
    border: none;
    border-bottom: 1px solid #3a3a3a;
    padding: 4px 6px;
    spacing: 3px;
}
QToolBar::separator {
    background: #464646;
    width: 1px;
    margin: 5px 7px;
}
QStatusBar { background: #2b2b2b; color: #9a9a9a; }
QMenu {
    background: #2b2b2b;
    color: #e6e6e6;
    border: 1px solid #3f3f3f;
    padding: 4px;
}
QMenu::item { padding: 6px 22px; border-radius: 4px; }
QMenu::item:selected { background: #3b6ea8; color: #ffffff; }
QMenu::separator { height: 1px; background: #3f3f3f; margin: 4px 8px; }
QListWidget#PageThumbs {
    background: #262626;
    border: none;
    outline: none;
}
QListWidget#PageThumbs::item { border-radius: 6px; padding: 6px; margin: 2px; }
QListWidget#PageThumbs::item:hover { background: #323232; }
QListWidget#PageThumbs::item:selected { background: #2f6fb5; color: #ffffff; }
"""


def init_fluent(application: QApplication, accent: str = ACCENT) -> None:
    """Apply the Fluent dark theme and the editor's accent colour."""
    setTheme(Theme.DARK)
    setThemeColor(accent)

    palette = QPalette()
    palette.setColor(QPalette.ColorRole.Window, QColor("#202020"))
    palette.setColor(QPalette.ColorRole.WindowText, QColor("#e6e6e6"))
    palette.setColor(QPalette.ColorRole.Base, QColor("#262626"))
    palette.setColor(QPalette.ColorRole.Text, QColor("#e6e6e6"))
    palette.setColor(QPalette.ColorRole.Button, QColor("#2b2b2b"))
    palette.setColor(QPalette.ColorRole.ButtonText, QColor("#e6e6e6"))
    palette.setColor(QPalette.ColorRole.Highlight, QColor(accent))
    palette.setColor(QPalette.ColorRole.HighlightedText, QColor("#ffffff"))
    application.setPalette(palette)
    application.setStyleSheet(CHROME_QSS)
    # Use a pixel size, like Fluent does itself. Mixing a point size into widgets
    # that expect pixels makes Qt warn with "Point size <= 0 (-1)".
    families = [FONT_FAMILY, "Microsoft YaHei", "Segoe UI", "Noto Sans CJK SC"]
    font = QFont()
    font.setFamilies(families)
    font.setPixelSize(13)
    application.setFont(font)
    try:
        from qfluentwidgets import setFontFamilies

        setFontFamilies(families)
    except Exception:  # noqa: BLE001 - older versions without the helper
        pass

