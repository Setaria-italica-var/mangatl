"""Floating erase toolbar: manual brush, size, engine and inline progress.

Visible only in the erased preview. Draggable, defaults to the top-right corner of the
canvas; its position is intentionally not persisted (a new process starts at the
default again). The minimise button collapses the bar to a single restore chip that
still supports press-and-drag.
"""

from __future__ import annotations

import time

from PySide6.QtCore import QEvent, QPoint, QPointF, QRectF, QSize, Qt, Signal
from PySide6.QtGui import QColor, QIcon, QPainter, QPen, QPixmap
from PySide6.QtWidgets import (
    QComboBox,
    QHBoxLayout,
    QLabel,
    QProgressBar,
    QSlider,
    QToolButton,
    QWidget,
)


class EraseToolbar(QWidget):
    """Compact overlay bar; emits intents, the window owns the behaviour."""

    sizeChanged = Signal(int)
    brushToggled = Signal(bool)
    cancelRequested = Signal()

    def __init__(self, parent: QWidget) -> None:
        super().__init__(parent)
        self.setObjectName("EraseBar")
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        self.setStyleSheet(
            "QWidget#EraseBar {"
            " background: rgba(38,38,38,210);"
            " border: 1px solid #4a4a4a;"
            " border-radius: 10px;"
            "}"
            "QLabel { color: #dcdcdc; }"
            "QToolButton { color: #e6e6e6; border: none; border-radius: 6px;"
            " padding: 4px 8px; }"
            "QToolButton:hover { background: #3a3a3a; }"
            "QToolButton:checked { background: #2f6fb5; color: #ffffff; }"
            "QComboBox { color: #e6e6e6; background: #2f2f2f;"
            " border: 1px solid #4a4a4a; border-radius: 6px; padding: 2px 6px; }"
        )
        self._drag_offset: QPoint | None = None
        self._user_moved = False
        self._minimized = False
        self._progress_active = False
        self._mini_press_at: QPoint | None = None
        self._mini_press_time = 0.0
        self._mini_moved = False

        layout = QHBoxLayout(self)
        layout.setContentsMargins(6, 3, 8, 3)
        layout.setSpacing(4)

        self.handle = QLabel("✥")
        self.handle.setToolTip("拖动工具条")
        self.handle.setCursor(Qt.CursorShape.SizeAllCursor)
        layout.addWidget(self.handle)

        self.brush_button = QToolButton()
        self.brush_button.setCheckable(True)
        self.brush_button.setIcon(self._eraser_icon())
        self.brush_button.setIconSize(QSize(22, 22))
        self.brush_button.setFixedSize(32, 28)
        self.brush_button.setToolTip("画笔 (B)：左键擦除，右键恢复")
        self.brush_button.toggled.connect(lambda on: self.brushToggled.emit(on))
        layout.addWidget(self.brush_button)

        self.size_title = QLabel("大小")
        layout.addWidget(self.size_title)
        self.size_slider = QSlider(Qt.Orientation.Horizontal)
        self.size_slider.setRange(4, 200)
        self.size_slider.setValue(32)
        self.size_slider.setFixedWidth(90)
        self.size_slider.valueChanged.connect(self._on_size)
        layout.addWidget(self.size_slider)
        self.size_label = QLabel("32px")
        self.size_label.setFixedWidth(36)
        layout.addWidget(self.size_label)

        self.engine_box = QComboBox()
        self.engine_box.addItems(["快速", "精细"])
        self.engine_box.setCurrentIndex(0)
        self.engine_box.setMinimumWidth(72)
        self.engine_box.setToolTip("快速=masked；精细=当前底部擦除引擎（LaMa）")
        layout.addWidget(self.engine_box)

        self.progress = QProgressBar()
        self.progress.setRange(0, 0)
        self.progress.setFixedSize(70, 6)
        self.progress.setTextVisible(False)
        self.progress.setStyleSheet(
            "QProgressBar { background: #262626; border: 1px solid #3a3a3a;"
            " border-radius: 3px; }"
            "QProgressBar::chunk { background: #4f9cf9; border-radius: 3px; }"
        )
        self.progress.hide()
        layout.addWidget(self.progress)
        self.cancel_button = QToolButton()
        self.cancel_button.setText("取消")
        self.cancel_button.clicked.connect(lambda: self.cancelRequested.emit())
        self.cancel_button.hide()
        layout.addWidget(self.cancel_button)

        self.minimize_button = QToolButton()
        self.minimize_button.setText("—")
        self.minimize_button.setToolTip("最小化工具条")
        self.minimize_button.clicked.connect(self.minimize)
        layout.addWidget(self.minimize_button)

        self.mini_button = QToolButton(self)
        self.mini_button.setIcon(self._expand_icon())
        self.mini_button.setIconSize(QSize(16, 16))
        self.mini_button.setFixedSize(30, 24)
        self.mini_button.setToolTip("长按拖动，短按还原工具条")
        self.mini_button.hide()
        layout.addWidget(self.mini_button)

        self._full_widgets = [
            self.handle,
            self.brush_button,
            self.size_title,
            self.size_slider,
            self.size_label,
            self.engine_box,
            self.progress,
            self.cancel_button,
            self.minimize_button,
        ]
        self.adjustSize()
        self.handle.installEventFilter(self)
        self.mini_button.installEventFilter(self)
        parent.installEventFilter(self)

    # -- geometry ---------------------------------------------------------
    def _expand_icon(self) -> QIcon:
        """Windows-style restore/expand glyph: two overlapping squares."""
        pixmap = QPixmap(32, 32)
        pixmap.fill(Qt.GlobalColor.transparent)
        painter = QPainter(pixmap)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        pen = QPen(QColor("#e6e6e6"), 2.0)
        pen.setCapStyle(Qt.PenCapStyle.SquareCap)
        painter.setPen(pen)
        painter.drawRect(9, 6, 15, 15)
        painter.fillRect(6, 11, 16, 15, QColor(38, 38, 38, 210))
        painter.drawRect(6, 11, 16, 15)
        painter.end()
        return QIcon(pixmap)

    def _eraser_icon(self) -> QIcon:
        """Simple tilted eraser drawn with QPainter (no font glyph)."""
        pixmap = QPixmap(32, 32)
        pixmap.fill(Qt.GlobalColor.transparent)
        painter = QPainter(pixmap)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.translate(16, 16)
        painter.rotate(-38)
        pen = QPen(QColor("#e6e6e6"), 2.0)
        pen.setJoinStyle(Qt.PenJoinStyle.RoundJoin)
        painter.setPen(pen)
        painter.drawRoundedRect(QRectF(-6, -9, 12, 18), 2, 2)
        painter.drawLine(QPointF(-6, 3), QPointF(6, 3))
        painter.end()
        return QIcon(pixmap)

    def default_position(self) -> QPoint:
        parent = self.parentWidget()
        if parent is None:
            return QPoint(12, 12)
        return QPoint(12, 12)

    def show_bar(self) -> None:
        self.adjustSize()
        if not self._user_moved:
            self.move(self.default_position())
        self.show()
        self.raise_()

    def hide_bar(self) -> None:
        self.stop_progress()
        self.hide()

    def minimize(self) -> None:
        if self._progress_active:
            return
        self._minimized = True
        for widget in self._full_widgets:
            widget.hide()
        self.mini_button.show()
        self.layout().activate()
        self.adjustSize()
        if not self._user_moved:
            self.move(self.default_position())

    def restore_bar(self) -> None:
        self._minimized = False
        self.mini_button.hide()
        for widget in self._full_widgets:
            if widget in (self.progress, self.cancel_button):
                continue
            widget.show()
        if self._progress_active:
            self.progress.show()
            self.cancel_button.show()
        self.layout().activate()
        self.adjustSize()
        if not self._user_moved:
            self.move(self.default_position())
        else:
            self._clamp()

    def is_minimized(self) -> bool:
        return self._minimized

    def eventFilter(self, obj, event) -> bool:  # noqa: N802 - Qt name
        if obj is self.handle:
            if event.type() == QEvent.Type.MouseButtonPress:
                self._drag_offset = event.globalPosition().toPoint() - self.pos()
                return True
            if event.type() == QEvent.Type.MouseMove and self._drag_offset:
                self.move(event.globalPosition().toPoint() - self._drag_offset)
                self._user_moved = True
                self._clamp()
                return True
            if event.type() == QEvent.Type.MouseButtonRelease:
                self._drag_offset = None
                return True
        if obj is self.mini_button:
            if event.type() == QEvent.Type.MouseButtonPress:
                self._mini_press_at = event.globalPosition().toPoint()
                self._mini_press_time = time.monotonic()
                self._mini_moved = False
                self._drag_offset = self._mini_press_at - self.pos()
                return True
            if event.type() == QEvent.Type.MouseMove and self._drag_offset:
                if (
                    event.globalPosition().toPoint() - (self._mini_press_at or QPoint())
                ).manhattanLength() > 4:
                    self._mini_moved = True
                    self._user_moved = True
                self.move(event.globalPosition().toPoint() - self._drag_offset)
                self._clamp()
                return True
            if event.type() == QEvent.Type.MouseButtonRelease:
                elapsed = time.monotonic() - self._mini_press_time
                self._drag_offset = None
                if not self._mini_moved and elapsed < 0.5:
                    self.restore_bar()
                return True
        if (
            obj is self.parentWidget()
            and event.type() == QEvent.Type.Resize
            and not self._user_moved
        ):
            self.move(self.default_position())
        return super().eventFilter(obj, event)

    def _clamp(self) -> None:
        parent = self.parentWidget()
        if parent is None:
            return
        x = min(max(0, self.x()), max(0, parent.width() - self.width()))
        y = min(max(0, self.y()), max(0, parent.height() - self.height()))
        self.move(x, y)

    # -- state ------------------------------------------------------------
    def brush_active(self) -> bool:
        return self.brush_button.isChecked()

    def set_brush_checked(self, checked: bool) -> None:
        if self.brush_button.isChecked() == checked:
            return
        self.brush_button.blockSignals(True)
        self.brush_button.setChecked(checked)
        self.brush_button.blockSignals(False)

    def brush_size(self) -> int:
        return int(self.size_slider.value())

    def engine(self) -> str:
        return "lama" if self.engine_box.currentIndex() == 1 else "masked"

    def start_progress(self) -> None:
        self._progress_active = True
        self.progress.show()
        self.cancel_button.show()
        self.minimize_button.setEnabled(False)

    def stop_progress(self) -> None:
        self._progress_active = False
        self.progress.hide()
        self.cancel_button.hide()
        self.minimize_button.setEnabled(True)

    # -- signals ----------------------------------------------------------
    def _on_size(self, value: int) -> None:
        self.size_label.setText(f"{value}px")
        self.sizeChanged.emit(int(value))
