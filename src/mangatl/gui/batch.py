"""Batch runner: spawn ``python -m mangatl run`` and watch its event stream.

Model work holds the GIL, so a worker *thread* freezes the editor. The pipeline runs
in a child process instead and streams one JSON event per line; this panel turns the
stream into a table, a progress bar, a log and a heartbeat.

The watchdog separates "slow" from "stuck": no event for ``threshold`` seconds shows
a bar with 终止进程 / 继续等待.
"""

from __future__ import annotations

import json
import os
import sys
import time
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from PySide6.QtCore import QProcess, Qt, QTimer, Signal
from PySide6.QtWidgets import (
    QFileDialog,
    QHBoxLayout,
    QProgressBar,
    QSpinBox,
    QTableWidgetItem,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)
from qfluentwidgets import (
    BodyLabel,
    CaptionLabel,
    CheckBox,
    PrimaryPushButton,
    PushButton,
    TableWidget,
)
from qfluentwidgets import (
    FluentIcon as FIF,
)

from mangatl.core.config import STAGE_ORDER
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

STATE_OK = "ok"
STATE_SLOW = "slow"
STATE_STUCK = "stuck"


def plan_pages(
    pages: list[Page],
    stages: tuple[str, ...],
    start: int,
    end: int,
    resume: bool,
    force: bool,
) -> tuple[list[str], list[str]]:
    """Split the range into (to_run, to_skip). ``force`` reruns everything."""
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


def parse_event(line: str) -> dict[str, Any] | None:
    """Parse one NDJSON line; ignore anything else (warnings, tracebacks)."""
    text = line.strip()
    if not text.startswith("{"):
        return None
    try:
        payload = json.loads(text)
    except json.JSONDecodeError:
        return None
    return payload if isinstance(payload, dict) and "kind" in payload else None


def watchdog_state(idle_seconds: float, threshold: float) -> str:
    """Classify silence: ok / slow (approaching) / stuck (over the threshold)."""
    if threshold <= 0:
        return STATE_OK
    if idle_seconds >= threshold:
        return STATE_STUCK
    if idle_seconds >= threshold / 3:
        return STATE_SLOW
    return STATE_OK


@dataclass
class Row:
    name: str
    status: str = STATUS_IDLE


class BatchSheet(QWidget):
    """Run panel: single page, or a range with subprocess monitoring."""

    runCurrentRequested = Signal()

    def __init__(
        self,
        project: Project,
        engines_provider: Callable[[], dict[str, str]] | None = None,
    ) -> None:
        super().__init__()
        self.project = project
        self.engines_provider = engines_provider or (lambda: {})
        self.process: QProcess | None = None
        self.failed: list[str] = []
        self.finished: Callable[[], None] | None = None
        self.rows: dict[str, Row] = {}
        self.started_at = 0.0
        self.last_event_at = 0.0
        self.current_page = ""
        self.current_stage = ""
        self.planned = 0
        self.started_pages = 0
        self.ok = 0
        self._stdout_buffer = b""

        layout = QVBoxLayout(self)
        layout.setContentsMargins(12, 10, 12, 10)
        layout.setSpacing(8)

        row_main = QHBoxLayout()
        row_main.setSpacing(8)
        self.btn_current = PrimaryPushButton(FIF.PLAY, "运行当前页")
        self.btn_current.setMinimumHeight(32)
        self.btn_current.clicked.connect(self.runCurrentRequested.emit)
        row_main.addWidget(self.btn_current, 1)
        self.btn_start = PrimaryPushButton(FIF.SYNC, "开始批量")
        self.btn_start.setMinimumHeight(32)
        self.btn_start.clicked.connect(self.start)
        row_main.addWidget(self.btn_start, 1)
        layout.addLayout(row_main)

        row_secondary = QHBoxLayout()
        row_secondary.setSpacing(8)
        self.btn_stop = PushButton(FIF.CLOSE, "停止")
        self.btn_stop.setEnabled(False)
        self.btn_stop.clicked.connect(self.stop)
        row_secondary.addWidget(self.btn_stop, 1)
        self.btn_retry = PushButton(FIF.RETURN, "重试失败")
        self.btn_retry.setEnabled(False)
        self.btn_retry.clicked.connect(self.retry_failed)
        row_secondary.addWidget(self.btn_retry, 1)
        self.btn_export = PushButton(FIF.SAVE, "导出日志")
        self.btn_export.clicked.connect(self.export_log)
        row_secondary.addWidget(self.btn_export, 1)
        layout.addLayout(row_secondary)

        self.progress = QProgressBar()
        self.progress.setRange(0, 100)
        self.progress.setFixedHeight(8)
        self.progress.setTextVisible(False)
        self.progress.setStyleSheet(
            "QProgressBar { background: #262626; border: 1px solid #3a3a3a;"
            " border-radius: 4px; }"
            "QProgressBar::chunk { background: #4f9cf9; border-radius: 4px; }"
        )
        layout.addWidget(self.progress)

        self.heartbeat = CaptionLabel("等待开始")
        self.heartbeat.setStyleSheet("color: #9aa0a8;")
        layout.addWidget(self.heartbeat)

        row_range = QHBoxLayout()
        row_range.setSpacing(8)
        row_range.addWidget(BodyLabel("页码范围"))
        self.start_box = QSpinBox()
        self.end_box = QSpinBox()
        for box in (self.start_box, self.end_box):
            box.setRange(1, 9999)
            box.setMinimumWidth(72)
            box.setAlignment(Qt.AlignmentFlag.AlignCenter)
            box.valueChanged.connect(self._range_edited)
        row_range.addWidget(self.start_box)
        row_range.addWidget(CaptionLabel("到"))
        row_range.addWidget(self.end_box)
        row_range.addStretch(1)
        self.all_box = CheckBox("全部")
        self.all_box.setChecked(True)
        self.all_box.stateChanged.connect(self._toggle_all)
        row_range.addWidget(self.all_box)
        layout.addLayout(row_range)

        row_stages = QHBoxLayout()
        row_stages.setSpacing(8)
        row_stages.addWidget(BodyLabel("阶段"))
        self.stage_boxes: dict[str, CheckBox] = {}
        for key in STAGE_ORDER:
            box = CheckBox(STAGE_LABELS.get(key, key))
            box.setChecked(True)
            self.stage_boxes[key] = box
            row_stages.addWidget(box)
        row_stages.addStretch(1)
        layout.addLayout(row_stages)

        row_options = QHBoxLayout()
        row_options.setSpacing(12)
        self.resume_box = CheckBox("跳过已完成")
        self.resume_box.setChecked(True)
        row_options.addWidget(self.resume_box)
        self.force_box = CheckBox("强制重跑")
        row_options.addWidget(self.force_box)
        row_options.addWidget(CaptionLabel("卡住阈值"))
        self.threshold_box = QSpinBox()
        self.threshold_box.setRange(10, 900)
        self.threshold_box.setValue(60)
        self.threshold_box.setSuffix(" 秒")
        row_options.addWidget(self.threshold_box)
        row_options.addStretch(1)
        layout.addLayout(row_options)

        self.warning_bar = QWidget()
        warn_layout = QHBoxLayout(self.warning_bar)
        warn_layout.setContentsMargins(0, 0, 0, 0)
        self.warning_label = CaptionLabel("")
        warn_layout.addWidget(self.warning_label, 1)
        self.btn_terminate = PushButton("终止进程")
        self.btn_terminate.clicked.connect(self.terminate)
        warn_layout.addWidget(self.btn_terminate)
        self.btn_continue = PushButton("继续等待")
        self.btn_continue.clicked.connect(self.continue_waiting)
        warn_layout.addWidget(self.btn_continue)
        self.warning_bar.setVisible(False)
        layout.addWidget(self.warning_bar)

        self.table = TableWidget()
        self.table.setColumnCount(4)
        self.table.setHorizontalHeaderLabels(["页", "状态", "块", "耗时"])
        self.table.horizontalHeader().setStretchLastSection(True)
        self.table.setMinimumHeight(160)
        layout.addWidget(self.table, 1)

        self.log = QTextEdit()
        self.log.setReadOnly(True)
        self.log.setFixedHeight(96)
        self.log.setPlaceholderText("运行日志（子进程 stderr + 事件）")
        self.log.setStyleSheet(
            "QTextEdit {"
            " background: #1b1b1b;"
            " color: #dcdcdc;"
            " border: 1px solid #3a3a3a;"
            " border-radius: 6px;"
            " padding: 4px;"
            "}"
        )
        layout.addWidget(CaptionLabel("运行日志"))
        layout.addWidget(self.log)

        self._watchdog = QTimer(self)
        self._watchdog.setInterval(1000)
        self._watchdog.timeout.connect(self._tick)
        self.set_project(project)

    # -- project ----------------------------------------------------------
    def set_project(self, project: Project) -> None:
        if self.is_running():
            return
        self.project = project
        pages = list(project)
        maximum = max(1, len(pages))
        for box in (self.start_box, self.end_box):
            box.setRange(1, maximum)
        self._set_range(1, maximum)
        self.all_box.blockSignals(True)
        self.all_box.setChecked(True)
        self.all_box.blockSignals(False)
        self.failed = []
        self.btn_retry.setEnabled(False)
        self._fill([page.name for page in pages])
        self.heartbeat.setText("等待开始")

    def _fill(self, names: list[str]) -> None:
        self.rows = {name: Row(name) for name in names}
        self.table.setRowCount(len(names))
        for row, name in enumerate(names):
            self.table.setItem(row, 0, QTableWidgetItem(name))
            self.table.setItem(row, 1, QTableWidgetItem(STATUS_IDLE))
            self.table.setItem(row, 2, QTableWidgetItem("-"))
            self.table.setItem(row, 3, QTableWidgetItem("-"))

    # -- helpers ----------------------------------------------------------
    def is_running(self) -> bool:
        return (
            self.process is not None
            and self.process.state() != QProcess.ProcessState.NotRunning
        )

    def _set_row(
        self, name: str, status: str, blocks: int = 0, seconds: float = 0.0
    ) -> None:
        self.rows[name] = Row(name, status)
        for row in range(self.table.rowCount()):
            item = self.table.item(row, 0)
            if item is not None and item.text() == name:
                self.table.setItem(row, 1, QTableWidgetItem(status))
                if blocks:
                    self.table.setItem(row, 2, QTableWidgetItem(str(blocks)))
                if seconds:
                    self.table.setItem(row, 3, QTableWidgetItem(f"{seconds:.1f}s"))
                return

    def append(self, text: str) -> None:
        """Public log hook used by the window."""
        self._append_log(text)

    def run_single(self, page_number: int) -> None:
        """Run one page (1-based) through the same child process."""
        if self.is_running():
            self._append_log("已有任务在运行，先停止再试")
            return
        self._append_log(f"运行第 {page_number} 页")
        self._launch(str(page_number), self._selected_stages(), force=False, planned=1)

    def _append_log(self, text: str) -> None:
        self.log.append(f"[{time.strftime('%H:%M:%S')}] {text}")
        if self.log.document().blockCount() > 500:
            cursor = self.log.textCursor()
            cursor.movePosition(cursor.MoveOperation.Start)
            cursor.select(cursor.SelectionType.BlockUnderCursor)
            cursor.removeSelectedText()
            cursor.deleteChar()

    def _set_range(self, start: int, end: int) -> None:
        """Update both boxes without treating it as manual range editing."""
        for box, value in ((self.start_box, start), (self.end_box, end)):
            box.blockSignals(True)
            box.setValue(value)
            box.blockSignals(False)

    def _toggle_all(self, state: int) -> None:
        """Keep the number boxes usable; ticking 全部 only changes what start() does."""
        if self.all_box.isChecked():
            pages = list(self.project)
            if pages:
                self._set_range(1, len(pages))

    def _range_edited(self, _value: int) -> None:
        """Typing a range unticks 全部 so the numbers always mean something."""
        if self.all_box.isChecked():
            self.all_box.setChecked(False)

    def _selected_stages(self) -> tuple[str, ...]:
        return tuple(key for key, box in self.stage_boxes.items() if box.isChecked())

    def _force(self) -> bool:
        return self.force_box.isChecked() or not self.resume_box.isChecked()

    # -- run control ------------------------------------------------------
    def start(self) -> None:
        if self.is_running():
            return
        stages = self._selected_stages()
        if not stages:
            self._append_log("至少选择一个阶段")
            return
        pages = list(self.project)
        start = 1 if self.all_box.isChecked() else self.start_box.value()
        end = len(pages) if self.all_box.isChecked() else self.end_box.value()
        if not pages:
            self._append_log("项目里没有页面")
            return
        page_spec = f"1-{len(pages)}" if self.all_box.isChecked() else f"{start}-{end}"
        self._fill([page.name for page in pages])
        self._launch(page_spec, stages, force=self._force(), planned=end - start + 1)

    def _launch(
        self, page_spec: str, stages: tuple[str, ...], force: bool, planned: int
    ) -> None:
        engines = self.engines_provider()
        if engines.get("translator") == "openai" and not os.environ.get(
            "MANGATL_API_KEY"
        ):
            self._append_log(
                "错误：翻译引擎是 openai，但 MANGATL_API_KEY 未设置。"
                "到「设置」里填写 Key，或把底部翻译引擎改成 echo。"
            )
            self.heartbeat.setText("未启动：缺少 MANGATL_API_KEY")
            return
        command = [
            sys.executable,
            "-m",
            "mangatl",
            "run",
            str(self.project.directory),
            "--stages",
            ",".join(stages),
            "--pages",
            page_spec,
            "--events-json",
            "--heartbeat",
            "1",
        ]
        for key in ("detector", "ocr", "inpainter", "translator"):
            value = engines.get(key)
            if value:
                command.extend([f"--{key}", value])
        if force:
            command.append("--force")

        self.planned = max(1, planned)
        self.started_pages = 0
        self.ok = 0
        self.failed = []
        self.started_at = time.monotonic()
        self.last_event_at = self.started_at
        self.current_page = ""
        self.current_stage = ""
        self._stdout_buffer = b""
        self.progress.setValue(0)
        self.warning_bar.setVisible(False)
        self.btn_start.setEnabled(False)
        self.btn_stop.setEnabled(True)
        self.btn_retry.setEnabled(False)

        process = QProcess(self)
        process.setProcessChannelMode(QProcess.ProcessChannelMode.SeparateChannels)
        process.readyReadStandardOutput.connect(self._read_stdout)
        process.readyReadStandardError.connect(self._read_stderr)
        process.finished.connect(self._on_finished)
        process.errorOccurred.connect(self._on_error)
        self.process = process
        self._append_log("启动子进程：" + " ".join(command[3:]))
        process.start(command[0], command[1:])
        self._watchdog.start()

    def stop(self) -> None:
        if not self.is_running():
            return
        self._append_log("请求停止 …")
        self.btn_stop.setEnabled(False)
        assert self.process is not None
        self.process.terminate()
        QTimer.singleShot(15000, self._kill_if_running)

    def terminate(self) -> None:
        if self.process is not None and self.is_running():
            self._append_log("强制终止子进程")
            self.process.kill()
        self.warning_bar.setVisible(False)

    def continue_waiting(self) -> None:
        self.warning_bar.setVisible(False)
        self.last_event_at = time.monotonic()
        self._append_log("用户选择继续等待")

    def _kill_if_running(self) -> None:
        if self.is_running():
            self._append_log("停止超时，强制终止")
            assert self.process is not None
            self.process.kill()

    def retry_failed(self) -> None:
        if not self.failed or self.is_running():
            return
        names = [page.name for page in self.project]
        retry = [name for name in self.failed if name in set(names)]
        if not retry:
            self.btn_retry.setEnabled(False)
            return
        spec = ",".join(str(names.index(name) + 1) for name in retry)
        self._append_log(f"重试失败页：{', '.join(retry)}")
        self._launch(spec, self._selected_stages(), force=True, planned=len(retry))

    def export_log(self) -> None:
        target, _ = QFileDialog.getSaveFileName(
            self, "导出日志", "batch.log", "Log (*.log *.txt)"
        )
        if target:
            Path(target).write_text(self.log.toPlainText(), encoding="utf-8")
            self._append_log(f"日志已导出到 {target}")

    # -- process signals --------------------------------------------------
    def _read_stdout(self) -> None:
        assert self.process is not None
        self._stdout_buffer += bytes(self.process.readAllStandardOutput())
        *lines, self._stdout_buffer = self._stdout_buffer.split(b"\n")
        for raw in lines:
            event = parse_event(raw.decode("utf-8", "replace"))
            if event is not None:
                self._handle_event(event)

    def _read_stderr(self) -> None:
        assert self.process is not None
        text = bytes(self.process.readAllStandardError()).decode("utf-8", "replace")
        for line in text.splitlines():
            if line.strip():
                self._append_log(line.strip())

    def _handle_event(self, event: dict[str, Any]) -> None:
        kind = str(event.get("kind", ""))
        page = str(event.get("page", ""))
        detail = str(event.get("detail", ""))
        self.last_event_at = time.monotonic()
        if kind == "tick":
            self.current_stage = detail or self.current_stage
            return
        if page:
            self.current_page = page
        if kind == "page-start":
            self.current_stage = ""
            self.started_pages = min(self.planned, self.started_pages + 1)
            self.progress.setValue(
                int(self.started_pages * 100 / max(1, self.planned))
            )
            self._set_row(page, STATUS_RUNNING)
            self.heartbeat.setText(f"第 {self.started_pages}/{self.planned} 页 · {page}")
        elif kind == "stage-start":
            self.current_stage = detail
            label = STAGE_LABELS.get(detail, detail)
            self.heartbeat.setText(f"{page} · 阶段 {label}")
        elif kind == "page-done":
            blocks = 0
            for token in detail.split():
                if token.isdigit():
                    blocks = int(token)
                    break
            self.ok += 1
            self._set_row(page, STATUS_DONE, blocks)
            self._append_log(f"{page} 完成（{detail or 'ok'}）")
        elif kind == "page-skipped":
            self.started_pages = min(self.planned, self.started_pages + 1)
            self.progress.setValue(
                int(self.started_pages * 100 / max(1, self.planned))
            )
            self._set_row(page, STATUS_SKIPPED)
        elif kind == "page-failed":
            self.failed.append(page)
            self._set_row(page, STATUS_FAILED)
            self._append_log(f"{page} 失败：{detail}")
        elif kind == "summary":
            self._append_log(
                f"汇总：成功 {event.get('ok', 0)}，失败 {event.get('failed', 0)}，"
                f"跳过 {event.get('skipped', 0)}"
            )

    def _on_error(self, error) -> None:
        self._append_log(f"子进程错误：{error}")

    def _on_finished(self, exit_code: int, status) -> None:
        self._watchdog.stop()
        self.process = None
        self.btn_start.setEnabled(True)
        self.btn_stop.setEnabled(False)
        self.btn_retry.setEnabled(bool(self.failed))
        self.warning_bar.setVisible(False)
        seconds = max(0.0, time.monotonic() - self.started_at)
        self.progress.setValue(100)
        self.heartbeat.setText(
            f"结束：成功 {self.ok} 页，失败 {len(self.failed)} 页，"
            f"用时 {seconds:.1f}s（退出码 {exit_code}）"
        )
        self._append_log(self.heartbeat.text())
        if callable(self.finished):
            self.finished()

    # -- watchdog ---------------------------------------------------------
    def _tick(self) -> None:
        if not self.is_running():
            return
        idle = time.monotonic() - self.last_event_at
        threshold = float(self.threshold_box.value())
        state = watchdog_state(idle, threshold)
        stage = STAGE_LABELS.get(self.current_stage, self.current_stage or "准备中")
        self.heartbeat.setText(
            f"心跳：{idle:.0f}s 前 · {self.current_page or '-'} · {stage} · "
            f"已用 {time.monotonic() - self.started_at:.0f}s"
        )
        if state == STATE_STUCK:
            self.warning_label.setText(
                f"{idle:.0f} 秒没有新进展，可能卡住（阈值 {threshold:.0f}s）"
            )
            self.warning_bar.setVisible(True)
        elif state == STATE_OK:
            self.warning_bar.setVisible(False)
