"""Right-side module panels: editing, block table, search, run and settings.

The module switcher is a narrow icon rail on the right edge (like VS Code's
activity bar), so the canvas keeps its width and height. The window bottom only
holds a slim engine bar, modelled on BallonsTranslator's bottom bar.
"""

from __future__ import annotations

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QHBoxLayout,
    QLabel,
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
    TableWidget,
    TextEdit,
)
from qfluentwidgets import (
    FluentIcon as FIF,
)

from mangatl.domain.block import TextBlock
from mangatl.domain.project import Page, Project
from mangatl.gui.pages import page_status

SHEET_TITLES = {
    "editor": "编辑",
    "blocks": "文本块",
    "search": "搜索",
    "run": "运行",
    "settings": "设置",
}

SHEET_ICONS = {
    "editor": FIF.EDIT,
    "blocks": FIF.TILES,
    "search": FIF.SEARCH,
    "run": FIF.PLAY,
    "settings": FIF.SETTING,
}


class EditorSheet(QWidget):
    """Block editor plus region actions for the current page."""

    regionAction = Signal(str)
    blockEdited = Signal(int, str, str, str)  # id, text, translation, role
    blockAction = Signal(str)  # reocr / translate / render / delete

    def __init__(self) -> None:
        super().__init__()
        layout = QVBoxLayout(self)
        layout.setContentsMargins(10, 8, 10, 8)
        layout.setSpacing(6)

        card = CardWidget()
        card_layout = QVBoxLayout(card)
        self.info = BodyLabel("未选中文本块")
        self.info.setWordWrap(True)
        card_layout.addWidget(self.info)
        self.meta = CaptionLabel("点画布上的框选中，或用套索框选区域")
        self.meta.setWordWrap(True)
        card_layout.addWidget(self.meta)
        layout.addWidget(card)

        layout.addWidget(CaptionLabel("原文（可手工修正）"))
        self.text_edit = TextEdit()
        self.text_edit.setFixedHeight(84)
        layout.addWidget(self.text_edit)

        layout.addWidget(CaptionLabel("译文"))
        self.translation_edit = TextEdit()
        self.translation_edit.setFixedHeight(84)
        layout.addWidget(self.translation_edit)

        row_role = QHBoxLayout()
        row_role.addWidget(QLabel("角色"))
        self.role_box = ComboBox()
        self.role_box.addItems(["dialogue", "sfx", "symbol", "texture"])
        row_role.addWidget(self.role_box, 1)
        layout.addLayout(row_role)

        row1 = QHBoxLayout()
        self.btn_apply = PrimaryPushButton(FIF.ACCEPT, "应用文本")
        self.btn_apply.clicked.connect(self._emit_edit)
        row1.addWidget(self.btn_apply)
        self.btn_reocr = PushButton(FIF.SYNC, "重新识别")
        self.btn_reocr.clicked.connect(lambda: self.blockAction.emit("reocr"))
        row1.addWidget(self.btn_reocr)
        layout.addLayout(row1)

        row2 = QHBoxLayout()
        self.btn_translate = PushButton(FIF.GLOBE, "翻译")
        self.btn_translate.clicked.connect(lambda: self.blockAction.emit("translate"))
        row2.addWidget(self.btn_translate)
        self.btn_render = PushButton(FIF.PHOTO, "排版本页")
        self.btn_render.clicked.connect(lambda: self.blockAction.emit("render"))
        row2.addWidget(self.btn_render)
        self.btn_delete = PushButton(FIF.DELETE, "删除")
        self.btn_delete.clicked.connect(lambda: self.blockAction.emit("delete"))
        row2.addWidget(self.btn_delete)
        layout.addLayout(row2)

        layout.addWidget(CaptionLabel("套索 / 矩形选区后："))
        row3 = QHBoxLayout()
        self.btn_detect = PushButton(FIF.SEARCH, "重新检测")
        self.btn_detect.clicked.connect(lambda: self.regionAction.emit("detect"))
        row3.addWidget(self.btn_detect)
        self.btn_erase = PushButton(FIF.BROOM, "重新擦除")
        self.btn_erase.clicked.connect(lambda: self.regionAction.emit("erase"))
        row3.addWidget(self.btn_erase)
        layout.addLayout(row3)
        self.btn_add = PushButton(FIF.ADD, "添加文本块")
        self.btn_add.clicked.connect(lambda: self.regionAction.emit("add"))
        layout.addWidget(self.btn_add)

        layout.addStretch(1)
        self._block_id: int | None = None

    def show_page(self, page: Page | None) -> None:
        if page is None:
            self.info.setText("未加载页面")
            return
        self.info.setText(
            f"{page.name} · {len(page.blocks)} 块 · 状态 {page_status(page)}"
        )

    def show_block(self, block: TextBlock | None) -> None:
        self._block_id = block.id if block else None
        if block is None:
            self.info.setText("未选中文本块")
            self.meta.setText("点画布上的框选中，或用套索框选区域")
            self.text_edit.setPlainText("")
            self.translation_edit.setPlainText("")
            return
        self.info.setText(
            f"#{block.id} {block.role} {'竖排' if block.vertical else '横排'}"
        )
        self.meta.setText(
            f"score={block.ocr_score:.2f} · source={block.ocr_source or '-'} · "
            f"{'气泡内' if block.in_bubble else '背景'}"
        )
        self.text_edit.setPlainText(block.text)
        self.translation_edit.setPlainText(block.translation)
        self.role_box.setCurrentText(block.role)

    def _emit_edit(self) -> None:
        if self._block_id is None:
            return
        self.blockEdited.emit(
            self._block_id,
            self.text_edit.toPlainText(),
            self.translation_edit.toPlainText(),
            self.role_box.currentText(),
        )


class BlocksSheet(QWidget):
    """Editable table of every block on the current page."""

    blockSelected = Signal(int)
    blockEdited = Signal(int, str, str, str)

    def __init__(self) -> None:
        super().__init__()
        layout = QVBoxLayout(self)
        layout.setContentsMargins(10, 8, 10, 8)

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
        self.blockEdited.emit(int(block_id), text, translation, "")


class SearchSheet(QWidget):
    """Cross-page block search with quality filters."""

    jumpRequested = Signal(int, int)

    def __init__(self, project: Project) -> None:
        super().__init__()
        self.project = project
        layout = QVBoxLayout(self)
        layout.setContentsMargins(10, 8, 10, 8)

        self.query = LineEdit()
        self.query.setPlaceholderText("搜索原文 / 译文…")
        self.query.textChanged.connect(self.refresh)
        layout.addWidget(self.query)

        row = QHBoxLayout()
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
                f"{block.text[:44]} → {block.translation[:34]}",
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

    runRequested = Signal(object, bool)

    def __init__(self) -> None:
        super().__init__()
        layout = QVBoxLayout(self)
        layout.setContentsMargins(10, 8, 10, 8)

        layout.addWidget(BodyLabel("阶段"))
        self.checks: dict[str, CheckBox] = {}
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
            layout.addWidget(box)

        self.btn_page = PrimaryPushButton(FIF.PLAY, "运行当前页")
        self.btn_page.clicked.connect(lambda: self._run(False))
        layout.addWidget(self.btn_page)
        self.btn_all = PushButton(FIF.SYNC, "运行全部页")
        self.btn_all.clicked.connect(lambda: self._run(True))
        layout.addWidget(self.btn_all)

        self.log = TextEdit()
        self.log.setReadOnly(True)
        self.log.setPlaceholderText("运行日志…")
        layout.addWidget(self.log, 1)

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
        layout = QVBoxLayout(self)
        layout.setContentsMargins(10, 8, 10, 8)

        layout.addWidget(BodyLabel("强调色"))
        row = QHBoxLayout()
        for colour, name in (
            ("#4f9cf9", "蓝"),
            ("#7c5cff", "紫"),
            ("#2fb171", "绿"),
            ("#e0863a", "橙"),
        ):
            button = PushButton(name)
            button.clicked.connect(lambda _=False, c=colour: self.accentChanged.emit(c))
            row.addWidget(button)
        layout.addLayout(row)

        import os

        card = CardWidget()
        card_layout = QVBoxLayout(card)
        card_layout.addWidget(BodyLabel("环境"))
        card_layout.addWidget(
            CaptionLabel(
                "翻译 API：" + ("已配置" if os.environ.get("MANGATL_API_KEY") else "未配置")
            )
        )
        card_layout.addWidget(CaptionLabel("OCR：manga-ocr + MIT48px 融合"))
        card_layout.addWidget(CaptionLabel("擦除：masked（只擦文字像素）"))
        layout.addWidget(card)
        layout.addStretch(1)


def build_sheets(project: Project) -> dict[str, QWidget]:
    """Create the standard module panels."""
    return {
        "editor": EditorSheet(),
        "blocks": BlocksSheet(),
        "search": SearchSheet(project),
        "run": RunSheet(),
        "settings": SettingsSheet(),
    }
