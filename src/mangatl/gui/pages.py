"""Page navigation widgets: status glyphs, thumbnails and the sheet-like tabs.

The bottom tab bar is modelled on a spreadsheet's sheet tabs: one tab per page,
a status dot, drag reordering, a filter box and a right-click menu with the
page-level actions. The left dock keeps the richer thumbnail list.
"""

from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import QSize, Qt, Signal
from PySide6.QtGui import QColor, QIcon, QPixmap
from PySide6.QtWidgets import (
    QHBoxLayout,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QMenu,
    QTabBar,
    QToolButton,
    QWidget,
)

from mangatl.domain.project import Page

STAGES = ("detect", "ocr", "translate", "erase", "render")

STATUS_GLYPHS = {
    "empty": "○",
    "partial": "◐",
    "done": "●",
    "review": "!",
}

STATUS_COLORS = {
    "empty": "#8a8a8a",
    "partial": "#d7a94a",
    "done": "#4caf50",
    "review": "#e05a5a",
}


def page_status(page: Page) -> str:
    """Return ``empty`` / ``partial`` / ``done`` / ``review`` for a page.

    ``review`` wins because a page with questionable blocks needs attention even
    when every stage has run.

    >>> page_status(Page(name="p"))
    'empty'
    """
    if any(block.needs_review for block in page.blocks):
        return "review"
    done = sum(1 for stage in STAGES if page.stage.get(stage))
    if done == len(STAGES):
        return "done"
    return "partial" if done else "empty"


def tab_label(page: Page) -> str:
    """Tab text: page number plus a status glyph."""
    glyph = STATUS_GLYPHS[page_status(page)]
    stem = Path(page.name).stem
    return f"{stem} {glyph}"


def page_tooltip(page: Page) -> str:
    """Rich tooltip listing stage state and review count."""
    pending = [stage for stage in STAGES if not page.stage.get(stage)]
    reviews = sum(1 for block in page.blocks if block.needs_review)
    lines = [page.name, f"{len(page.blocks)} 块 · {reviews} 待校对"]
    if pending:
        lines.append("未完成：" + ", ".join(pending))
    else:
        lines.append("全部阶段已完成")
    return "\n".join(lines)


class PageTabs(QWidget):
    """Spreadsheet-style page tabs with filter and page actions."""

    pageSelected = Signal(int)
    pageAction = Signal(str, int)  # action name, page index

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self._names: list[str] = []
        self._suppress = False

        layout = QHBoxLayout(self)
        layout.setContentsMargins(6, 4, 6, 4)
        layout.setSpacing(6)

        self.tabs = QTabBar()
        self.tabs.setExpanding(False)
        self.tabs.setMovable(True)
        self.tabs.setDrawBase(False)
        self.tabs.setElideMode(Qt.TextElideMode.ElideRight)
        self.tabs.setUsesScrollButtons(True)
        self.tabs.currentChanged.connect(self._on_current)
        self.tabs.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.tabs.customContextMenuRequested.connect(self._context_menu)
        layout.addWidget(self.tabs, 1)

        self.add_button = QToolButton()
        self.add_button.setText("＋")
        self.add_button.setToolTip("添加页面（把图片放进项目目录后刷新）")
        self.add_button.clicked.connect(lambda: self.pageAction.emit("add", -1))
        layout.addWidget(self.add_button)

        self.filter = QLineEdit()
        self.filter.setPlaceholderText("过滤页面…")
        self.filter.setClearButtonEnabled(True)
        self.filter.setFixedWidth(180)
        self.filter.textChanged.connect(self.apply_filter)
        layout.addWidget(self.filter)

    # -- content ----------------------------------------------------------
    def set_pages(self, names: list[str]) -> None:
        """Rebuild the tabs from page names."""
        self._names = list(names)
        self._suppress = True
        while self.tabs.count():
            self.tabs.removeTab(0)
        for name in self._names:
            self.tabs.addTab(Path(name).stem)
        self._suppress = False
        self.apply_filter(self.filter.text())

    def update_page(self, index: int, page: Page) -> None:
        """Refresh one tab's label and tooltip."""
        if 0 <= index < self.tabs.count():
            self.tabs.setTabText(index, tab_label(page))
            self.tabs.setTabToolTip(index, page_tooltip(page))
            colour = STATUS_COLORS[page_status(page)]
            self.tabs.setTabTextColor(index, QColor(colour))

    def select(self, index: int) -> None:
        """Select a page without emitting the user-facing signal."""
        self._suppress = True
        self.tabs.setCurrentIndex(index)
        self._suppress = False

    def apply_filter(self, text: str) -> None:
        """Hide tabs whose name does not contain ``text``."""
        needle = text.strip().lower()
        for index, name in enumerate(self._names):
            visible = needle in name.lower() if needle else True
            self.tabs.setTabVisible(index, visible)

    # -- events -----------------------------------------------------------
    def _on_current(self, index: int) -> None:
        if not self._suppress and index >= 0:
            self.pageSelected.emit(index)

    def _context_menu(self, position) -> None:
        index = self.tabs.tabAt(position)
        if index < 0:
            return
        menu = QMenu(self)
        actions = [
            ("运行本页", "run"),
            ("重置本页", "reset"),
            ("打开结果图", "open"),
            ("重命名…", "rename"),
        ]
        for label, key in actions:
            action = menu.addAction(label)
            action.triggered.connect(lambda _=False, k=key, i=index: self.pageAction.emit(k, i))
        menu.exec(self.tabs.mapToGlobal(position))


class ThumbnailList(QListWidget):
    """Left dock list: page thumbnail plus status line."""

    pageSelected = Signal(int)
    pageAction = Signal(str, int)

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setIconSize(QSize(96, 136))
        self.setSpacing(2)
        self.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.customContextMenuRequested.connect(self._context_menu)
        self.currentRowChanged.connect(self._on_row)
        self._suppress = False

    def set_pages(self, pages: list[Page], directory: Path) -> None:
        """Fill the list with thumbnail entries."""
        self._suppress = True
        self.clear()
        for page in pages:
            item = QListWidgetItem()
            item.setText(f"{Path(page.name).stem}  {STATUS_GLYPHS[page_status(page)]}")
            item.setToolTip(page_tooltip(page))
            icon = self._thumbnail(directory / page.name)
            if icon is not None:
                item.setIcon(icon)
            self.addItem(item)
        self._suppress = False

    def update_page(self, index: int, page: Page) -> None:
        """Refresh one row's label and tooltip."""
        item = self.item(index)
        if item is not None:
            item.setText(f"{Path(page.name).stem}  {STATUS_GLYPHS[page_status(page)]}")
            item.setToolTip(page_tooltip(page))

    def _thumbnail(self, path: Path) -> QIcon | None:
        pixmap = QPixmap(str(path))
        if pixmap.isNull():
            return None
        return QIcon(pixmap.scaled(96, 136, Qt.AspectRatioMode.KeepAspectRatio))

    def _on_row(self, row: int) -> None:
        if not self._suppress and row >= 0:
            self.pageSelected.emit(row)

    def _context_menu(self, position) -> None:
        index = self.row(self.itemAt(position))
        if index < 0:
            return
        menu = QMenu(self)
        for label, key in (
            ("运行本页", "run"),
            ("重置本页", "reset"),
            ("打开结果图", "open"),
            ("重命名…", "rename"),
        ):
            action = menu.addAction(label)
            action.triggered.connect(lambda _=False, k=key, i=index: self.pageAction.emit(k, i))
        menu.exec(self.viewport().mapToGlobal(position))


