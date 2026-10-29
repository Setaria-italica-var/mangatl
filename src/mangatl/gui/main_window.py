"""Fluent editor: page sidebar, canvas, right module rail and a slim engine bar."""

from __future__ import annotations

import os
from pathlib import Path

from PySide6.QtCore import QPointF, Qt, QTimer
from PySide6.QtGui import QAction, QKeySequence
from PySide6.QtWidgets import (
    QComboBox,
    QDockWidget,
    QHBoxLayout,
    QInputDialog,
    QLabel,
    QMainWindow,
    QMessageBox,
    QSlider,
    QStackedWidget,
    QToolBar,
    QVBoxLayout,
    QWidget,
)
from qfluentwidgets import (
    Action,
    InfoBar,
    InfoBarPosition,
    RoundMenu,
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
from mangatl.gui.sheets import SHEET_ICONS, SHEET_TITLES, build_sheets

ENGINE_OPTIONS = {
    "detector": ("ctd",),
    "ocr": ("mit_manga", "manga_ocr", "mit48px_ctc", "rapidocr"),
    "inpainter": ("masked", "lama"),
    "translator": ("openai", "echo"),
}


class MainWindow(QMainWindow):
    """Editor window for one project directory."""

    def __init__(self, project_dir: Path) -> None:
        super().__init__()
        self.setWindowTitle(f"mangatl — {project_dir.name}")
        self.resize(1560, 960)

        from mangatl.gui import recent

        self.project = Project.open(project_dir)
        recent.remember(project_dir)
        if not len(self.project):
            self.project.scan()
        self.page_index = 0
        self.editor: PageEditor | None = None
        self.selected_id: int | None = None
        self.selected_ids: list[int] = []
        self.view_mode = "source"
        self.auto_preview = True
        self._preview_timer = QTimer(self)
        self._preview_timer.setSingleShot(True)
        self._preview_timer.setInterval(350)
        self._preview_timer.timeout.connect(self._auto_rerender)
        self.region: list[tuple[float, float]] | None = None
        self._undo: list[list[dict]] = []

        self._build_toolbar()
        self._build_central()
        self._build_sidebar()
        self._build_module_panel()
        self._build_engine_bar()
        self._install_shortcuts()
        self.statusBar().showMessage("就绪")

        self.refresh_pages()
        if len(self.project):
            self.load_page(0)
        else:
            self.statusBar().showMessage("项目里没有图片：请把页面放进该目录")

    def _install_shortcuts(self) -> None:
        """Global keys: undo/save, previews, fit, rotate, full screen."""
        for keys, slot in (
            ("Ctrl+Z", self.undo),
            ("Ctrl+S", self.save),
            ("Ctrl+1", lambda: self.show_view("source")),
            ("Ctrl+2", lambda: self.show_view("erased")),
            ("Ctrl+3", lambda: self.show_view("result")),
            ("Home", self.canvas.fit),
            ("F", self.canvas.fit),
            ("Esc", self._cancel_selection),
            ("R", self.canvas.rotate_view),
            ("F11", self.toggle_fullscreen),
        ):
            action = QAction(self)
            action.setShortcut(QKeySequence(keys))
            action.triggered.connect(slot)
            self.addAction(action)

    # -- top toolbar ------------------------------------------------------
    def _tool_button(self, icon, tooltip: str, slot, checkable: bool = False):
        button = TransparentToolButton(icon)
        button.setToolTip(tooltip)
        button.setCheckable(checkable)
        button.clicked.connect(slot)
        return button

    def _build_toolbar(self) -> None:
        """Toolbar grouped by task: file, select, view, navigate, act."""
        bar = QToolBar("工具", self)
        bar.setMovable(False)
        bar.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonIconOnly)
        self.addToolBar(bar)

        # file
        bar.addWidget(
            self._tool_button(FIF.FOLDER, "打开文件夹", self.open_folder_dialog)
        )
        bar.addSeparator()

        # selection tools
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

        # preview mode
        self.btn_view_source = self._tool_button(
            FIF.PHOTO, "原图 (Ctrl+1)", lambda: self.show_view("source"), True
        )
        self.btn_view_erased = self._tool_button(
            FIF.BRUSH, "擦除后 (Ctrl+2)", lambda: self.show_view("erased"), True
        )
        self.btn_view_result = self._tool_button(
            FIF.VIEW, "排版结果 (Ctrl+3)", lambda: self.show_view("result"), True
        )
        self.btn_view_source.setChecked(True)
        for button in (self.btn_view_source, self.btn_view_erased, self.btn_view_result):
            bar.addWidget(button)
        self.btn_auto = self._tool_button(
            FIF.SYNC, "自动预览排版", self._toggle_auto_preview, True
        )
        self.btn_auto.setChecked(True)
        bar.addWidget(self.btn_auto)
        bar.addSeparator()

        # view
        bar.addWidget(
            self._tool_button(FIF.FIT_PAGE, "适应窗口", lambda: self.canvas.fit())
        )
        bar.addWidget(
            self._tool_button(FIF.ROTATE, "旋转 90°", lambda: self.canvas.rotate_view())
        )
        bar.addWidget(
            self._tool_button(
                FIF.PAGE_LEFT, "上一页", lambda: self.load_page(self.page_index - 1)
            )
        )
        bar.addWidget(
            self._tool_button(
                FIF.PAGE_RIGHT, "下一页", lambda: self.load_page(self.page_index + 1)
            )
        )
        bar.addWidget(
            self._tool_button(FIF.FULL_SCREEN, "全屏", self.toggle_fullscreen)
        )
        bar.addSeparator()

        # actions
        bar.addWidget(self._tool_button(FIF.SEARCH, "搜索", self.show_search))
        bar.addWidget(
            self._tool_button(
                FIF.PLAY, "运行本页", lambda: self.run_page(self.page_index)
            )
        )
        bar.addWidget(self._tool_button(FIF.SAVE, "保存", self.save))
        bar.addWidget(self._tool_button(FIF.RETURN, "撤销", self.undo))

    # -- canvas / sidebar -------------------------------------------------
    def _build_central(self) -> None:
        self.canvas = PageCanvas(self)
        self.canvas.setMinimumWidth(420)
        self.canvas.blockClicked.connect(self.select_block)
        self.canvas.blockGeometryChanged.connect(self.on_geometry_changed)
        self.canvas.blockRotated.connect(self.on_block_rotated)
        self.canvas.lassoFinished.connect(self.on_lasso)
        self.canvas.rectFinished.connect(self.on_rect)
        self.canvas.cursorMoved.connect(
            lambda x, y: self.statusBar().showMessage(f"x={x} y={y}")
        )
        self.setCentralWidget(self.canvas)
        self._build_selection_bar()
        self.canvas.selectionChanged.connect(self._on_selection_changed)
        self.canvas.selectionIdsChanged.connect(self.on_selection_ids)
        self.canvas.contextMenuRequested.connect(self.on_canvas_menu)

    def _build_selection_bar(self) -> None:
        """Floating actions shown right next to a lasso/rectangle selection."""
        self.selection_bar = QWidget(self.canvas.viewport())
        layout = QHBoxLayout(self.selection_bar)
        layout.setContentsMargins(6, 3, 6, 3)
        layout.setSpacing(2)
        for icon, tip, slot in (
            (FIF.SEARCH, "重新检测", "detect"),
            (FIF.BROOM, "局部重绘", "erase"),
            (FIF.ADD, "添加文本块", "add"),
        ):
            button = TransparentToolButton(icon)
            button.setToolTip(tip)
            button.clicked.connect(lambda _=False, a=slot: self._selection_action(a))
            layout.addWidget(button)
        close = TransparentToolButton(FIF.CLOSE)
        close.setToolTip("取消选区 (Esc)")
        close.clicked.connect(self._cancel_selection)
        layout.addWidget(close)
        self.selection_bar.setObjectName("SelectionBar")
        self.selection_bar.setStyleSheet(
            "QWidget#SelectionBar { background: rgba(40,40,40,220); border-radius: 8px; }"
        )
        self.selection_bar.hide()

    def _on_selection_changed(self, active: bool) -> None:
        if not active:
            self.selection_bar.hide()
            return
        box = self.canvas.selection_bbox()
        if box is None:
            return
        top_left = self.canvas.mapFromScene(QPointF(box[0], box[1]))
        x = max(4, top_left.x())
        y = max(4, top_left.y() - self.selection_bar.sizeHint().height() - 6)
        self.selection_bar.adjustSize()
        self.selection_bar.move(x, y)
        self.selection_bar.show()
        self.selection_bar.raise_()

    def _selection_action(self, action: str) -> None:
        actions = {
            "detect": self.redetect_region,
            "erase": self.erase_region,
            "add": self.add_region_block,
        }
        actions[action]()
        self._finish_selection_action()

    def _clear_region(self) -> None:
        """Forget the lasso/rectangle; block selection is untouched."""
        self.region = None
        self.canvas.clear_selection()

    def _finish_selection_action(self, keep_blocks: bool = True) -> None:
        """A region action consumed the region: drop it but keep block selection."""
        self._clear_region()
        if not keep_blocks:
            self.selected_ids = []
            self.selected_id = None
            if self.editor is not None:
                self.canvas.set_blocks(self.editor.page.blocks)
            self.sheets["editor"].show_block(None)

    def _cancel_selection(self) -> None:
        self.canvas.clear_selection()
        self.selection_bar.hide()

    def _build_sidebar(self) -> None:
        dock = QDockWidget("页面", self)
        dock.setFeatures(QDockWidget.DockWidgetFeature.DockWidgetMovable)
        self.page_list = ThumbnailList()
        self.page_list.pageSelected.connect(self.load_page)
        self.page_list.pageAction.connect(self.on_page_action)
        dock.setWidget(self.page_list)
        dock.setMinimumWidth(190)
        dock.setMaximumWidth(250)
        self.addDockWidget(Qt.DockWidgetArea.LeftDockWidgetArea, dock)

    # -- right module rail ------------------------------------------------
    def _build_module_panel(self) -> None:
        self.sheets = build_sheets(self.project)
        dock = QDockWidget("模块", self)
        dock.setFeatures(QDockWidget.DockWidgetFeature.DockWidgetMovable)
        container = QWidget()
        layout = QHBoxLayout(container)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        rail = QWidget()
        rail.setFixedWidth(46)
        rail_layout = QVBoxLayout(rail)
        rail_layout.setContentsMargins(4, 8, 4, 8)
        rail_layout.setSpacing(4)
        self.rail_buttons: dict[str, TransparentToolButton] = {}
        for key in SHEET_TITLES:
            button = TransparentToolButton(SHEET_ICONS[key])
            button.setToolTip(SHEET_TITLES[key])
            button.setCheckable(True)
            button.clicked.connect(lambda _=False, k=key: self.show_module(k))
            self.rail_buttons[key] = button
            rail_layout.addWidget(button)
        rail_layout.addStretch(1)
        layout.addWidget(rail)

        self.stack = QStackedWidget()
        self._sheet_keys = list(self.sheets)
        for key in self._sheet_keys:
            self.stack.addWidget(self.sheets[key])
        layout.addWidget(self.stack, 1)

        dock.setWidget(container)
        dock.setMinimumWidth(350)
        dock.setMaximumWidth(430)
        self.addDockWidget(Qt.DockWidgetArea.RightDockWidgetArea, dock)
        self.module_dock = dock

        editor = self.sheets["editor"]
        editor.regionAction.connect(self.on_sheet_region)
        editor.blockEdited.connect(self.on_block_edited)
        editor.blockAction.connect(self.on_block_action)
        editor.blockApplied.connect(self.on_block_applied)
        self.sheets["blocks"].blockSelected.connect(self.select_block)
        self.sheets["blocks"].blockEdited.connect(self.on_block_edited)
        self.sheets["search"].jumpRequested.connect(self._jump_to_block)
        self.sheets["run"].runRequested.connect(self.on_run_requested)
        self.sheets["settings"].accentChanged.connect(self.on_accent)

        self.rail_current = "editor"
        self.rail_buttons["editor"].setChecked(True)
        self.stack.setCurrentWidget(self.sheets["editor"])

    def show_module(self, key: str) -> None:
        """Switch the right panel to a module."""
        if key not in self.sheets:
            return
        self.rail_current = key
        for name, button in self.rail_buttons.items():
            button.setChecked(name == key)
        self.stack.setCurrentWidget(self.sheets[key])
        self.module_dock.show()

    def show_search(self) -> None:
        self.show_module("search")
        self.sheets["search"].refresh()

    # -- slim bottom engine bar -------------------------------------------
    def _build_engine_bar(self) -> None:
        bar = QToolBar("引擎", self)
        bar.setMovable(False)
        self.addToolBar(Qt.ToolBarArea.BottomToolBarArea, bar)

        self.engine_boxes: dict[str, QComboBox] = {}
        labels = {
            "detector": "检测",
            "ocr": "OCR",
            "inpainter": "擦除",
            "translator": "翻译",
        }
        for key, options in ENGINE_OPTIONS.items():
            bar.addWidget(QLabel(labels[key]))
            box = QComboBox()
            box.addItems(options)
            self.engine_boxes[key] = box
            bar.addWidget(box)
            bar.addWidget(QLabel(" "))

        bar.addWidget(QLabel("图层透明度"))
        self.opacity_slider = QSlider(Qt.Orientation.Horizontal)
        self.opacity_slider.setRange(0, 100)
        self.opacity_slider.setValue(100)
        self.opacity_slider.setFixedWidth(140)
        self.opacity_slider.valueChanged.connect(self.canvas.set_overlay_opacity)
        bar.addWidget(self.opacity_slider)

    def showEvent(self, event) -> None:  # noqa: N802 - Qt name
        super().showEvent(event)
        self._pending_fit = True
        QTimer.singleShot(0, self._fit_once)

    def resizeEvent(self, event) -> None:  # noqa: N802 - Qt name
        super().resizeEvent(event)
        if getattr(self, "_pending_fit", False):
            self._fit_once()

    def _fit_once(self) -> None:
        """Fit the page once the window has its final size."""
        if not getattr(self, "_pending_fit", False):
            return
        self._pending_fit = False
        self.canvas.fit()

    # -- pages ------------------------------------------------------------
    def refresh_pages(self) -> None:
        current = self.page_index
        self.page_list.set_pages(list(self.project), self.project.directory)
        self.page_list.blockSignals(True)
        self.page_list.setCurrentRow(current)
        self.page_list.blockSignals(False)
        self.sheets["search"].project = self.project
        self.sheets["search"].refresh()
        self._refresh_sheets()

    def _touch_page(self) -> None:
        """Refresh just the current page without rebuilding the sidebar."""
        if not len(self.project):
            return
        page = list(self.project)[self.page_index]
        self.page_list.update_page(self.page_index, page)
        self.sheets["editor"].show_page(page)
        self.sheets["blocks"].show_page(page)

    def _refresh_sheets(self) -> None:
        page = list(self.project)[self.page_index] if len(self.project) else None
        self.sheets["editor"].show_page(page)
        self.sheets["blocks"].show_page(page)

    def load_page(self, index: int, keep_selection: bool = False) -> None:
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
        if not keep_selection:
            # A selection belongs to one page: drop it (and its floating bar) when
            # moving on, otherwise the buttons hover over the new page.
            self.region = None
            self.canvas.clear_selection()
        self._undo.clear()
        self.canvas.show_image(self.editor.image_path, keep_selection=keep_selection)
        self.canvas.set_blocks(page.blocks, self.selected_ids if keep_selection else ())
        self.show_view(self.view_mode, quiet=True)
        # The viewport is not laid out yet during construction; fit once Qt has
        # given the canvas its real size, otherwise the page opens tiny.
        QTimer.singleShot(0, self.canvas.fit)
        self.sheets["editor"].show_block(None)
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

    def _engines(self) -> dict[str, str]:
        return {key: box.currentText() for key, box in self.engine_boxes.items()}

    def run_page(self, index: int) -> None:
        from mangatl.core.config import RunConfig
        from mangatl.gui.pipeline_bridge import build_default_service

        page = list(self.project)[index]
        try:
            service = build_default_service(self.project, **self._engines())
            summary = service.run(RunConfig(), only={page.name})
        except Exception as exc:  # noqa: BLE001 - surface the failure in the GUI
            QMessageBox.warning(self, "运行失败", str(exc))
            return
        self.sheets["run"].append(
            f"{page.name}: 成功 {summary.ok} 失败 {summary.failed} 块 {summary.blocks}"
        )
        self.view_mode = "result"
        self.refresh_pages()
        self.load_page(index, keep_selection=True)
        self.statusBar().showMessage(
            f"{page.name}: 成功 {summary.ok}，失败 {summary.failed}，块 {summary.blocks}"
        )

    def save(self) -> None:
        self.project.save()
        self.statusBar().showMessage("已保存 project.json")

    def _jump_to_block(self, page_index: int, block_id: int) -> None:
        self.load_page(page_index)
        self.select_block(block_id)
        self.show_module("editor")

    # -- selection --------------------------------------------------------
    def select_block(self, block_id: int) -> None:
        if self.editor is None:
            return
        block = next((b for b in self.editor.page.blocks if b.id == block_id), None)
        if block is None:
            return
        self.selected_id = block_id
        self.selected_ids = [block_id]
        self.sheets["editor"].show_block(block)
        self.canvas.set_blocks(self.editor.page.blocks, [block_id])

    def on_selection_ids(self, ids: list[int]) -> None:
        """Highlight blocks picked with the rubber band."""
        if self.editor is None:
            return
        self.selected_ids = list(ids)
        self.selected_id = ids[0] if ids else None
        blocks = self.editor.page.blocks
        if len(ids) == 1:
            block = next((b for b in blocks if b.id == ids[0]), None)
            self.sheets["editor"].show_block(block)
        elif ids:
            self.sheets["editor"].show_block(None)
            self.sheets["editor"].info.setText(f"已选 {len(ids)} 个文本块")
        self.canvas.set_blocks(blocks, ids)
        if ids:
            self.statusBar().showMessage(f"已选 {len(ids)} 块（右键打开菜单）")

    def _region_points(self) -> list[tuple[float, float]]:
        """Selection polygon, else the union box of the selected blocks."""
        points = self.canvas.selection_points
        if points:
            return points
        page_blocks = self.editor.page.blocks if self.editor else []
        blocks = [b for b in page_blocks if b.id in self.selected_ids]
        if not blocks:
            return list(self.region or [])
        x1 = min(b.bbox[0] for b in blocks)
        y1 = min(b.bbox[1] for b in blocks)
        x2 = max(b.bbox[2] for b in blocks)
        y2 = max(b.bbox[3] for b in blocks)
        return [(x1, y1), (x2, y1), (x2, y2), (x1, y2)]

    def on_canvas_menu(self, global_pos) -> None:
        """Show the selection menu at the cursor."""
        menu = self.build_canvas_menu()
        if menu is not None:
            menu.exec(global_pos)

    def build_canvas_menu(self) -> RoundMenu | None:
        """Fluent menu for the current selection (separate for testability)."""
        if self.editor is None:
            return None
        menu = RoundMenu(parent=self)
        for text, icon, slot in (
            (f"删除所选（{len(self.selected_ids)}）", FIF.DELETE, self.delete_selected),
            ("重新识别所选", FIF.SYNC, self.reocr_block),
            ("翻译所选", FIF.GLOBE, self.translate_block),
            ("重新检测选区", FIF.SEARCH, self.redetect_region),
            ("重绘选区（原地填充）", FIF.BRUSH, self.erase_region),
            ("恢复选区至原图", FIF.RETURN, self.restore_selected_region),
        ):
            menu.addAction(Action(text, menu, icon=icon, triggered=slot))
        return menu

    def delete_selected(self) -> None:
        if self.editor is None or not self.selected_ids:
            return
        targets = [b for b in self.editor.page.blocks if b.id in self.selected_ids]
        if not targets:
            return
        self._snapshot()
        self.editor.remove_blocks(targets)
        self.selected_ids = []
        self.selected_id = None
        self.canvas.set_blocks(self.editor.page.blocks)
        self.sheets["editor"].show_block(None)
        self._touch_page()
        self.statusBar().showMessage(f"已删除 {len(targets)} 个块")
        self._schedule_render()

    def restore_selected_region(self) -> None:
        if self.editor is None:
            return
        points = self._region_points()
        if len(points) < 3:
            InfoBar.info("需要选区", "先框选一块区域，或选中若干文本块", parent=self)
            return
        self._snapshot()
        self.editor.restore_region(points)
        self.show_view("erased", quiet=True)
        self._touch_page()
        self._schedule_render()
        self._finish_selection_action()
        self.statusBar().showMessage("已把选区内恢复为原图")

    def _selected(self):
        if self.editor is None or self.selected_id is None:
            return None
        return next(
            (b for b in self.editor.page.blocks if b.id == self.selected_id), None
        )

    # -- block actions ----------------------------------------------------
    def _snapshot(self, images: tuple[str, ...] = ()) -> None:
        """Remember state before an edit; ``images`` also snapshots page files."""
        if self.editor is None:
            return
        entry = {
            "blocks": [dict(b.to_dict()) for b in self.editor.page.blocks],
            "page": self.editor.page.name,
        }
        for key in images:
            path = (
                self.editor.erased_path if key == "inpainted" else self.editor.result_path
            )
            if path.is_file():
                entry[key] = path.read_bytes()
        self._undo.append(entry)
        if len(self._undo) > 20:
            self._undo.pop(0)

    def undo(self) -> None:
        if self.editor is None or not self._undo:
            return
        from mangatl.domain.block import TextBlock

        snapshot = self._undo.pop()
        if snapshot.get("page") not in (None, self.editor.page.name):
            self.statusBar().showMessage("撤销栈属于另一页，已忽略")
            return
        self.editor.page.blocks = [
            TextBlock.from_dict(item) for item in snapshot.get("blocks", [])
        ]
        restored = []
        for key, path in (
            ("inpainted", self.editor.erased_path),
            ("result", self.editor.result_path),
        ):
            if key not in snapshot:
                # The file did not exist before the edit: undo removes it again.
                if path.is_file():
                    path.unlink()
                    restored.append(key)
                continue
            path.parent.mkdir(parents=True, exist_ok=True)
            temp = path.with_name(path.stem + ".undo" + path.suffix)
            temp.write_bytes(snapshot[key])
            temp.replace(path)
            restored.append(key)
        self.editor.project.save()
        self.sheets["editor"].show_block(None)
        self.show_view(self.view_mode, quiet=True)
        self._touch_page()
        self.statusBar().showMessage(
            "已撤销" + ("（含画面）" if restored else "")
        )
        self._schedule_render()

    def on_geometry_changed(self, block_id: int, bbox: tuple) -> None:
        """Persist a block moved or resized on the canvas."""
        if self.editor is None:
            return
        block = next((b for b in self.editor.page.blocks if b.id == block_id), None)
        if block is None:
            return
        self._snapshot()
        self.editor.lock_style(block)
        if self.view_mode == "result":
            self.editor.set_text_bbox(block, bbox)
        else:
            self.editor.set_bbox(block, bbox)
        self.canvas.set_blocks(self.editor.page.blocks, [block_id])
        self._touch_page()
        self._schedule_render()
        self.statusBar().showMessage(f"#{block_id} 已调整框 {block.bbox}")

    def on_block_rotated(self, block_id: int, degrees: float) -> None:
        """Persist a free-transform rotation from the canvas."""
        if self.editor is None:
            return
        block = next((b for b in self.editor.page.blocks if b.id == block_id), None)
        if block is None:
            return
        self._snapshot()
        self.editor.lock_style(block)
        block.rotation = round(float(degrees), 2)
        self.editor.project.save()
        self.canvas.set_blocks(self.editor.page.blocks, [block_id])
        self._touch_page()
        self._schedule_render()
        self.statusBar().showMessage(f"#{block_id} 旋转 {block.rotation:.0f}°")

    def on_block_edited(
        self, block_id: int, text: str, translation: str, role: str
    ) -> None:
        if self.editor is None:
            return
        block = next((b for b in self.editor.page.blocks if b.id == block_id), None)
        if block is None:
            return
        self._snapshot()
        block.text = text.strip()
        block.translation = translation.strip()
        if role:
            block.role = role
        block.ocr_source = "manual"
        block.needs_review = False
        self.editor.project.save()
        self._touch_page()
        self._schedule_render()
        self.canvas.set_blocks(self.editor.page.blocks, [block_id])
        self.statusBar().showMessage(f"已更新 #{block_id}")

    def on_block_applied(
        self,
        block_id: int,
        text: str,
        translation: str,
        role: str,
        style: dict,
    ) -> None:
        """Single "apply" action: text, role, style, then a fresh render."""
        if self.editor is None:
            return
        block = next((b for b in self.editor.page.blocks if b.id == block_id), None)
        if block is None:
            return
        self._snapshot()
        block.text = text.strip()
        block.translation = translation.strip()
        if role:
            block.role = role
        block.style = {
            key: value for key, value in style.items() if value not in ("", 0, 0.0)
        }
        block.ocr_source = "manual"
        block.needs_review = False
        self.editor.project.save()
        self._touch_page()
        self.canvas.set_blocks(self.editor.page.blocks, [block_id])
        self.rerender()
        self.statusBar().showMessage(f"#{block_id} 已应用并重排")

    def on_block_action(self, action: str) -> None:
        if action == "reocr":
            self.reocr_block()
        elif action == "translate":
            self.translate_block()
        elif action == "render":
            self.rerender()
        elif action == "delete":
            self.delete_block()

    def reocr_block(self) -> None:
        block = self._selected()
        if block is None or self.editor is None:
            return
        self._snapshot()
        from mangatl.adapters.ocr.manga_ocr import MangaOcrAdapter

        adapter = MangaOcrAdapter()
        probe = adapter.recognize(self.editor.image_path, [block])[0]
        self.sheets["editor"].text_edit.setPlainText(probe.text)
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
        self.sheets["editor"].show_block(block)
        self.editor.project.save()
        self._touch_page()

    def delete_block(self) -> None:
        block = self._selected()
        if block is None or self.editor is None:
            return
        self._snapshot()
        self.editor.remove_blocks([block])
        self.selected_id = None
        self.canvas.set_blocks(self.editor.page.blocks)
        self.sheets["editor"].show_block(None)
        self._touch_page()
        self.statusBar().showMessage("已删除")

    def rerender(self) -> None:
        if self.editor is None:
            return
        path = self.editor.rerender()
        self.view_mode = "result"
        self.canvas.show_image(path, keep_selection=True, preserve_view=True)
        self.canvas.set_blocks(self.editor.page.blocks)
        self._touch_page()
        self.statusBar().showMessage(f"已排版 -> {path}")

    # -- region actions ---------------------------------------------------
    def on_lasso(self, points: list) -> None:
        self.region = points
        self.show_module("editor")
        self.statusBar().showMessage(
            f"已选择区域（{len(points)} 点）：点选区上方的按钮，或右侧操作"
        )

    def on_rect(self, box: tuple) -> None:
        x1, y1, x2, y2 = box
        self.region = [(x1, y1), (x2, y1), (x2, y2), (x1, y2)]
        self.show_module("editor")
        self.statusBar().showMessage("已选择矩形区域：点选区上方的按钮，或右侧操作")

    def on_sheet_region(self, action: str) -> None:
        if action == "detect":
            self.redetect_region()
        elif action == "erase":
            self.erase_region()
        elif action == "add":
            self.add_region_block()

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
        self._touch_page()
        self._finish_selection_action()
        self.statusBar().showMessage(f"区域检测：新增 {len(added)} 块")

    def erase_region(self) -> None:
        if self.editor is None or not self._require_region():
            return
        self._snapshot(images=("inpainted", "result"))
        path = self.editor.erase_region(self.region or [])
        self.show_view("erased", quiet=True)
        self._touch_page()
        self._schedule_render()
        self._finish_selection_action()
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
        self.sheets["editor"].text_edit.setFocus()
        self.statusBar().showMessage("已添加文本块，输入内容后点“应用文本”")

    # -- run / theme ------------------------------------------------------
    def on_run_requested(self, stages, all_pages: bool) -> None:
        from mangatl.core.config import RunConfig
        from mangatl.gui.pipeline_bridge import build_default_service

        if not stages:
            InfoBar.warning("未选择阶段", "至少勾选一个阶段", parent=self)
            return
        try:
            service = build_default_service(self.project, **self._engines())
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
        self.view_mode = "result"
        self.refresh_pages()
        self.load_page(self.page_index, keep_selection=True)

    def on_accent(self, colour: str) -> None:
        set_accent(colour)
        self.statusBar().showMessage(f"强调色已切换为 {colour}")

    # -- misc -------------------------------------------------------------
    def _toggle_auto_preview(self, checked: bool) -> None:
        self.auto_preview = bool(checked)
        if not self.auto_preview:
            self._preview_timer.stop()
        self.statusBar().showMessage(
            "自动预览已开启" if self.auto_preview else "自动预览已关闭"
        )

    def _schedule_render(self) -> None:
        """Render the current page shortly after an edit settles."""
        if self.auto_preview and self.editor is not None:
            self._preview_timer.start()

    def _auto_rerender(self) -> None:
        """Redraw the page and refresh the result view when it is on screen."""
        if self.editor is None:
            return
        try:
            path = self.editor.rerender()
        except Exception as exc:  # noqa: BLE001 - a broken block must not kill the UI
            self.statusBar().showMessage(f"自动排版失败：{exc}")
            return
        if self.view_mode == "result":
            self.canvas.set_overlay_mode("text")
            self.canvas.show_image(path, keep_selection=True, preserve_view=True)
            self.canvas.set_blocks(self.editor.page.blocks, self.selected_ids)
        self.statusBar().showMessage("已自动重排当前页")

    def show_view(self, mode: str, quiet: bool = False) -> None:
        """Display the original, the erased page or the typeset result."""
        if self.editor is None:
            return
        missing = {
            "erased": (self.editor.erased_path, "还没有擦除图", "先运行本页或做一次区域擦除"),
            "result": (self.editor.result_path, "还没有结果图", "点「运行本页」生成结果"),
        }.get(mode)
        if missing is not None and not missing[0].is_file():
            if not quiet:
                InfoBar.info(missing[1], missing[2], parent=self)
            mode = "source"
        self.view_mode = mode
        if mode == "result" and not quiet and self._result_is_stale():
            if self.auto_preview:
                self._auto_rerender()
            InfoBar.warning(
                "结果图可能过期",
                "project.json 比结果图新，点「运行本页」重新生成",
                parent=self,
            )
        path = self.editor.view_path(mode)
        if path is not None:
            self.canvas.set_overlay_mode(
                {"source": "blocks", "erased": "diff", "result": "text"}[mode]
            )
            self.canvas.show_image(
                path, keep_selection=mode == "erased", preserve_view=True
            )
            if mode == "erased" and self.editor.erased_path.is_file():
                self.canvas.show_erased_diff(
                    self.editor.image_path, self.editor.erased_path
                )
            if mode == "erased":
                # Erased view is region-only: no block boxes, no block highlight.
                self._clear_region()
                self.canvas.set_blocks(self.editor.page.blocks)
            else:
                self.canvas.set_blocks(self.editor.page.blocks, self.selected_ids)
        self.btn_view_source.setChecked(mode == "source")
        self.btn_view_erased.setChecked(mode == "erased")
        self.btn_view_result.setChecked(mode == "result")
        labels = {
            "source": "原图 · 编辑检测框",
            "erased": "擦除后 · 红色为已擦除区域",
            "result": "排版结果 · 拖动虚线框调整文字",
        }
        self.statusBar().showMessage(labels.get(mode, mode))

    def _result_is_stale(self) -> bool:
        """True when the project changed after the result image was written."""
        if self.editor is None or not self.editor.result_path.is_file():
            return False
        project_file = self.project.directory / "project.json"
        if not project_file.is_file():
            return False
        # A fresh render touches result then saves project, so allow a small gap.
        return (
            project_file.stat().st_mtime
            > self.editor.result_path.stat().st_mtime + 2.0
        )

    def open_folder_dialog(self) -> None:
        """Switch to another manga folder."""
        from PySide6.QtWidgets import QFileDialog

        chosen = QFileDialog.getExistingDirectory(
            self, "选择漫画文件夹", str(self.project.directory)
        )
        if not chosen:
            return
        self.load_project(Path(chosen))

    def load_project(self, folder: Path) -> None:
        """Switch this window to another manga folder."""
        from mangatl.gui import recent

        self.project = Project.open(folder)
        if not len(self.project):
            self.project.scan()
        recent.remember(folder)
        self.page_index = 0
        self.selected_id = None
        self.selected_ids = []
        self.region = None
        self.canvas.clear_selection()
        self.sheets["search"].project = self.project
        self.setWindowTitle(f"mangatl — {folder.name}")
        self.refresh_pages()
        if len(self.project):
            self.load_page(0)
        else:
            self.statusBar().showMessage("这个文件夹里没有图片")

    def toggle_fullscreen(self) -> None:
        """Switch between maximised and true full screen."""
        if self.isFullScreen():
            self.showMaximized()
        else:
            self.showFullScreen()
        QTimer.singleShot(50, self.canvas.fit)

    def keyPressEvent(self, event) -> None:  # noqa: N802 - Qt name
        if event.key() == Qt.Key.Key_F11:
            self.toggle_fullscreen()
            return
        super().keyPressEvent(event)

    def _set_mode(self, mode: str) -> None:
        self.canvas.set_mode(mode)
        self.btn_select.setChecked(mode == "select")
        self.btn_lasso.setChecked(mode == "lasso")
        self.btn_rect.setChecked(mode == "rect")
        self.statusBar().showMessage(f"工具：{mode}")
