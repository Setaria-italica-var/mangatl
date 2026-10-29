"""Page sidebar: thumbnails with status glyphs and page-level actions."""

from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import QSize, Qt, Signal
from PySide6.QtGui import QIcon, QPixmap
from PySide6.QtWidgets import QListWidget, QListWidgetItem
from qfluentwidgets import Action, RoundMenu

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

    ``review`` wins because questionable blocks need attention even when every
    stage has run.

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
    """Short label used by tests and the sidebar."""
    return f"{Path(page.name).stem} {STATUS_GLYPHS[page_status(page)]}"


def page_tooltip(page: Page) -> str:
    """Rich tooltip listing stage state and review count."""
    pending = [stage for stage in STAGES if not page.stage.get(stage)]
    reviews = sum(1 for block in page.blocks if block.needs_review)
    lines = [page.name, f"{len(page.blocks)} 块 · {reviews} 待校对"]
    lines.append("未完成：" + ", ".join(pending) if pending else "全部阶段已完成")
    return "\n".join(lines)


class ThumbnailList(QListWidget):
    """Sidebar list: page thumbnail, status glyph and a context menu."""

    pageSelected = Signal(int)
    pageAction = Signal(str, int)  # action name, page index

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setObjectName("PageThumbs")
        self.setIconSize(QSize(104, 148))
        self.setSpacing(3)
        self.setUniformItemSizes(False)
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
        item = self.item(index)
        if item is not None:
            item.setText(f"{Path(page.name).stem}  {STATUS_GLYPHS[page_status(page)]}")
            item.setToolTip(page_tooltip(page))

    def _thumbnail(self, path: Path) -> QIcon | None:
        pixmap = QPixmap(str(path))
        if pixmap.isNull():
            return None
        return QIcon(pixmap.scaled(104, 148, Qt.AspectRatioMode.KeepAspectRatio))

    def _on_row(self, row: int) -> None:
        if not self._suppress and row >= 0:
            self.pageSelected.emit(row)

    def _context_menu(self, position) -> None:
        index = self.row(self.itemAt(position))
        if index < 0:
            return
        menu = RoundMenu(parent=self)
        for label, key in (
            ("运行本页", "run"),
            ("重置本页", "reset"),
            ("打开结果图", "open"),
            ("重命名…", "rename"),
        ):
            menu.addAction(
                Action(
                    label,
                    menu,
                    triggered=lambda _=False, k=key, i=index: self.pageAction.emit(k, i),
                )
            )
        menu.exec(self.viewport().mapToGlobal(position))
