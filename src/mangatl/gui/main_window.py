"""Main window: thumbnails, sheet-style page tabs, canvas and inspector."""

from __future__ import annotations

import os
from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtGui import QAction, QKeySequence
from PySide6.QtWidgets import (
    QComboBox,
    QDockWidget,
    QHBoxLayout,
    QInputDialog,
    QLabel,
    QMainWindow,
    QMessageBox,
    QPushButton,
    QTextEdit,
    QToolBar,
    QVBoxLayout,
    QWidget,
)

from mangatl.domain.project import Project
from mangatl.gui.canvas import PageCanvas
from mangatl.gui.editor import PageEditor
from mangatl.gui.pages import PageTabs, ThumbnailList
from mangatl.gui.search import GlobalSearchDialog
from mangatl.gui.theme import icon, toolbar_icon_size


class MainWindow(QMainWindow):
    """Editor window for one project directory."""

    def __init__(self, project_dir: Path) -> None:
        super().__init__()
        self.setWindowTitle(f"mangatl — {project_dir.name}")
        self.resize(1500, 940)

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
        self._build_pages()
        self._build_inspector()
        self.statusBar().showMessage("就绪")

        self.refresh_pages()
        if len(self.project):
            self.load_page(0)
        else:
            self.statusBar().showMessage("项目里没有图片：请把页面放进该目录")

    # -- construction -----------------------------------------------------
    def _action(self, icon_name: str, text: str, shortcut=None, checkable=False) -> QAction:
        """Create a toolbar action with an icon and optional shortcut."""
        action = QAction(icon(icon_name), text, self)
        action.setCheckable(checkable)
        if shortcut is not None:
            action.setShortcut(QKeySequence(shortcut))
        return action

    def _build_toolbar(self) -> None:
        bar = QToolBar("工具", self)
        bar.setMovable(False)
        bar.setIconSize(toolbar_icon_size())
        self.addToolBar(bar)

        self.act_select = self._action("fa6s.arrow-pointer", "选择", checkable=True)
        self.act_select.setChecked(True)
        self.act_select.triggered.connect(lambda: self._set_mode("select"))
        self.act_lasso = self._action("fa6s.lasso", "套索", checkable=True)
        self.act_lasso.triggered.connect(lambda: self._set_mode("lasso"))
        self.act_rect = self._action("fa6s.vector-square", "矩形", checkable=True)
        self.act_rect.triggered.connect(lambda: self._set_mode("rect"))
        for action in (self.act_select, self.act_lasso, self.act_rect):
            bar.addAction(action)

        bar.addSeparator()
        self.act_fit = self._action("fa6s.expand", "适应窗口", "F")
        self.act_fit.triggered.connect(lambda: self.canvas.fit())
        bar.addAction(self.act_fit)
        self.act_rotate = self._action("fa6s.rotate-right", "旋转 90°", "R")
        self.act_rotate.triggered.connect(lambda: self.canvas.rotate_view())
        bar.addAction(self.act_rotate)

        bar.addSeparator()
        self.act_prev = self._action("fa6s.chevron-left", "上一页", "PgUp")
        self.act_prev.triggered.connect(lambda: self.load_page(self.page_index - 1))
        self.act_next = self._action("fa6s.chevron-right", "下一页", "PgDown")
        self.act_next.triggered.connect(lambda: self.load_page(self.page_index + 1))
        bar.addAction(self.act_prev)
        bar.addAction(self.act_next)

        bar.addSeparator()
        self.act_search = self._action("fa6s.magnifying-glass", "全局搜索", "Ctrl+G")
        self.act_search.triggered.connect(self.open_search)
        bar.addAction(self.act_search)
        self.act_run = self._action("fa6s.play", "运行本页", "F5")
        self.act_run.triggered.connect(lambda: self.run_page(self.page_index))
        bar.addAction(self.act_run)

        self.act_undo = self._action("fa6s.rotate-left", "撤销", "Ctrl+Z")
        self.act_undo.triggered.connect(self.undo)
        bar.addAction(self.act_undo)
        self.act_save = self._action("fa6s.floppy-disk", "保存", "Ctrl+S")
        self.act_save.triggered.connect(self.save)
        bar.addAction(self.act_save)

    def _build_central(self) -> None:
        container = QWidget()
        layout = QVBoxLayout(container)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)
        self.canvas = PageCanvas(self)
        self.canvas.blockClicked.connect(self.select_block)
        self.canvas.lassoFinished.connect(self.on_lasso)
        self.canvas.rectFinished.connect(self.on_rect)
        self.canvas.cursorMoved.connect(
            lambda x, y: self.statusBar().showMessage(f"x={x} y={y}")
        )
        layout.addWidget(self.canvas, 1)
        self.tabs = PageTabs()
        self.tabs.pageSelected.connect(self.load_page)
        self.tabs.pageAction.connect(self.on_page_action)
        layout.addWidget(self.tabs)
        self.setCentralWidget(container)

    def _build_pages(self) -> None:
        dock = QDockWidget("页面", self)
        dock.setFeatures(QDockWidget.DockWidgetFeature.DockWidgetMovable)
        self.page_list = ThumbnailList()
        self.page_list.pageSelected.connect(self.load_page)
        self.page_list.pageAction.connect(self.on_page_action)
        dock.setWidget(self.page_list)
        dock.setMinimumWidth(190)
        self.addDockWidget(Qt.DockWidgetArea.LeftDockWidgetArea, dock)

    def _build_inspector(self) -> None:
        dock = QDockWidget("文本块", self)
        dock.setMinimumWidth(330)
        panel = QWidget()
        layout = QVBoxLayout(panel)

        self.info = QLabel("未选中")
        self.info.setWordWrap(True)
        layout.addWidget(self.info)

        layout.addWidget(QLabel("原文（可手工修正）"))
        self.text_edit = QTextEdit()
        self.text_edit.setFixedHeight(88)
        layout.addWidget(self.text_edit)

        layout.addWidget(QLabel("译文"))
        self.translation_edit = QTextEdit()
        self.translation_edit.setFixedHeight(88)
        layout.addWidget(self.translation_edit)

        layout.addWidget(QLabel("角色"))
        self.role_box = QComboBox()
        self.role_box.addItems(["dialogue", "sfx", "symbol", "texture"])
        layout.addWidget(self.role_box)

        row = QHBoxLayout()
        self.btn_apply = QPushButton("应用文本")
        self.btn_apply.clicked.connect(self.apply_text)
        row.addWidget(self.btn_apply)
        self.btn_reocr = QPushButton("重新识别")
        self.btn_reocr.clicked.connect(self.reocr_block)
        row.addWidget(self.btn_reocr)
        layout.addLayout(row)

        row2 = QHBoxLayout()
        self.btn_translate = QPushButton("翻译此块")
        self.btn_translate.clicked.connect(self.translate_block)
        row2.addWidget(self.btn_translate)
        self.btn_render = QPushButton("重新排版")
        self.btn_render.clicked.connect(self.rerender)
        row2.addWidget(self.btn_render)
        layout.addLayout(row2)

        layout.addWidget(QLabel("区域操作（套索/矩形后执行）"))
        self.btn_detect = QPushButton("区域重新检测")
        self.btn_detect.clicked.connect(self.redetect_region)
        layout.addWidget(self.btn_detect)
        self.btn_erase = QPushButton("区域重新擦除")
        self.btn_erase.clicked.connect(self.erase_region)
        layout.addWidget(self.btn_erase)
        self.btn_add = QPushButton("区域添加文本块")
        self.btn_add.clicked.connect(self.add_region_block)
        layout.addWidget(self.btn_add)

        row3 = QHBoxLayout()
        self.btn_delete = QPushButton("删除选中块")
        self.btn_delete.clicked.connect(self.delete_block)
        row3.addWidget(self.btn_delete)
        self.btn_open = QPushButton("打开结果图")
        self.btn_open.clicked.connect(self.open_result)
        row3.addWidget(self.btn_open)
        layout.addLayout(row3)

        layout.addStretch(1)
        dock.setWidget(panel)
        self.addDockWidget(Qt.DockWidgetArea.RightDockWidgetArea, dock)

    # -- pages ------------------------------------------------------------
    def refresh_pages(self) -> None:
        """Rebuild the tab bar and thumbnail list from the project."""
        names = [page.name for page in self.project]
        self.tabs.set_pages(names)
        self.page_list.set_pages(list(self.project), self.project.directory)
        for index, page in enumerate(self.project):
            self.tabs.update_page(index, page)
            self.page_list.update_page(index, page)

    def load_page(self, index: int) -> None:
        if not len(self.project):
            return
        index = max(0, min(index, len(self.project) - 1))
        self.page_index = index
        self.page_list.blockSignals(True)
        self.page_list.setCurrentRow(index)
        self.page_list.blockSignals(False)
        self.tabs.select(index)
        page = list(self.project)[index]
        self.editor = PageEditor(self.project, page)
        self.selected_id = None
        self.region = None
        self._undo.clear()
        self.canvas.show_image(self.editor.image_path)
        self.canvas.set_blocks(page.blocks)
        self.info.setText(f"{page.name} — {len(page.blocks)} 块")
        self.statusBar().showMessage(f"已加载 {page.name}")

    def on_page_action(self, action: str, index: int) -> None:
        """Handle the page-level context-menu actions."""
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
        self.statusBar().showMessage(f"已重命名为 {new_name}")

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
        """Run the automatic pipeline for one page."""
        from mangatl.core.config import RunConfig
        from mangatl.gui.pipeline_bridge import build_default_service

        page = list(self.project)[index]
        try:
            service = build_default_service(self.project)
            summary = service.run(RunConfig(), only={page.name})
        except Exception as exc:  # noqa: BLE001 - surface the failure in the GUI
            QMessageBox.warning(self, "运行失败", str(exc))
            return
        self.refresh_pages()
        self.load_page(index)
        self.statusBar().showMessage(
            f"{page.name}: 成功 {summary.ok}，失败 {summary.failed}，块 {summary.blocks}"
        )

    def save(self) -> None:
        self.project.save()
        self.statusBar().showMessage("已保存 project.json")

    def open_search(self) -> None:
        dialog = GlobalSearchDialog(self.project, self)
        dialog.jumpRequested.connect(self._jump_to_block)
        dialog.exec()

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
            f"#{block.id} {block.role} {'竖排' if block.vertical else '横排'} "
            f"score={block.ocr_score:.2f} source={block.ocr_source or '-'}"
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
            QMessageBox.warning(self, "翻译不可用", str(exc))
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
        self.statusBar().showMessage(f"已选择区域（{len(points)} 点），选择右侧操作")

    def on_rect(self, box: tuple) -> None:
        x1, y1, x2, y2 = box
        self.region = [(x1, y1), (x2, y1), (x2, y2), (x1, y2)]
        self.statusBar().showMessage("已选择矩形区域，选择右侧操作")

    def _require_region(self) -> bool:
        if self.region is None:
            QMessageBox.information(self, "需要区域", "先用套索或矩形工具框选一块区域")
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

    # -- misc -------------------------------------------------------------
    def _set_mode(self, mode: str) -> None:
        self.canvas.set_mode(mode)
        self.act_select.setChecked(mode == "select")
        self.act_lasso.setChecked(mode == "lasso")
        self.act_rect.setChecked(mode == "rect")
        self.statusBar().showMessage(f"工具：{mode}")
