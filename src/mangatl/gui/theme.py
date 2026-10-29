"""Visual theme: a modern dark workspace for editing manga pages.

The palette follows the conventions of image editors (Krita, Clip Studio): a dark
neutral canvas surround, one accent colour for selection, and low-contrast panel
chrome so the page itself is the brightest thing on screen.

Kept as one stylesheet instead of a widget framework so the editor stays light and
portable; ``docs/gui.md`` records the alternatives considered.
"""

from __future__ import annotations

from PySide6.QtCore import QSize
from PySide6.QtGui import QColor, QFont, QPalette
from PySide6.QtWidgets import QApplication

BG = "#1b1d21"
SURFACE = "#24262b"
SURFACE_ALT = "#2c2f35"
BORDER = "#3a3e46"
TEXT = "#e6e7ea"
MUTED = "#9aa0a8"
ACCENT = "#4f9cf9"
ACCENT_DIM = "#3c78c0"

STYLESHEET = f"""
QMainWindow, QDialog {{
    background: {BG};
    color: {TEXT};
}}
QWidget {{
    color: {TEXT};
    font-size: 13px;
}}
QToolBar {{
    background: {SURFACE};
    border: none;
    border-bottom: 1px solid {BORDER};
    padding: 4px 6px;
    spacing: 4px;
}}
QToolBar QToolButton {{
    border-radius: 6px;
    padding: 5px 8px;
    color: {TEXT};
}}
QToolBar QToolButton:hover {{ background: {SURFACE_ALT}; }}
QToolBar QToolButton:checked {{
    background: {ACCENT_DIM};
    color: white;
}}
QDockWidget {{
    titlebar-close-icon: none;
    titlebar-normal-icon: none;
    color: {MUTED};
}}
QDockWidget::title {{
    background: {SURFACE};
    padding: 6px 10px;
    border-bottom: 1px solid {BORDER};
}}
QListWidget {{
    background: {SURFACE};
    border: 1px solid {BORDER};
    border-radius: 8px;
    padding: 4px;
    outline: none;
}}
QListWidget::item {{
    border-radius: 6px;
    padding: 6px;
    margin: 2px;
}}
QListWidget::item:hover {{ background: {SURFACE_ALT}; }}
QListWidget::item:selected {{
    background: {ACCENT_DIM};
    color: white;
}}
QTabBar {{
    background: {SURFACE};
    border-top: 1px solid {BORDER};
}}
QTabBar::tab {{
    background: {SURFACE};
    color: {MUTED};
    padding: 6px 14px;
    margin-right: 2px;
    border-top-left-radius: 6px;
    border-top-right-radius: 6px;
}}
QTabBar::tab:hover {{ background: {SURFACE_ALT}; color: {TEXT}; }}
QTabBar::tab:selected {{
    background: {SURFACE_ALT};
    color: {TEXT};
    border-bottom: 2px solid {ACCENT};
}}
QPushButton {{
    background: {SURFACE_ALT};
    border: 1px solid {BORDER};
    border-radius: 6px;
    padding: 6px 12px;
}}
QPushButton:hover {{ border-color: {ACCENT}; }}
QPushButton:pressed {{ background: {ACCENT_DIM}; }}
QLineEdit, QTextEdit, QComboBox {{
    background: {SURFACE_ALT};
    border: 1px solid {BORDER};
    border-radius: 6px;
    padding: 4px 6px;
    selection-background-color: {ACCENT_DIM};
}}
QLineEdit:focus, QTextEdit:focus, QComboBox:focus {{ border-color: {ACCENT}; }}
QStatusBar {{
    background: {SURFACE};
    color: {MUTED};
    border-top: 1px solid {BORDER};
}}
QScrollBar:vertical {{ background: transparent; width: 10px; }}
QScrollBar::handle:vertical {{
    background: {BORDER};
    border-radius: 5px;
    min-height: 24px;
}}
QScrollBar::handle:vertical:hover {{ background: {ACCENT_DIM}; }}
QScrollBar::add-line, QScrollBar::sub-line {{ height: 0; }}
QScrollBar:horizontal {{ background: transparent; height: 10px; }}
QScrollBar::handle:horizontal {{
    background: {BORDER};
    border-radius: 5px;
    min-width: 24px;
}}
QTableWidget {{
    background: {SURFACE};
    gridline-color: {BORDER};
    border: 1px solid {BORDER};
    border-radius: 8px;
}}
QHeaderView::section {{
    background: {SURFACE_ALT};
    color: {MUTED};
    border: none;
    padding: 5px;
}}
QMenu {{
    background: {SURFACE};
    border: 1px solid {BORDER};
    border-radius: 6px;
    padding: 4px;
}}
QMenu::item {{ padding: 6px 18px; border-radius: 4px; }}
QMenu::item:selected {{ background: {ACCENT_DIM}; }}
QToolTip {{
    background: {SURFACE_ALT};
    color: {TEXT};
    border: 1px solid {BORDER};
}}
"""


def apply_theme(application: QApplication) -> None:
    """Apply the dark palette, font and stylesheet to the application."""
    application.setStyle("Fusion")
    palette = QPalette()
    palette.setColor(QPalette.ColorRole.Window, QColor(BG))
    palette.setColor(QPalette.ColorRole.WindowText, QColor(TEXT))
    palette.setColor(QPalette.ColorRole.Base, QColor(SURFACE))
    palette.setColor(QPalette.ColorRole.AlternateBase, QColor(SURFACE_ALT))
    palette.setColor(QPalette.ColorRole.Text, QColor(TEXT))
    palette.setColor(QPalette.ColorRole.Button, QColor(SURFACE_ALT))
    palette.setColor(QPalette.ColorRole.ButtonText, QColor(TEXT))
    palette.setColor(QPalette.ColorRole.Highlight, QColor(ACCENT))
    palette.setColor(QPalette.ColorRole.HighlightedText, QColor("#ffffff"))
    palette.setColor(QPalette.ColorRole.ToolTipBase, QColor(SURFACE_ALT))
    palette.setColor(QPalette.ColorRole.ToolTipText, QColor(TEXT))
    application.setPalette(palette)

    font = QFont("Microsoft YaHei UI", 9)
    application.setFont(font)
    application.setStyleSheet(STYLESHEET)


def icon(name: str, colour: str = TEXT):
    """Return a Font Awesome icon, or ``None`` when qtawesome is absent."""
    try:
        import qtawesome

        return qtawesome.icon(name, color=colour)
    except Exception:  # noqa: BLE001 - icons are cosmetic
        return None


def toolbar_icon_size() -> QSize:
    """Consistent icon size for the toolbar."""
    return QSize(18, 18)
