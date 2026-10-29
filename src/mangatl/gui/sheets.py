"""Right-side module panels: editing, block table, search, run and settings.

The module switcher is a narrow icon rail on the right edge (like VS Code's
activity bar), so the canvas keeps its width and height. The window bottom only
holds a slim engine bar, modelled on BallonsTranslator's bottom bar.
"""

from __future__ import annotations

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QColorDialog,
    QDialog,
    QDoubleSpinBox,
    QHBoxLayout,
    QLabel,
    QSpinBox,
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
    "run": "运行",
    "settings": "设置",
}

SHEET_ICONS = {
    "editor": FIF.EDIT,
    "run": FIF.PLAY,
    "settings": FIF.SETTING,
}


class EditorSheet(QWidget):
    """Block editor plus region actions for the current page."""

    regionAction = Signal(str)
    blockEdited = Signal(int, str, str, str)  # id, text, translation, role
    blockAction = Signal(str)  # reocr / translate / render / delete
    blockApplied = Signal(int, str, str, str, dict)  # id, text, translation, role, style

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

        layout.addWidget(CaptionLabel("样式（0 = 自动）"))
        row_font = QHBoxLayout()
        self.font_box = ComboBox()
        self.font_box.addItems(["黑体", "宋体", "手写"])
        row_font.addWidget(self.font_box, 2)
        self.size_box = QSpinBox()
        self.size_box.setRange(0, 200)
        self.size_box.setPrefix("字号 ")
        row_font.addWidget(self.size_box, 1)
        layout.addLayout(row_font)

        row_style = QHBoxLayout()
        self.bold_box = CheckBox("粗体")
        row_style.addWidget(self.bold_box)
        self.italic_box = CheckBox("斜体")
        row_style.addWidget(self.italic_box)
        self.align_box = ComboBox()
        self.align_box.addItems(["居中", "左对齐", "右对齐"])
        row_style.addWidget(self.align_box, 1)
        self.spacing_box = QDoubleSpinBox()
        self.spacing_box.setRange(0.0, 3.0)
        self.spacing_box.setSingleStep(0.05)
        self.spacing_box.setPrefix("行距 ")
        row_style.addWidget(self.spacing_box, 1)
        layout.addLayout(row_style)

        row_color = QHBoxLayout()
        self.fg_button = PushButton("前景色")
        self.fg_button.clicked.connect(lambda: self._pick_colour("fg"))
        row_color.addWidget(self.fg_button)
        self.bg_button = PushButton("描边色")
        self.bg_button.clicked.connect(lambda: self._pick_colour("bg"))
        row_color.addWidget(self.bg_button)
        layout.addLayout(row_color)
        self._fg_colour = ""
        self._bg_colour = ""



        row1 = QHBoxLayout()
        self.btn_apply = PrimaryPushButton(FIF.ACCEPT, "应用并排版")
        self.btn_apply.setToolTip("保存原文/译文/角色/样式，并立即重绘本页")
        self.btn_apply.clicked.connect(self._apply_all)
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
        self.btn_erase = PushButton(FIF.BROOM, "局部重绘")
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

    def show_block(
        self, block: TextBlock | None, effective: dict | None = None
    ) -> None:
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
        rotation = float(getattr(block, "rotation", 0.0) or 0.0)
        extra = f" · 旋转 {rotation:.0f}°" if abs(rotation) > 0.5 else ""
        self.meta.setText(
            f"score={block.ocr_score:.2f} · source={block.ocr_source or '-'} · "
            f"{'气泡内' if block.in_bubble else '背景'}{extra}"
        )
        self.text_edit.setPlainText(block.text)
        self.translation_edit.setPlainText(block.translation)
        self.role_box.setCurrentText(block.role)
        style = block.style or {}
        effective = effective or {}
        categories = {"sans": "黑体", "serif": "宋体", "hand": "手写"}
        category = style.get("font") or effective.get("font", "")
        self.font_box.setCurrentText(categories.get(category, "黑体"))
        self.size_box.setValue(int(style.get("font_size") or 0))
        self.bold_box.setChecked(bool(style.get("bold", effective.get("bold", False))))
        self.italic_box.setChecked(
            bool(style.get("italic", effective.get("italic", False)))
        )
        aligns = {"left": "左对齐", "right": "右对齐", "center": "居中"}
        self.align_box.setCurrentText(aligns.get(style.get("align", ""), "居中"))
        self.spacing_box.setValue(float(style.get("line_spacing") or 0.0))
        self._fg_colour = style.get("fg", "")
        self._bg_colour = style.get("bg", "")
        self._update_colour_buttons()

    def _pick_colour(self, target: str) -> None:
        current = self._fg_colour if target == "fg" else self._bg_colour
        colour = QColorDialog.getColor(
            __import__("PySide6.QtGui", fromlist=["QColor"]).QColor(current or "#000000"),
            self,
            "选择颜色",
        )
        if not colour.isValid():
            return
        value = colour.name()
        if target == "fg":
            self._fg_colour = value
        else:
            self._bg_colour = value
        self._update_colour_buttons()

    def _update_colour_buttons(self) -> None:
        self.fg_button.setText(
            f"前景色 {self._fg_colour}" if self._fg_colour else "前景色（自动）"
        )
        self.bg_button.setText(
            f"描边色 {self._bg_colour}" if self._bg_colour else "描边色（自动）"
        )

    def _style_dict(self) -> dict:
        categories = {"黑体": "sans", "宋体": "serif", "手写": "hand"}
        aligns = {"居中": "center", "左对齐": "left", "右对齐": "right"}
        style = {
            "font": categories.get(self.font_box.currentText(), "sans"),
            "font_size": int(self.size_box.value()),
            "bold": self.bold_box.isChecked(),
            "italic": self.italic_box.isChecked(),
            "align": aligns.get(self.align_box.currentText(), "center"),
            "line_spacing": float(self.spacing_box.value()),
        }
        if self._fg_colour:
            style["fg"] = self._fg_colour
        if self._bg_colour:
            style["bg"] = self._bg_colour
        return style

    def _apply_all(self) -> None:
        """One button: text, translation, role, style and a fresh render."""
        if self._block_id is None:
            return
        self.blockApplied.emit(
            self._block_id,
            self.text_edit.toPlainText(),
            self.translation_edit.toPlainText(),
            self.role_box.currentText(),
            self._style_dict(),
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


class SettingsSheet(QWidget):
    """Accent colour, translation endpoint and environment overview."""

    apiConfigured = Signal()

    def __init__(self) -> None:
        super().__init__()
        layout = QVBoxLayout(self)
        layout.setContentsMargins(10, 8, 10, 8)

        layout.addWidget(BodyLabel("翻译接口"))
        self.preset_box = ComboBox()
        self.preset_box.addItems(
            ["DeepSeek 云端", "Ollama 本地", "LM Studio 本地", "llama.cpp 本地", "自定义"]
        )
        self.preset_box.currentIndexChanged.connect(self._apply_preset)
        layout.addWidget(self.preset_box)
        self.api_key = LineEdit()
        self.api_key.setPlaceholderText("MANGATL_API_KEY，例如 sk-…")
        self.api_key.setEchoMode(LineEdit.EchoMode.Password)
        layout.addWidget(self.api_key)
        self.base_url = LineEdit()
        self.base_url.setPlaceholderText("https://api.deepseek.com/v1")
        layout.addWidget(self.base_url)
        self.model_name = LineEdit()
        self.model_name.setPlaceholderText("deepseek-chat")
        layout.addWidget(self.model_name)
        self.remember_box = CheckBox("记住 Key（Windows DPAPI 加密）")
        layout.addWidget(self.remember_box)
        api_row = QHBoxLayout()
        self.btn_api = PrimaryPushButton(FIF.ACCEPT, "应用接口设置")
        self.btn_api.setMinimumHeight(32)
        self.btn_api.clicked.connect(self._apply_api)
        api_row.addWidget(self.btn_api)
        self.api_status = CaptionLabel("")
        api_row.addWidget(self.api_status, 1)
        layout.addLayout(api_row)
        layout.addWidget(
            CaptionLabel(
                "设置保存在 data/settings.json；"
                "Key 用 DPAPI 加密后写入 data/secrets.bin。"
            )
        )

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


class SearchDialog(QDialog):
    """Global block search as a dialog (the rail keeps only editing/run/settings)."""

    def __init__(self, project: Project, parent=None) -> None:
        super().__init__(parent)
        self.setWindowTitle("搜索文本块")
        self.resize(900, 600)
        layout = QVBoxLayout(self)
        self.sheet = SearchSheet(project)
        layout.addWidget(self.sheet)

    def refresh(self) -> None:
        self.sheet.refresh()


def _settings_apply_preset(self) -> None:
    from mangatl.adapters.translators.openai_compat import PROFILES

    profiles = ["openai", "ollama", "lmstudio", "llamacpp", None]
    profile = profiles[self.preset_box.currentIndex()]
    if profile is None:
        return
    base, model, needs_key = PROFILES[profile]
    self.base_url.setText(base)
    self.model_name.setText(model)
    self.api_key.setEnabled(needs_key)
    if not needs_key:
        self.api_key.setPlaceholderText("本地模型通常不需要 Key")


def _settings_apply_api(self) -> None:
    import os

    from mangatl.io import settings as prefs

    profiles = ["openai", "ollama", "lmstudio", "llamacpp", "openai"]
    profile = profiles[self.preset_box.currentIndex()]
    key = self.api_key.text().strip()
    base = self.base_url.text().strip()
    model = self.model_name.text().strip()
    if profile == "openai" and not key:
        self.api_status.setText("云端翻译需要 Key")
        return
    if key:
        os.environ["MANGATL_API_KEY"] = key
    if base:
        os.environ["MANGATL_BASE_URL"] = base
    if model:
        os.environ["MANGATL_MODEL"] = model
    prefs.save_settings({"profile": profile, "base_url": base, "model": model})
    if key and self.remember_box.isChecked():
        stored = prefs.save_api_key(key)
        self.api_status.setText(
            "已加密保存" if stored else "DPAPI 不可用，仅本次运行"
        )
    else:
        prefs.clear_api_key()
        self.api_status.setText("已写入当前进程（未保存 Key）")
    self.apiConfigured.emit()


def _settings_load_saved(self) -> None:
    import os

    from mangatl.io import secrets as secure
    from mangatl.io import settings as prefs

    saved = prefs.load_settings()
    profile = saved.get("profile", "openai")
    names = ["openai", "ollama", "lmstudio", "llamacpp"]
    self.preset_box.setCurrentIndex(
        names.index(profile) if profile in names else 4
    )
    self.base_url.setText(
        saved.get("base_url") or os.environ.get("MANGATL_BASE_URL", "")
    )
    self.model_name.setText(
        saved.get("model") or os.environ.get("MANGATL_MODEL", "")
    )
    if os.environ.get("MANGATL_API_KEY"):
        self.api_key.setText(os.environ["MANGATL_API_KEY"])
    stored = secure.load_key(prefs.SECRETS_PATH) is not None
    self.remember_box.setChecked(stored)
    self.api_status.setText("已加密保存" if stored else "未保存 Key")


# Attach the handler defined above (kept out of the class body to keep it readable).
SettingsSheet._apply_api = _settings_apply_api
SettingsSheet._apply_preset = _settings_apply_preset
SettingsSheet._load_saved = _settings_load_saved


def build_sheets(project: Project, engines_provider=None) -> dict[str, QWidget]:
    """Create the standard module panels (run doubles as the batch panel)."""
    from mangatl.gui.batch import BatchSheet

    settings = SettingsSheet()
    settings._load_saved()
    return {
        "editor": EditorSheet(),
        "run": BatchSheet(project, engines_provider),
        "settings": settings,
    }
