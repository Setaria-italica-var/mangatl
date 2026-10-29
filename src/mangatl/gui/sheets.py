"""Bottom sheet host: the Excel-like bar switches *modules*, not pages.

Pages live in the left sidebar; the sheet bar is a workspace switcher whose tabs can
be added or removed at runtime (the "+" button). Each sheet is an independent panel:
editing tools, the block table, search, pipeline run and settings.
"""

from __future__ import annotations

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QHBoxLayout,
    QMenu,
    QStackedWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)
from qfluentwidgets import (
    BodyLabel,
    CaptionLabel,
    CardWidget,
    CheckBox,
    ComboBox,
    LineEdit,
    PrimaryPushButton,
    PushButton,
    TabBar,
    TableWidget,
    TextEdit,
    TransparentToolButton,
)
from qfluentwidgets import (
    FluentIcon as FIF,
)

from mangatl.domain.project import Page, Project
from mangatl.gui.pages import page_status

SHEET_TITLES = {
    "editor": "编辑",
    "blocks": "文本块",
    "search": "搜索",
    "run": "运行",
    "settings": "设置",
}


class EditorSheet(QWidget):
    """Region actions and quick hints for the current page."""

    regionAction = Signal(str)

    def __init__(self) -> None:
        super().__init__()
        layout = QHBoxLayout(self)
        layout.setContentsMargins(8, 8, 8, 8)

        info = QVBoxLayout()
        self.page_label = BodyLabel("未加载页面")
        info.addWidget(self.page_label)
        self.hint = CaptionLabel("用套索或矩形框选区域，再选择右侧操作。")
        info.addWidget(self.hint)
        info.addStretch(1)
        layout.addLayout(info, 2)

        buttons = QVBoxLayout()
        row1 = QHBoxLayout()
        self.btn_detect = PushButton(FIF.SEARCH, "区域重新检测")
        self.btn_detect.clicked.connect(lambda: self.regionAction.emit("detect"))
        row1.addWidget(self.btn_detect)
        self.btn_erase = PushButton(FIF.BROOM, "区域重新擦除")
        self.btn_erase.clicked.connect(lambda: self.regionAction.emit("erase"))
        row1.addWidget(self.btn_erase)
        buttons.addLayout(row1)

        row2 = QHBoxLayout()
        self.btn_add = PushButton(FIF.ADD, "区域添加文本块")
        self.btn_add.clicked.connect(lambda: self.regionAction.emit("add"))
        row2.addWidget(self.btn_add)
        self.btn_render = PushButton(FIF.PHOTO, "重新排版本页")
        self.btn_render.clicked.connect(lambda: self.regionAction.emit("render"))
        row2.addWidget(self.btn_render)
        buttons.addLayout(row2)
        layout.addLayout(buttons, 3)

    def show_page(self, page: Page | None) -> None:
        if page is None:
            self.page_label.setText("未加载页面")
            return
        self.page_label.setText(
            f"{page.name} · {len(page.blocks)} 块 · 状态 {page_status(page)}"
        )


class BlocksSheet(QWidget):
    """Editable table of every block on the current page."""

    blockSelected = Signal(int)
    blockEdited = Signal(int, str, str)

    def __init__(self) -> None:
        super().__init__()
        layout = QVBoxLayout(self)
        layout.setContentsMargins(8, 8, 8, 8)

        row = QHBoxLayout()
        row.addWidget(BodyLabel("当前页文本块"))
        row.addStretch(1)
        self.filter_box = ComboBox()
        self.filter_box.addItems(["全部", "低分 (<0.5)", "空译文", "待校对"])
        self.filter_box.currentIndexChanged.connect(self._refresh)
        row.addWidget(self.filter_box)
        layout.addLayout(row)

        self.table = TableWidget()
        self.table.setColumnCount(6)
        self.table.setHorizontalHeaderLabels(
            ["#", "角色", "分数", "竖排", "原文", "译文"]
        )
        self.table.horizontalHeader().setStretchLastSection(True)
        self.table.cellDoubleClicked.connect(self._select_row)
        self.table.itemChanged.connect(self._edited)
        layout.addWidget(self.table, 1)

        self._page: Page | None = None

    def show_page(self, page: Page | None) -> None:
        self._page = page
        self._refresh()

    def _refresh(self) -> None:
        if self._page is None:
            self.table.setRowCount(0)
            return
        mode = self.filter_box.currentIndex()
        blocks = [
            block
            for block in self._page.blocks
            if not (
                (mode == 1 and block.ocr_score >= 0.5)
                or (mode == 2 and block.translation.strip())
                or (mode == 3 and not block.needs_review)
            )
        ]
        self.table.blockSignals(True)
        self.table.setRowCount(len(blocks))
        for row, block in enumerate(blocks):
            values = [
                str(block.id),
                block.role,
                f"{block.ocr_score:.2f}",
                "是" if block.vertical else "否",
                block.text,
                block.translation,
            ]
            for column, value in enumerate(values):
                item = QTableWidgetItem(value)
                item.setData(Qt.ItemDataRole.UserRole, block.id)
                if column >= 4:
                    item.setFlags(item.flags() | Qt.ItemFlag.ItemIsEditable)
                else:
                    item.setFlags(item.flags() & ~Qt.ItemFlag.ItemIsEditable)
                self.table.setItem(row, column, item)
        self.table.blockSignals(False)

    def _select_row(self, row: int, _column: int) -> None:
        item = self.table.item(row, 0)
        if item is not None:
            self.blockSelected.emit(int(item.data(Qt.ItemDataRole.UserRole)))

    def _edited(self, item: QTableWidgetItem) -> None:
        if item.column() not in (4, 5):
            return
        block_id = self.table.item(item.row(), 0).data(Qt.ItemDataRole.UserRole)
        text = self.table.item(item.row(), 4).text()
        translation = self.table.item(item.row(), 5).text()
        self.blockEdited.emit(int(block_id), text, translation)


class SearchSheet(QWidget):
    """Cross-page block search with quality filters."""

    jumpRequested = Signal(int, int)

    def __init__(self, project: Project) -> None:
        super().__init__()
        self.project = project
        layout = QVBoxLayout(self)
        layout.setContentsMargins(8, 8, 8, 8)

        row = QHBoxLayout()
        self.query = LineEdit()
        self.query.setPlaceholderText("搜索原文 / 译文…")
        self.query.textChanged.connect(self.refresh)
        row.addWidget(self.query, 1)
        self.filter_box = ComboBox()
        self.filter_box.addItems(["全部", "低分 (<0.5)", "空译文", "待校对"])
        self.filter_box.currentIndexChanged.connect(self.refresh)
        row.addWidget(self.filter_box)
        self.bubble_only = CheckBox("仅气泡内")
        self.bubble_only.stateChanged.connect(self.refresh)
        row.addWidget(self.bubble_only)
        layout.addLayout(row)

        self.table = TableWidget()
        self.table.setColumnCount(5)
        self.table.setHorizontalHeaderLabels(["页", "#", "分数", "角色", "原文 / 译文"])
        self.table.horizontalHeader().setStretchLastSection(True)
        self.table.cellDoubleClicked.connect(self._jump)
        layout.addWidget(self.table, 1)
        self.status = CaptionLabel("")
        layout.addWidget(self.status)
        self.refresh()

    def refresh(self) -> None:
        needle = self.query.text().strip().lower()
        mode = self.filter_box.currentIndex()
        bubble_only = self.bubble_only.isChecked()
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
                if needle and needle not in f"{block.text} {block.translation}".lower():
                    continue
                rows.append((page_index, page.name, block))
        self.table.setRowCount(len(rows))
        for row, (page_index, name, block) in enumerate(rows):
            values = [
                name,
                str(block.id),
                f"{block.ocr_score:.2f}",
                block.role,
                f"{block.text[:46]} → {block.translation[:36]}",
            ]
            for column, value in enumerate(values):
                item = QTableWidgetItem(value)
                item.setData(Qt.ItemDataRole.UserRole, (page_index, block.id))
                self.table.setItem(row, column, item)
        self.status.setText(f"{len(rows)} 条结果")

    def _jump(self, row: int, _column: int) -> None:
        item = self.table.item(row, 0)
        if item is not None:
            page_index, block_id = item.data(Qt.ItemDataRole.UserRole)
            self.jumpRequested.emit(int(page_index), int(block_id))


class RunSheet(QWidget):
    """Stage switches and run buttons for the automatic pipeline."""

    runRequested = Signal(object, bool)  # stages tuple, all_pages

    def __init__(self) -> None:
        super().__init__()
        layout = QHBoxLayout(self)
        layout.setContentsMargins(8, 8, 8, 8)

        stages = QVBoxLayout()
        stages.addWidget(BodyLabel("阶段"))
        self.checks = {}
        for key, label in (
            ("detect", "检测"),
            ("ocr", "OCR"),
            ("translate", "翻译"),
            ("erase", "擦除"),
            ("render", "排版"),
        ):
            box = CheckBox(label)
            box.setChecked(True)
            self.checks[key] = box
            stages.addWidget(box)
        stages.addStretch(1)
        layout.addLayout(stages, 1)

        actions = QVBoxLayout()
        self.btn_page = PrimaryPushButton(FIF.PLAY, "运行当前页")
        self.btn_page.clicked.connect(lambda: self._run(False))
        actions.addWidget(self.btn_page)
        self.btn_all = PushButton(FIF.SYNC, "运行全部页")
        self.btn_all.clicked.connect(lambda: self._run(True))
        actions.addWidget(self.btn_all)
        actions.addStretch(1)
        layout.addLayout(actions, 1)

        self.log = TextEdit()
        self.log.setReadOnly(True)
        self.log.setPlaceholderText("运行日志…")
        layout.addWidget(self.log, 3)

    def _run(self, all_pages: bool) -> None:
        stages = tuple(key for key, box in self.checks.items() if box.isChecked())
        self.runRequested.emit(stages, all_pages)

    def append(self, message: str) -> None:
        self.log.append(message)


class SettingsSheet(QWidget):
    """Accent colour and environment overview."""

    accentChanged = Signal(str)

    def __init__(self) -> None:
        super().__init__()
        layout = QHBoxLayout(self)
        layout.setContentsMargins(8, 8, 8, 8)

        card = CardWidget()
        card_layout = QVBoxLayout(card)
        card_layout.addWidget(BodyLabel("强调色"))
        for colour, name in (
            ("#4f9cf9", "蓝"),
            ("#7c5cff", "紫"),
            ("#2fb171", "绿"),
            ("#e0863a", "橙"),
        ):
            button = PushButton(name)
            button.clicked.connect(lambda _=False, c=colour: self.accentChanged.emit(c))
            card_layout.addWidget(button)
        card_layout.addStretch(1)
        layout.addWidget(card, 1)

        info = CardWidget()
        info_layout = QVBoxLayout(info)
        info_layout.addWidget(BodyLabel("环境"))
        import os

        info_layout.addWidget(
            CaptionLabel(
                "翻译 API：" + ("已配置" if os.environ.get("MANGATL_API_KEY") else "未配置")
            )
        )
        info_layout.addWidget(CaptionLabel("OCR：manga-ocr + MIT48px 融合"))
        info_layout.addWidget(CaptionLabel("擦除：masked（只擦文字像素）"))
        info_layout.addStretch(1)
        layout.addWidget(info, 2)


class SheetHost(QWidget):
    """Tab bar plus stack; tabs can be added or removed at runtime."""

    def __init__(self, sheets: dict[str, QWidget]) -> None:
        super().__init__()
        self._sheets = sheets
        self._shown: list[str] = []

        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)

        bar_row = QHBoxLayout()
        bar_row.setContentsMargins(6, 2, 6, 0)
        self.tabbar = TabBar()
        self.tabbar.currentChanged.connect(self._switch)
        bar_row.addWidget(self.tabbar, 1)

        self.add_button = TransparentToolButton(FIF.ADD)
        self.add_button.setToolTip("添加模块页签")
        self.add_button.clicked.connect(self._show_add_menu)
        bar_row.addWidget(self.add_button)
        outer.addLayout(bar_row)

        self.stack = QStackedWidget()
        outer.addWidget(self.stack, 1)

        for key in sheets:
            self.add_sheet(key)

    # -- sheet management -------------------------------------------------
    def add_sheet(self, key: str) -> None:
        if key in self._shown or key not in self._sheets:
            return
        self._shown.append(key)
        self.stack.addWidget(self._sheets[key])
        self.tabbar.addTab(key, SHEET_TITLES.get(key, key))
        self.tabbar.setCurrentIndex(len(self._shown) - 1)

    def remove_sheet(self, key: str) -> None:
        if key not in self._shown:
            return
        index = self._shown.index(key)
        self._shown.pop(index)
        widget = self._sheets[key]
        self.stack.removeWidget(widget)
        self.tabbar.removeTab(index)
        if self._shown:
            self.tabbar.setCurrentIndex(min(index, len(self._shown) - 1))

    def show_sheet(self, key: str) -> None:
        if key not in self._shown:
            self.add_sheet(key)
        self.tabbar.setCurrentIndex(self._shown.index(key))

    @property
    def current_key(self) -> str | None:
        index = self.tabbar.currentIndex()
        return self._shown[index] if 0 <= index < len(self._shown) else None

    def sheet(self, key: str) -> QWidget | None:
        return self._sheets.get(key)

    # -- internals --------------------------------------------------------
    def _switch(self, index: int) -> None:
        if 0 <= index < self._shown:
            self.stack.setCurrentWidget(self._sheets[self._shown[index]])

    def _show_add_menu(self) -> None:
        menu = QMenu(self)
        for key in self._sheets:
            action = menu.addAction(SHEET_TITLES.get(key, key))
            action.setCheckable(True)
            action.setChecked(key in self._shown)
            action.triggered.connect(
                lambda checked, k=key: self.add_sheet(k) if checked else self.remove_sheet(k)
            )
        menu.exec(self.add_button.mapToGlobal(self.add_button.rect().bottomLeft()))


def build_sheets(project: Project) -> dict[str, QWidget]:
    """Create the standard sheet set."""
    return {
        "editor": EditorSheet(),
        "blocks": BlocksSheet(),
        "search": SearchSheet(project),
        "run": RunSheet(),
        "settings": SettingsSheet(),
    }
