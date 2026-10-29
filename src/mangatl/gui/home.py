"""Welcome window: pick a manga folder, or reopen the last one."""

from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QFileDialog,
    QHBoxLayout,
    QListWidget,
    QListWidgetItem,
    QMainWindow,
    QVBoxLayout,
    QWidget,
)
from qfluentwidgets import (
    BodyLabel,
    CaptionLabel,
    CardWidget,
    InfoBar,
    PrimaryPushButton,
    TitleLabel,
)
from qfluentwidgets import (
    FluentIcon as FIF,
)

from mangatl.gui import recent

IMAGE_SUFFIXES = {".jpg", ".jpeg", ".png", ".webp", ".bmp", ".tif", ".tiff"}


def has_images(folder: Path) -> bool:
    """Whether a folder looks like a manga volume."""
    try:
        return any(item.suffix.lower() in IMAGE_SUFFIXES for item in folder.iterdir())
    except OSError:
        return False


class RecentList(QListWidget):
    """Clickable list of previously opened folders."""

    folderPicked = Signal(object)

    def __init__(self) -> None:
        super().__init__()
        self.setAlternatingRowColors(False)
        self.itemActivated.connect(self._activate)
        self.itemClicked.connect(self._activate)
        self.refresh()

    def refresh(self) -> None:
        self.clear()
        for folder in recent.load():
            item = QListWidgetItem(folder.name)
            item.setData(Qt.ItemDataRole.UserRole, str(folder))
            item.setToolTip(str(folder))
            self.addItem(item)

    def _activate(self, item: QListWidgetItem) -> None:
        self.folderPicked.emit(Path(str(item.data(Qt.ItemDataRole.UserRole))))


class HomePage(QWidget):
    """Landing page shown before a project is opened."""

    folderChosen = Signal(object)

    def __init__(self) -> None:
        super().__init__()
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.addStretch(1)

        row = QHBoxLayout()
        row.addStretch(1)
        card = CardWidget()
        card.setFixedWidth(620)
        layout = QVBoxLayout(card)
        layout.setContentsMargins(28, 24, 28, 24)
        layout.setSpacing(10)

        title = TitleLabel("mangatl")
        layout.addWidget(title)
        layout.addWidget(
            BodyLabel("漫画翻译：识别日文 → 翻译 → 擦除原文 → 中文排版")
        )
        layout.addSpacing(8)

        self.open_button = PrimaryPushButton(FIF.FOLDER, "打开漫画文件夹")
        self.open_button.setFixedHeight(40)
        self.open_button.clicked.connect(self.choose_folder)
        layout.addWidget(self.open_button)

        layout.addSpacing(12)
        layout.addWidget(CaptionLabel("最近打开"))
        self.recent = RecentList()
        self.recent.setMinimumHeight(160)
        self.recent.folderPicked.connect(self.folderChosen)
        layout.addWidget(self.recent)

        hint = CaptionLabel("支持 jpg / png / webp；文件夹里的图片会按文件名排序")
        hint.setWordWrap(True)
        layout.addWidget(hint)

        row.addWidget(card)
        row.addStretch(1)
        outer.addLayout(row)
        outer.addStretch(2)

    def choose_folder(self) -> None:
        start = str(recent.last() or Path.home())
        chosen = QFileDialog.getExistingDirectory(self, "选择漫画文件夹", start)
        if chosen:
            self.folderChosen.emit(Path(chosen))


class HomeWindow(QMainWindow):
    """Thin shell that swaps itself for the editor once a folder is picked."""

    def __init__(self) -> None:
        super().__init__()
        self.setWindowTitle("mangatl")
        self.resize(1000, 720)
        self.page = HomePage()
        self.page.folderChosen.connect(self.open_folder)
        self.setCentralWidget(self.page)
        self._editor = None

    def open_folder(self, folder: Path) -> None:
        folder = Path(folder)
        if not folder.is_dir():
            InfoBar.error("文件夹不存在", str(folder), parent=self)
            return
        if not has_images(folder):
            InfoBar.warning(
                "没有图片",
                "这个文件夹里没有 jpg/png 等图片，换一个试试",
                parent=self,
            )
            return
        from mangatl.gui.main_window import MainWindow

        recent.remember(folder)
        editor = MainWindow(folder)
        editor.showMaximized()
        self._editor = editor
        self.close()


def welcome_or_folder(explicit: Path | None) -> Path | None:
    """Decide which folder to open on launch.

    ``explicit`` wins; otherwise the last folder is reused when it still exists and
    holds images; otherwise the welcome page is shown.
    """
    if explicit is not None:
        candidate = Path(explicit)
        return candidate if candidate.is_dir() else None
    remembered = recent.last()
    if remembered is not None and has_images(remembered):
        return remembered
    return None
