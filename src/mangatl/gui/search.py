"""Global block search: find a page and block from text, score or review state."""

from __future__ import annotations

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDialog,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
)

from mangatl.domain.project import Project


class GlobalSearchDialog(QDialog):
    """Search every block in the project and jump to the result."""

    jumpRequested = Signal(int, int)  # page index, block id

    def __init__(self, project: Project, parent=None) -> None:
        super().__init__(parent)
        self.setWindowTitle("全局搜索")
        self.resize(880, 520)
        self.project = project

        layout = QVBoxLayout(self)
        row = QHBoxLayout()
        self.query = QLineEdit()
        self.query.setPlaceholderText("搜索原文或译文…")
        self.query.textChanged.connect(self.refresh)
        row.addWidget(self.query, 1)

        self.filter_box = QComboBox()
        self.filter_box.addItems(["全部", "低分 (<0.5)", "空译文", "待校对"])
        self.filter_box.currentIndexChanged.connect(self.refresh)
        row.addWidget(self.filter_box)

        self.only_bubble = QCheckBox("仅气泡内")
        self.only_bubble.stateChanged.connect(self.refresh)
        row.addWidget(self.only_bubble)
        layout.addLayout(row)

        self.table = QTableWidget(0, 5)
        self.table.setHorizontalHeaderLabels(["页", "#", "分数", "角色", "原文 / 译文"])
        self.table.horizontalHeader().setStretchLastSection(True)
        self.table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self.table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self.table.cellDoubleClicked.connect(self._jump)
        layout.addWidget(self.table, 1)

        self.status = QLabel("")
        layout.addWidget(self.status)
        self.refresh()

    # -- data -------------------------------------------------------------
    def refresh(self) -> None:
        """Rebuild the table from the current filters."""
        needle = self.query.text().strip().lower()
        mode = self.filter_box.currentIndex()
        bubble_only = self.only_bubble.isChecked()

        rows = []
        for page_index, page in enumerate(self.project):
            for block in page.blocks:
                if bubble_only and not block.in_bubble:
                    continue
                if mode == 1 and block.ocr_score >= 0.5:
                    continue
                if mode == 2 and block.translation.strip():
                    continue
                if mode == 3 and not block.needs_review:
                    continue
                haystack = f"{block.text} {block.translation}".lower()
                if needle and needle not in haystack:
                    continue
                rows.append((page_index, page.name, block))

        self.table.setRowCount(len(rows))
        for row, (page_index, page_name, block) in enumerate(rows):
            values = [
                page_name,
                str(block.id),
                f"{block.ocr_score:.2f}",
                block.role,
                f"{block.text[:48]}  →  {block.translation[:40]}",
            ]
            for column, value in enumerate(values):
                item = QTableWidgetItem(value)
                item.setData(Qt.ItemDataRole.UserRole, (page_index, block.id))
                self.table.setItem(row, column, item)
        self.status.setText(f"{len(rows)} 条结果")

    def _jump(self, row: int, _column: int) -> None:
        item = self.table.item(row, 0)
        if item is None:
            return
        page_index, block_id = item.data(Qt.ItemDataRole.UserRole)
        self.jumpRequested.emit(int(page_index), int(block_id))
