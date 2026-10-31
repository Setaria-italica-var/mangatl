"""Persistent child process for region repaint.

The worker keeps the LaMa mask session warm, so the second and later fills take about
two seconds instead of reloading 208 MB of weights. Communication is one JSON object per
line on stdin/stdout; a reader thread turns lines into Qt signals so the GUI never
blocks. Model logs go to ``data/tmp/region-worker.log`` to keep the protocol pipe clean.
"""

from __future__ import annotations

import contextlib
import json
import os
import subprocess
import sys
import threading
import time
from pathlib import Path

from PySide6.QtCore import QObject, QTimer, Signal

from mangatl import paths


class RegionWorkerClient(QObject):
    """Owns the child process; emits results on the GUI thread."""

    result = Signal(object)
    failed = Signal(str)

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self._process: subprocess.Popen | None = None
        self._thread: threading.Thread | None = None
        self._log = None
        self._closing = False
        self._busy = False
        self._last_activity = time.monotonic()
        self._idle_timeout = 0.0
        self._soft_cancel = False
        self._idle_timer = QTimer(self)
        self._idle_timer.setInterval(15000)
        self._idle_timer.timeout.connect(self._check_idle)
        self._idle_timer.start()

    # -- preferences ------------------------------------------------------
    def set_idle_timeout(self, seconds: float) -> None:
        """Stop the worker after this many idle seconds (0 = keep it warm)."""
        self._idle_timeout = max(0.0, float(seconds))

    def set_soft_cancel(self, enabled: bool) -> None:
        self._soft_cancel = bool(enabled)

    @property
    def soft_cancel(self) -> bool:
        return self._soft_cancel

    def cancel_token(self, request_id: str) -> Path:
        """File the worker checks before replacing the page (cooperative cancel)."""
        return paths.data_dir() / "tmp" / f"region-cancel-{request_id}"

    def clear_cancel_token(self, request_id: str) -> None:
        with contextlib.suppress(OSError):
            self.cancel_token(request_id).unlink(missing_ok=True)

    def _check_idle(self) -> None:
        if not self.is_running() or self._busy or self._idle_timeout <= 0:
            return
        if time.monotonic() - self._last_activity >= self._idle_timeout:
            self.cancel()

    def is_running(self) -> bool:
        return self._process is not None and self._process.poll() is None

    def _log_path(self) -> Path:
        log_dir = paths.data_dir() / "tmp"
        log_dir.mkdir(parents=True, exist_ok=True)
        return log_dir / "region-worker.log"

    def ensure_started(self) -> bool:
        if self.is_running():
            return True
        self._closing = False
        try:
            self._log = self._log_path().open("w", encoding="utf-8", errors="replace")
        except OSError:
            self._log = subprocess.DEVNULL
        env = dict(os.environ)
        env["PYTHONIOENCODING"] = "utf-8"
        env["PYTHONUTF8"] = "1"
        self._last_activity = time.monotonic()
        try:
            self._process = subprocess.Popen(
                [sys.executable, "-m", "mangatl", "task-worker"],
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=self._log,
                text=True,
                encoding="utf-8",
                errors="replace",
                bufsize=1,
                cwd=str(paths.app_root()),
                env=env,
            )
        except OSError as exc:
            self.failed.emit(f"无法启动重绘进程：{exc}")
            return False
        self._thread = threading.Thread(target=self._read_loop, daemon=True)
        self._thread.start()
        return True

    def submit(self, request: dict) -> bool:
        if not self.ensure_started():
            return False
        self._busy = True
        self._last_activity = time.monotonic()
        assert self._process is not None and self._process.stdin is not None
        try:
            self._process.stdin.write(json.dumps(request, ensure_ascii=True) + "\n")
            self._process.stdin.flush()
        except (OSError, ValueError) as exc:
            self.failed.emit(f"重绘进程写入失败：{exc}")
            self.cancel()
            return False
        return True

    def _read_loop(self) -> None:
        process = self._process
        if process is None or process.stdout is None:
            return
        for line in process.stdout:
            if self._closing:
                break
            line = line.strip()
            if not line.startswith("{"):
                continue
            try:
                payload = json.loads(line)
            except json.JSONDecodeError:
                continue
            if payload.get("ready"):
                continue
            if "id" in payload:
                self._busy = False
                self._last_activity = time.monotonic()
                self.result.emit(payload)
        self._busy = False
        if not self._closing:
            self.failed.emit("重绘进程已退出，请重试")

    def cancel(self) -> None:
        """Stop the worker (used by 取消 and by page changes)."""
        self._closing = True
        self._busy = False
        process = self._process
        self._process = None
        if process is not None:
            try:
                if process.poll() is None:
                    process.terminate()
                    try:
                        process.wait(timeout=2)
                    except subprocess.TimeoutExpired:
                        process.kill()
                        process.wait(timeout=2)
            except (OSError, subprocess.TimeoutExpired):
                pass
            for stream in (process.stdin, process.stdout):
                if stream is not None:
                    with contextlib.suppress(OSError):
                        stream.close()
        if self._log not in (None, subprocess.DEVNULL):
            with contextlib.suppress(OSError):
                self._log.close()
        self._log = None

    def shutdown(self) -> None:
        self.cancel()
