"""In-app data directory browser used when Windows shell launch is unavailable."""

from __future__ import annotations

from pathlib import Path

from PySide6.QtWidgets import (
    QApplication,
    QDialog,
    QFileSystemModel,
    QHBoxLayout,
    QTreeView,
    QVBoxLayout,
)
from qfluentwidgets import CaptionLabel, InfoBar, PushButton


class DataBrowserDialog(QDialog):
    """Read-only file browser rooted at the data directory."""

    def __init__(self, directory: Path, parent=None) -> None:
        super().__init__(parent)
        self.directory = Path(directory)
        self.setWindowTitle("数据目录")
        self.resize(760, 520)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(12, 10, 12, 10)
        layout.setSpacing(8)
        label = CaptionLabel(str(self.directory))
        label.setWordWrap(True)
        layout.addWidget(label)

        self.model = QFileSystemModel(self)
        self.model.setRootPath(str(self.directory))
        self.tree = QTreeView()
        self.tree.setModel(self.model)
        self.tree.setRootIndex(self.model.index(str(self.directory)))
        self.tree.setUniformRowHeights(True)
        self.tree.setAnimated(True)
        self.tree.setColumnWidth(0, 320)
        self.tree.setColumnHidden(2, True)
        self.tree.setColumnHidden(3, True)
        self.tree.doubleClicked.connect(self._copy_selected)
        layout.addWidget(self.tree, 1)

        row = QHBoxLayout()
        copy_button = PushButton("复制当前路径")
        copy_button.clicked.connect(self._copy_selected)
        row.addWidget(copy_button)
        row.addStretch(1)
        close_button = PushButton("关闭")
        close_button.clicked.connect(self.accept)
        row.addWidget(close_button)
        layout.addLayout(row)

    def _copy_selected(self, index=None) -> None:
        current = index if index is not None else self.tree.currentIndex()
        path = self.model.filePath(current) if current.isValid() else str(self.directory)
        QApplication.clipboard().setText(path)
        InfoBar.success("已复制路径", path, parent=self, duration=2500)
