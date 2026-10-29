"""Batch runner: pick a page range, run stages, resume where the last run stopped.

The pipeline already records per-page stage flags, so "resume" is just a filter over
those flags. The worker runs one page at a time so it can report progress and stop
between pages instead of freezing the editor.
"""

from __future__ import annotations

import time
from collections.abc import Callable
from dataclasses import dataclass

from PySide6.QtCore import QThread, Signal
from PySide6.QtWidgets import (
    QHBoxLayout,
    QProgressBar,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)
from qfluentwidgets import (
    BodyLabel,
    CaptionLabel,
    CheckBox,
    PrimaryPushButton,
    PushButton,
    SpinBox,
    TableWidget,
)
from qfluentwidgets import (
    FluentIcon as FIF,
)

from mangatl.core.config import RunConfig
from mangatl.core.pipeline import PipelineService
from mangatl.domain.project import Page, Project

STAGE_LABELS = {
    "detect": "检测",
    "ocr": "OCR",
    "translate": "翻译",
    "erase": "擦除",
    "render": "排版",
}

STATUS_IDLE = "未开始"
STATUS_RUNNING = "进行中"
STATUS_DONE = "完成"
STATUS_SKIPPED = "已完成，跳过"
STATUS_FAILED = "失败"


@dataclass
class PageResult:
    name: str
    status: str
    blocks: int = 0
    seconds: float = 0.0
    message: str = ""


def plan_pages(
    pages: list[Page],
    stages: tuple[str, ...],
    start: int,
    end: int,
    resume: bool,
    force: bool,
) -> tuple[list[str], list[str]]:
    """Split the range into (to_run, to_skip).

    ``resume`` skips pages whose selected stages are all done; ``force`` reruns
    everything in range.
    """
    first = max(0, start - 1)
    last = min(len(pages), end)
    selected = pages[first:last]
    if force or not resume:
        return [page.name for page in selected], []
    run: list[str] = []
    skip: list[str] = []
    for page in selected:
        if all(page.stage.get(stage) for stage in stages):
            skip.append(page.name)
        else:
            run.append(page.name)
    return run, skip


class BatchWorker(QThread):
    """Runs the pipeline page by page so the UI can show progress and stop."""

    pageStarted = Signal(str, int, int)  # name, index, total
    pageFinished = Signal(str, str, int, float, str)  # name, status, blocks, seconds, msg
    batchFinished = Signal(int, int, int)  # ok, failed, seconds*100

    def __init__(
        self,
        service: PipelineService,
        pages: list[str],
        force: bool,
        parent=None,
    ) -> None:
        super().__init__(parent)
        self.service = service
        self.pages = pages
        self.force = force
        self._stop = False

    def stop(self) -> None:
        self._stop = True

    def run(self) -> None:  # noqa: D401 - Qt entry point
        started = time.time()
        ok = failed = 0
        for index, name in enumerate(self.pages, start=1):
            if self._stop:
                break
            self.pageStarted.emit(name, index, len(self.pages))
            began = time.time()
            try:
                summary = self.service.run(
                    RunConfig(force=self.force), only={name}
                )
            except Exception as exc:  # noqa: BLE001 - report and continue
                failed += 1
                self.pageFinished.emit(name, STATUS_FAILED, 0, time.time() - began, str(exc))
                continue
            if summary.failed:
                failed += 1
                self.pageFinished.emit(
                    name, STATUS_FAILED, 0, time.time() - began, "页面处理失败"
                )
            elif summary.skipped:
                self.pageFinished.emit(
                    name, STATUS_SKIPPED, 0, time.time() - began, "所有阶段已完成"
                )
            else:
                ok += 1
                self.pageFinished.emit(
                    name,
                    STATUS_DONE,
                    summary.blocks,
                    time.time() - began,
                    f"块 {summary.blocks}",
                )
        self.batchFinished.emit(ok, failed, int((time.time() - started) * 100))


class BatchSheet(QWidget):
    """Batch controls plus a live per-page table."""

    def __init__(
        self,
        project: Project,
        service_factory: Callable[[], PipelineService],
    ) -> None:
        super().__init__()
        self.project = project
        self.service_factory = service_factory
        self.worker: BatchWorker | None = None
        self.failed: list[str] = []

        layout = QVBoxLayout(self)
        layout.setContentsMargins(10, 8, 10, 8)
        layout.setSpacing(6)

        row_range = QHBoxLayout()
        row_range.addWidget(BodyLabel("页码范围"))
        self.start_box = SpinBox()
        self.end_box = SpinBox()
        for box in (self.start_box, self.end_box):
            box.setRange(1, 9999)
            row_range.addWidget(box)
        row_range.addWidget(CaptionLabel("到"))
        row_range.addStretch(1)
        self.all_box = CheckBox("全部")
        self.all_box.setChecked(True)
        self.all_box.stateChanged.connect(self._toggle_all)
        row_range.addWidget(self.all_box)
        layout.addLayout(row_range)

        row_stages = QHBoxLayout()
        row_stages.addWidget(BodyLabel("阶段"))
        self.stage_boxes: dict[str, CheckBox] = {}
        for key, label in STAGE_LABELS.items():
            box = CheckBox(label)
            box.setChecked(True)
            self.stage_boxes[key] = box
            row_stages.addWidget(box)
        row_stages.addStretch(1)
        layout.addLayout(row_stages)

        row_options = QHBoxLayout()
        self.resume_box = CheckBox("跳过已完成")
        self.resume_box.setChecked(True)
        row_options.addWidget(self.resume_box)
        self.force_box = CheckBox("强制重跑")
        row_options.addWidget(self.force_box)
        row_options.addStretch(1)
        layout.addLayout(row_options)

        row_buttons = QHBoxLayout()
        self.btn_start = PrimaryPushButton(FIF.PLAY, "开始")
        self.btn_start.clicked.connect(self.start)
        row_buttons.addWidget(self.btn_start)
        self.btn_stop = PushButton(FIF.CLOSE, "停止")
        self.btn_stop.setEnabled(False)
        self.btn_stop.clicked.connect(self.stop)
        row_buttons.addWidget(self.btn_stop)
        self.btn_retry = PushButton(FIF.SYNC, "重试失败页")
        self.btn_retry.setEnabled(False)
        self.btn_retry.clicked.connect(self.retry_failed)
        row_buttons.addWidget(self.btn_retry)
        row_buttons.addStretch(1)
        self.status = CaptionLabel("就绪")
        row_buttons.addWidget(self.status)
        layout.addLayout(row_buttons)

        self.progress = QProgressBar()
        self.progress.setRange(0, 100)
        self.progress.setValue(0)
        layout.addWidget(self.progress)

        self.table = TableWidget()
        self.table.setColumnCount(4)
        self.table.setHorizontalHeaderLabels(["页", "状态", "块", "耗时"])
        self.table.horizontalHeader().setStretchLastSection(True)
        layout.addWidget(self.table, 1)

        self.set_project(project)

    # -- state ------------------------------------------------------------
    def set_project(self, project: Project) -> None:
        self.project = project
        pages = list(project)
        self.start_box.setRange(1, max(1, len(pages)))
        self.end_box.setRange(1, max(1, len(pages)))
        self.start_box.setValue(1)
        self.end_box.setValue(max(1, len(pages)))
        self.failed = []
        self.btn_retry.setEnabled(False)
        self._fill_table([page.name for page in pages])

    def _fill_table(self, names: list[str]) -> None:
        self.table.setRowCount(len(names))
        for row, name in enumerate(names):
            self.table.setItem(row, 0, QTableWidgetItem(name))
            self.table.setItem(row, 1, QTableWidgetItem(STATUS_IDLE))
            self.table.setItem(row, 2, QTableWidgetItem("-"))
            self.table.setItem(row, 3, QTableWidgetItem("-"))
        self.status.setText("就绪")

    def _set_row(self, name: str, status: str, blocks: int = 0, seconds: float = 0.0) -> None:
        for row in range(self.table.rowCount()):
            item = self.table.item(row, 0)
            if item is not None and item.text() == name:
                self.table.setItem(row, 1, QTableWidgetItem(status))
                if blocks:
                    self.table.setItem(row, 2, QTableWidgetItem(str(blocks)))
                if seconds:
                    self.table.setItem(row, 3, QTableWidgetItem(f"{seconds:.1f}s"))
                return

    # -- controls ---------------------------------------------------------
    def _toggle_all(self, state: int) -> None:
        enabled = not self.all_box.isChecked()
        self.start_box.setEnabled(enabled)
        self.end_box.setEnabled(enabled)

    def _selected_stages(self) -> tuple[str, ...]:
        return tuple(key for key, box in self.stage_boxes.items() if box.isChecked())

    def start(self) -> None:
        stages = self._selected_stages()
        if not stages:
            self.status.setText("至少选一个阶段")
            return
        pages = list(self.project)
        start = 1 if self.all_box.isChecked() else self.start_box.value()
        end = len(pages) if self.all_box.isChecked() else self.end_box.value()
        run, skip = plan_pages(
            pages,
            stages,
            start,
            end,
            resume=self.resume_box.isChecked(),
            force=self.force_box.isChecked(),
        )
        self._fill_table([page.name for page in pages])
        for name in skip:
            self._set_row(name, STATUS_SKIPPED)
        if not run:
            self.status.setText("范围内没有需要处理的页")
            return

        self.failed = []
        self.btn_start.setEnabled(False)
        self.btn_stop.setEnabled(True)
        self.btn_retry.setEnabled(False)
        self.progress.setValue(0)
        self.status.setText(f"准备处理 {len(run)} 页")

        service = self.service_factory()
        self.worker = BatchWorker(service, run, force=self.force_box.isChecked(), parent=self)
        self.worker.pageStarted.connect(self._on_page_started)
        self.worker.pageFinished.connect(self._on_page_finished)
        self.worker.batchFinished.connect(self._on_batch_finished)
        self.worker.start()

    def stop(self) -> None:
        if self.worker is not None:
            self.worker.stop()
            self.status.setText("正在停止 …")

    def retry_failed(self) -> None:
        if not self.failed:
            return
        pages = list(self.project)
        existing = {page.name for page in pages}
        run = [name for name in self.failed if name in existing]
        if not run:
            self.btn_retry.setEnabled(False)
            return
        self.failed = []
        self.btn_start.setEnabled(False)
        self.btn_stop.setEnabled(True)
        self.progress.setValue(0)
        self.status.setText(f"重试 {len(run)} 页")
        service = self.service_factory()
        self.worker = BatchWorker(service, run, force=True, parent=self)
        self.worker.pageStarted.connect(self._on_page_started)
        self.worker.pageFinished.connect(self._on_page_finished)
        self.worker.batchFinished.connect(self._on_batch_finished)
        self.worker.start()

    # -- worker signals ---------------------------------------------------
    def _on_page_started(self, name: str, index: int, total: int) -> None:
        self.progress.setValue(int((index - 1) * 100 / max(1, total)))
        self._set_row(name, STATUS_RUNNING)
        self.status.setText(f"{index}/{total} · {name}")

    def _on_page_finished(
        self, name: str, status: str, blocks: int, seconds: float, message: str
    ) -> None:
        self._set_row(name, status, blocks, seconds)
        if status == STATUS_FAILED:
            self.failed.append(name)
        self.status.setText(message or status)

    def _on_batch_finished(self, ok: int, failed: int, seconds_centi: int) -> None:
        self.worker = None
        self.btn_start.setEnabled(True)
        self.btn_stop.setEnabled(False)
        self.btn_retry.setEnabled(bool(self.failed))
        self.progress.setValue(100)
        self.status.setText(
            f"完成 {ok} 页，失败 {failed} 页，用时 {seconds_centi / 100:.1f}s"
        )
        if callable(self.finished):
            self.finished()
