"""Small modal-ish progress window for background region repaint."""

from __future__ import annotations

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QDialog,
    QHBoxLayout,
    QProgressBar,
    QVBoxLayout,
)
from qfluentwidgets import BodyLabel, CaptionLabel, PushButton


class RegionProgressDialog(QDialog):
    """Indeterminate progress with a cancel button; closing it cancels too."""

    cancelled = Signal()

    def __init__(self, parent=None, title: str = "局部重绘") -> None:
        super().__init__(parent)
        self.setWindowTitle(title)
        self.setFixedWidth(360)
        self.setModal(False)
        self.setWindowFlag(Qt.WindowType.WindowCloseButtonHint, True)
        self._finished = False

        layout = QVBoxLayout(self)
        layout.setContentsMargins(18, 16, 18, 14)
        layout.setSpacing(8)
        self.title_label = BodyLabel(f"正在{title}…")
        layout.addWidget(self.title_label)
        self.detail = CaptionLabel("启动子进程")
        self.detail.setStyleSheet("color: #9aa0a8;")
        layout.addWidget(self.detail)

        self.progress = QProgressBar()
        self.progress.setRange(0, 0)
        self.progress.setFixedHeight(6)
        self.progress.setTextVisible(False)
        self.progress.setStyleSheet(
            "QProgressBar { background: #262626; border: 1px solid #3a3a3a;"
            " border-radius: 3px; }"
            "QProgressBar::chunk { background: #4f9cf9; border-radius: 3px; }"
        )
        layout.addWidget(self.progress)

        row = QHBoxLayout()
        self.elapsed = CaptionLabel("0.0s")
        self.elapsed.setStyleSheet("color: #9aa0a8;")
        row.addWidget(self.elapsed)
        row.addStretch(1)
        self.cancel_button = PushButton("取消")
        self.cancel_button.clicked.connect(self._cancel)
        row.addWidget(self.cancel_button)
        layout.addLayout(row)

    def set_elapsed(self, seconds: float) -> None:
        self.elapsed.setText(f"{seconds:.1f}s")

    def set_detail(self, text: str) -> None:
        self.detail.setText(text)

    def finish(self) -> None:
        self._finished = True
        self.close()

    def _cancel(self) -> None:
        if self._finished:
            return
        self._finished = True
        self.cancelled.emit()
        self.close()

    def closeEvent(self, event) -> None:  # noqa: N802 - Qt name
        if not self._finished:
            self._finished = True
            self.cancelled.emit()
        super().closeEvent(event)
