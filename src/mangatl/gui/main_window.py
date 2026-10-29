"""Fluent main window: page sidebar, canvas, inspector and module sheets."""

from __future__ import annotations

import os
from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QDockWidget,
    QHBoxLayout,
    QInputDialog,
    QMainWindow,
    QMessageBox,
    QToolBar,
    QVBoxLayout,
    QWidget,
)
from qfluentwidgets import (
    BodyLabel,
    CaptionLabel,
    CardWidget,
    ComboBox,
    InfoBar,
    InfoBarPosition,
    PrimaryPushButton,
    PushButton,
    TextEdit,
    TransparentToolButton,
)
from qfluentwidgets import (
    FluentIcon as FIF,
)

from mangatl.domain.project import Project
from mangatl.gui.canvas import PageCanvas
from mangatl.gui.editor import PageEditor
from mangatl.gui.fluent import set_accent
from mangatl.gui.pages import ThumbnailList
from mangatl.gui.sheets import build_sheets


class MainWindow(QMainWindow):
    """Editor window for one project directory."""

    def __init__(self, project_dir: Path) -> None:
        super().__init__()
        self.setWindowTitle(f"mangatl — {project_dir.name}")
        self.resize(1560, 980)

        self.project = Project.open(project_dir)
        if not len(self.project):
            self.project.scan()
        self.page_index = 0
        self.editor: PageEditor | None = None
        self.selected_id: int | None = None
        self.region: list[tuple[float, float]] | None = None
        self._undo: list[list[dict]] = []

        self._build_toolbar()
        self._build_central()
        self._build_sidebar()
        self._build_inspector()
        self._build_sheets()
        self.statusBar().showMessage("就绪")

        self.refresh_pages()
        if len(self.project):
            self.load_page(0)
        else:
            self.statusBar().showMessage("项目里没有图片：请把页面放进该目录")

    # -- construction -----------------------------------------------------
    def _tool_button(self, icon, tooltip: str, slot, checkable: bool = False):
        button = TransparentToolButton(icon)
        button.setToolTip(tooltip)
        button.setCheckable(checkable)
        button.clicked.connect(slot)
        return button

    def _build_toolbar(self) -> None:
        bar = QToolBar("工具", self)
        bar.setMovable(False)
        self.addToolBar(bar)

        self.btn_select = self._tool_button(
            FIF.CLEAR_SELECTION, "选择", lambda: self._set_mode("select"), True
        )
        self.btn_lasso = self._tool_button(
            FIF.CUT, "套索", lambda: self._set_mode("lasso"), True
        )
        self.btn_rect = self._tool_button(
            FIF.FULL_SCREEN, "矩形", lambda: self._set_mode("rect"), True
        )
        self.btn_select.setChecked(True)
        for button in (self.btn_select, self.btn_lasso, self.btn_rect):
            bar.addWidget(button)

        bar.addSeparator()
        bar.addWidget(self._tool_button(FIF.FIT_PAGE, "适应窗口", lambda: self.canvas.fit()))
        bar.addWidget(
            self._tool_button(FIF.ROTATE, "旋转 90°", lambda: self.canvas.rotate_view())
        )

        bar.addSeparator()
        bar.addWidget(
            self._tool_button(
                FIF.LEFT_ARROW, "上一页", lambda: self.load_page(self.page_index - 1)
            )
        )
        bar.addWidget(
            self._tool_button(
                FIF.RIGHT_ARROW, "下一页", lambda: self.load_page(self.page_index + 1)
            )
        )

        bar.addSeparator()
        bar.addWidget(self._tool_button(FIF.SEARCH, "全局搜索", self.open_search))
        bar.addWidget(
            self._tool_button(
                FIF.PLAY, "运行本页", lambda: self.run_page(self.page_index)
            )
        )
        bar.addWidget(self._tool_button(FIF.SAVE, "保存", self.save))
        bar.addWidget(self._tool_button(FIF.RETURN, "撤销", self.undo))

    def _build_central(self) -> None:
        self.canvas = PageCanvas(self)
        self.canvas.blockClicked.connect(self.select_block)
        self.canvas.lassoFinished.connect(self.on_lasso)
        self.canvas.rectFinished.connect(self.on_rect)
        self.canvas.cursorMoved.connect(
            lambda x, y: self.statusBar().showMessage(f"x={x} y={y}")
        )
        self.setCentralWidget(self.canvas)

    def _build_sidebar(self) -> None:
        dock = QDockWidget("页面", self)
        dock.setFeatures(QDockWidget.DockWidgetFeature.DockWidgetMovable)
        self.page_list = ThumbnailList()
        self.page_list.pageSelected.connect(self.load_page)
        self.page_list.pageAction.connect(self.on_page_action)
        dock.setWidget(self.page_list)
        dock.setMinimumWidth(200)
        self.addDockWidget(Qt.DockWidgetArea.LeftDockWidgetArea, dock)

    def _build_inspector(self) -> None:
        dock = QDockWidget("文本块", self)
        dock.setMinimumWidth(340)
        panel = QWidget()
        layout = QVBoxLayout(panel)
        layout.setContentsMargins(8, 8, 8, 8)

        card = CardWidget()
        card_layout = QVBoxLayout(card)
        self.info = BodyLabel("未选中文本块")
        self.info.setWordWrap(True)
        card_layout.addWidget(self.info)
        self.meta = CaptionLabel("")
        card_layout.addWidget(self.meta)
        layout.addWidget(card)

        layout.addWidget(CaptionLabel("原文（可手工修正）"))
        self.text_edit = TextEdit()
        self.text_edit.setFixedHeight(92)
        layout.addWidget(self.text_edit)

        layout.addWidget(CaptionLabel("译文"))
        self.translation_edit = TextEdit()
        self.translation_edit.setFixedHeight(92)
        layout.addWidget(self.translation_edit)

        layout.addWidget(CaptionLabel("角色"))
        self.role_box = ComboBox()
        self.role_box.addItems(["dialogue", "sfx", "symbol", "texture"])
        layout.addWidget(self.role_box)

        row = QHBoxLayout()
        self.btn_apply = PrimaryPushButton(FIF.ACCEPT, "应用文本")
        self.btn_apply.clicked.connect(self.apply_text)
        row.addWidget(self.btn_apply)
        self.btn_reocr = PushButton(FIF.SYNC, "重新识别")
        self.btn_reocr.clicked.connect(self.reocr_block)
        row.addWidget(self.btn_reocr)
        layout.addLayout(row)

        row2 = QHBoxLayout()
        self.btn_translate = PushButton(FIF.GLOBE, "翻译此块")
        self.btn_translate.clicked.connect(self.translate_block)
        row2.addWidget(self.btn_translate)
        self.btn_render = PushButton(FIF.PHOTO, "重新排版")
        self.btn_render.clicked.connect(self.rerender)
        row2.addWidget(self.btn_render)
        layout.addLayout(row2)

        row3 = QHBoxLayout()
        self.btn_delete = PushButton(FIF.DELETE, "删除")
        self.btn_delete.clicked.connect(self.delete_block)
        row3.addWidget(self.btn_delete)
        self.btn_open = PushButton(FIF.FOLDER, "打开结果图")
        self.btn_open.clicked.connect(self.open_result)
        row3.addWidget(self.btn_open)
        layout.addLayout(row3)

        layout.addStretch(1)
        dock.setWidget(panel)
        self.addDockWidget(Qt.DockWidgetArea.RightDockWidgetArea, dock)

    def _build_sheets(self) -> None:
        from mangatl.gui.sheets import SheetHost

        self.sheets = build_sheets(self.project)
        self.sheet_host = SheetHost(self.sheets)
        dock = QDockWidget("模块", self)
        dock.setFeatures(QDockWidget.DockWidgetFeature.DockWidgetMovable)
        dock.setWidget(self.sheet_host)
        dock.setMinimumHeight(170)
        self.addDockWidget(Qt.DockWidgetArea.BottomDockWidgetArea, dock)
        self.sheet_dock = dock
        self.resizeDocks([dock], [230], Qt.Orientation.Vertical)

        self.sheets["editor"].regionAction.connect(self.on_sheet_region)
        self.sheets["blocks"].blockSelected.connect(self.select_block)
        self.sheets["blocks"].blockEdited.connect(self.on_table_edit)
        self.sheets["search"].jumpRequested.connect(self._jump_to_block)
        self.sheets["run"].runRequested.connect(self.on_run_requested)
        self.sheets["settings"].accentChanged.connect(self.on_accent)

    # -- pages ------------------------------------------------------------
    def refresh_pages(self) -> None:
        pages = list(self.project)
        self.page_list.set_pages(pages, self.project.directory)
        self.sheets["search"].project = self.project
        self.sheets["search"].refresh()
        self._refresh_sheets()

    def _refresh_sheets(self) -> None:
        page = list(self.project)[self.page_index] if len(self.project) else None
        self.sheets["editor"].show_page(page)
        self.sheets["blocks"].show_page(page)

    def load_page(self, index: int) -> None:
        if not len(self.project):
            return
        index = max(0, min(index, len(self.project) - 1))
        self.page_index = index
        self.page_list.blockSignals(True)
        self.page_list.setCurrentRow(index)
        self.page_list.blockSignals(False)
        page = list(self.project)[index]
        self.editor = PageEditor(self.project, page)
        self.selected_id = None
        self.region = None
        self._undo.clear()
        self.canvas.show_image(self.editor.image_path)
        self.canvas.set_blocks(page.blocks)
        self._refresh_sheets()
        self.statusBar().showMessage(f"已加载 {page.name}")

    def on_page_action(self, action: str, index: int) -> None:
        if action == "add":
            self.project.scan()
            self.refresh_pages()
            return
        if index < 0 or index >= len(self.project):
            return
        if action == "run":
            self.run_page(index)
        elif action == "reset":
            self.reset_page(index)
        elif action == "open":
            page = list(self.project)[index]
            result = self.project.directory / "result" / page.name
            if result.is_file():
                os.startfile(result)  # noqa: S606 - open a local file
            else:
                self.statusBar().showMessage("该页还没有排版结果")
        elif action == "rename":
            self.rename_page(index)

    def rename_page(self, index: int) -> None:
        page = list(self.project)[index]
        new_name, ok = QInputDialog.getText(
            self, "重命名页面", "新文件名：", text=page.name
        )
        if not ok or not new_name.strip() or new_name == page.name:
            return
        old_path = self.project.directory / page.name
        new_path = self.project.directory / new_name
        if new_path.exists():
            QMessageBox.warning(self, "重命名失败", "目标文件已存在")
            return
        old_path.rename(new_path)
        pages = self.project.pages
        pages[new_name] = pages.pop(page.name)
        pages[new_name].name = new_name
        self.project.save()
        self.refresh_pages()
        self.load_page(index)

    def reset_page(self, index: int) -> None:
        page = list(self.project)[index]
        for stage in list(page.stage):
            page.stage[stage] = 0
        for block in page.blocks:
            block.needs_review = False
        self.project.save()
        self.refresh_pages()
        self.statusBar().showMessage(f"{page.name} 已重置")

    def run_page(self, index: int) -> None:
        from mangatl.core.config import RunConfig
        from mangatl.gui.pipeline_bridge import build_default_service

        page = list(self.project)[index]
        try:
            service = build_default_service(self.project)
            summary = service.run(RunConfig(), only={page.name})
        except Exception as exc:  # noqa: BLE001 - surface the failure in the GUI
            QMessageBox.warning(self, "运行失败", str(exc))
            return
        self.sheets["run"].append(
            f"{page.name}: 成功 {summary.ok} 失败 {summary.failed} 块 {summary.blocks}"
        )
        self.refresh_pages()
        self.load_page(index)
        self.statusBar().showMessage(
            f"{page.name}: 成功 {summary.ok}，失败 {summary.failed}，块 {summary.blocks}"
        )

    def save(self) -> None:
        self.project.save()
        self.statusBar().showMessage("已保存 project.json")

    def open_search(self) -> None:
        self.sheet_host.show_sheet("search")
        self.sheet_dock.show()

    def _jump_to_block(self, page_index: int, block_id: int) -> None:
        self.load_page(page_index)
        self.select_block(block_id)

    # -- selection --------------------------------------------------------
    def select_block(self, block_id: int) -> None:
        if self.editor is None:
            return
        block = next((b for b in self.editor.page.blocks if b.id == block_id), None)
        if block is None:
            return
        self.selected_id = block_id
        self.text_edit.setPlainText(block.text)
        self.translation_edit.setPlainText(block.translation)
        self.role_box.setCurrentText(block.role)
        self.info.setText(
            f"#{block.id} {block.role} {'竖排' if block.vertical else '横排'}"
        )
        self.meta.setText(
            f"score={block.ocr_score:.2f} · source={block.ocr_source or '-'} · "
            f"{'气泡内' if block.in_bubble else '背景'}"
        )
        self.canvas.set_blocks(self.editor.page.blocks, [block_id])

    def _selected(self):
        if self.editor is None or self.selected_id is None:
            return None
        return next(
            (b for b in self.editor.page.blocks if b.id == self.selected_id), None
        )

    # -- block actions ----------------------------------------------------
    def _snapshot(self) -> None:
        if self.editor is not None:
            self._undo.append([dict(b.to_dict()) for b in self.editor.page.blocks])
            if len(self._undo) > 50:
                self._undo.pop(0)

    def undo(self) -> None:
        if self.editor is None or not self._undo:
            return
        from mangatl.domain.block import TextBlock

        snapshot = self._undo.pop()
        self.editor.page.blocks = [TextBlock.from_dict(item) for item in snapshot]
        self.editor.project.save()
        self.canvas.set_blocks(self.editor.page.blocks)
        self.refresh_pages()
        self.statusBar().showMessage("已撤销")

    def apply_text(self) -> None:
        block = self._selected()
        if block is None or self.editor is None:
            return
        self._snapshot()
        self.editor.set_text(block, self.text_edit.toPlainText())
        self.editor.set_translation(block, self.translation_edit.toPlainText())
        block.role = self.role_box.currentText()
        self.editor.project.save()
        self.canvas.set_blocks(self.editor.page.blocks, [block.id])
        self.refresh_pages()
        self.statusBar().showMessage(f"已更新 #{block.id}")

    def on_table_edit(self, block_id: int, text: str, translation: str) -> None:
        block = (
            next((b for b in self.editor.page.blocks if b.id == block_id), None)
            if self.editor
            else None
        )
        if block is None:
            return
        block.text = text
        block.translation = translation
        block.ocr_source = "manual"
        block.needs_review = False
        self.editor.project.save()
        self.statusBar().showMessage(f"表格已更新 #{block_id}")

    def reocr_block(self) -> None:
        block = self._selected()
        if block is None or self.editor is None:
            return
        self._snapshot()
        from mangatl.adapters.ocr.manga_ocr import MangaOcrAdapter

        adapter = MangaOcrAdapter()
        probe = adapter.recognize(self.editor.image_path, [block])[0]
        self.text_edit.setPlainText(probe.text)
        self.editor.project.save()
        self.statusBar().showMessage(f"重新识别 #{probe.id}: {probe.text[:20]}")

    def translate_block(self) -> None:
        block = self._selected()
        if block is None or self.editor is None:
            return
        from mangatl.adapters.translators.openai_compat import (
            LlmConfig,
            OpenAiTranslator,
            TranslationError,
        )

        try:
            translator = OpenAiTranslator(LlmConfig.from_env())
        except TranslationError as exc:
            InfoBar.warning(
                "翻译不可用", str(exc), parent=self, position=InfoBarPosition.TOP
            )
            return
        translator.translate([block], {"target_lang": "简体中文"})
        self.translation_edit.setPlainText(block.translation)
        self.editor.project.save()
        self.refresh_pages()

    def delete_block(self) -> None:
        block = self._selected()
        if block is None or self.editor is None:
            return
        self._snapshot()
        self.editor.remove_blocks([block])
        self.selected_id = None
        self.canvas.set_blocks(self.editor.page.blocks)
        self.refresh_pages()
        self.statusBar().showMessage("已删除")

    def rerender(self) -> None:
        if self.editor is None:
            return
        path = self.editor.rerender()
        self.canvas.show_image(path)
        self.canvas.set_blocks(self.editor.page.blocks)
        self.refresh_pages()
        self.statusBar().showMessage(f"已排版 -> {path}")

    def open_result(self) -> None:
        if self.editor is None:
            return
        path = self.editor.result_path
        if path.is_file():
            os.startfile(path)  # noqa: S606 - open a local file

    # -- region actions ---------------------------------------------------
    def on_lasso(self, points: list) -> None:
        self.region = points
        self.statusBar().showMessage(
            f"已选择区域（{len(points)} 点），选“编辑”页签里的操作"
        )

    def on_rect(self, box: tuple) -> None:
        x1, y1, x2, y2 = box
        self.region = [(x1, y1), (x2, y1), (x2, y2), (x1, y2)]
        self.statusBar().showMessage("已选择矩形区域，选“编辑”页签里的操作")

    def on_sheet_region(self, action: str) -> None:
        if action == "detect":
            self.redetect_region()
        elif action == "erase":
            self.erase_region()
        elif action == "add":
            self.add_region_block()
        elif action == "render":
            self.rerender()

    def _require_region(self) -> bool:
        if self.region is None:
            InfoBar.info("需要区域", "先用套索或矩形工具框选一块区域", parent=self)
            return False
        return True

    def redetect_region(self) -> None:
        if self.editor is None or not self._require_region():
            return
        self._snapshot()
        added = self.editor.redetect(self.region or [])
        self.canvas.set_blocks(self.editor.page.blocks)
        self.refresh_pages()
        self.statusBar().showMessage(f"区域检测：新增 {len(added)} 块")

    def erase_region(self) -> None:
        if self.editor is None or not self._require_region():
            return
        self._snapshot()
        path = self.editor.erase_region(self.region or [])
        self.canvas.show_image(path)
        self.canvas.set_blocks(self.editor.page.blocks)
        self.refresh_pages()
        self.statusBar().showMessage(f"区域擦除 -> {path}")

    def add_region_block(self) -> None:
        if self.editor is None or not self._require_region():
            return
        from mangatl.gui.geometry import polygon_bbox

        self._snapshot()
        box = polygon_bbox(self.region or [])
        block = self.editor.add_block(box, text="", translation="")
        self.canvas.set_blocks(self.editor.page.blocks, [block.id])
        self.select_block(block.id)
        self.text_edit.setFocus()
        self.statusBar().showMessage("已添加文本块，输入内容后点“应用文本”")

    # -- run / theme ------------------------------------------------------
    def on_run_requested(self, stages, all_pages: bool) -> None:
        from mangatl.core.config import RunConfig
        from mangatl.gui.pipeline_bridge import build_default_service

        if not stages:
            InfoBar.warning("未选择阶段", "至少勾选一个阶段", parent=self)
            return
        try:
            service = build_default_service(self.project)
            only = None if all_pages else {list(self.project)[self.page_index].name}
            summary = service.run(RunConfig(stages=tuple(stages)), only=only)
        except Exception as exc:  # noqa: BLE001 - show failures in the log
            self.sheets["run"].append(f"运行失败：{exc}")
            InfoBar.error("运行失败", str(exc), parent=self)
            return
        self.sheets["run"].append(
            f"完成：成功 {summary.ok}，失败 {summary.failed}，"
            f"跳过 {summary.skipped}，块 {summary.blocks}"
        )
        self.refresh_pages()
        self.load_page(self.page_index)

    def on_accent(self, colour: str) -> None:
        set_accent(colour)
        self.statusBar().showMessage(f"强调色已切换为 {colour}")

    # -- misc -------------------------------------------------------------
    def _set_mode(self, mode: str) -> None:
        self.canvas.set_mode(mode)
        self.btn_select.setChecked(mode == "select")
        self.btn_lasso.setChecked(mode == "lasso")
        self.btn_rect.setChecked(mode == "rect")
        self.statusBar().showMessage(f"工具：{mode}")
