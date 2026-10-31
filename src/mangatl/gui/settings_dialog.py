"""Settings dialog: translation endpoint, region worker behaviour, environment."""

from __future__ import annotations

import os
import sys

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QApplication,
    QDialog,
    QHBoxLayout,
    QScrollArea,
    QSpinBox,
    QVBoxLayout,
    QWidget,
)
from qfluentwidgets import (
    BodyLabel,
    CaptionLabel,
    CheckBox,
    ComboBox,
    LineEdit,
    PrimaryPushButton,
    PushButton,
)
from qfluentwidgets import (
    FluentIcon as FIF,
)

from mangatl import paths
from mangatl.gui.data_browser import DataBrowserDialog
from mangatl.io import secrets as secure
from mangatl.io import settings as prefs

PRESETS = [
    "DeepSeek 云端",
    "Ollama 本地",
    "LM Studio 本地",
    "llama.cpp 本地",
    "回显原文（不翻译）",
    "自定义",
]
PROFILES = ["openai", "ollama", "lmstudio", "llamacpp", "echo", None]
DEFAULT_IDLE_MINUTES = 10


class SettingsDialog(QDialog):
    """Modal settings; saving writes data/settings.json and emits the new values."""

    applied = Signal(dict)

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setWindowTitle("设置")
        self.resize(560, 660)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QScrollArea.Shape.NoFrame)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        body = QWidget()
        form = QVBoxLayout(body)
        form.setContentsMargins(20, 16, 20, 12)
        form.setSpacing(8)

        form.addWidget(BodyLabel("翻译接口"))
        self.preset_box = ComboBox()
        self.preset_box.addItems(PRESETS)
        self.preset_box.currentIndexChanged.connect(self._apply_preset)
        form.addWidget(self.preset_box)
        self.api_key = LineEdit()
        self.api_key.setPlaceholderText("MANGATL_API_KEY，例如 sk-…")
        self.api_key.setEchoMode(LineEdit.EchoMode.Password)
        form.addWidget(self.api_key)
        self.base_url = LineEdit()
        self.base_url.setPlaceholderText("https://api.deepseek.com/v1")
        form.addWidget(self.base_url)
        self.model_name = LineEdit()
        self.model_name.setPlaceholderText("deepseek-chat")
        form.addWidget(self.model_name)
        self.remember_box = CheckBox("记住 Key（Windows DPAPI 加密，仅当前用户可解）")
        form.addWidget(self.remember_box)

        form.addWidget(BodyLabel("后台任务（局部重绘 / 重识别 / 翻译 / 重检测）"))
        idle_row = QHBoxLayout()
        idle_row.addWidget(CaptionLabel("空闲自动退出"))
        self.idle_spin = QSpinBox()
        self.idle_spin.setRange(0, 180)
        self.idle_spin.setSuffix(" 分钟")
        self.idle_spin.setToolTip(
            "0 = 一直保留后台进程；空闲超过该时间后退出，下次任务重新加载模型"
        )
        idle_row.addWidget(self.idle_spin)
        idle_row.addStretch(1)
        form.addLayout(idle_row)
        self.soft_cancel_box = CheckBox("取消时等待当前任务完成（软取消，结果丢弃）")
        self.soft_cancel_box.setToolTip(
            "对所有后台任务生效：\n"
            "关闭（默认）：立即杀掉后台进程，下次任务需要重新加载模型；\n"
            "开启：当前任务继续跑完但结果丢弃，模型保持热启动。"
        )
        form.addWidget(self.soft_cancel_box)

        form.addWidget(BodyLabel("启动与预览"))
        self.auto_preview_box = CheckBox("启动时开启实时预览")
        form.addWidget(self.auto_preview_box)

        form.addWidget(BodyLabel("环境"))
        self.env_label = CaptionLabel("")
        self.env_label.setWordWrap(True)
        form.addWidget(self.env_label)
        self.key_label = CaptionLabel("")
        form.addWidget(self.key_label)
        form.addWidget(CaptionLabel("依赖清单：requirements.txt（更新依赖运行 setup.bat）"))
        path_row = QHBoxLayout()
        self.path_label = CaptionLabel(
            f"数据目录：{paths.display_path(paths.data_dir())}"
        )
        self.path_label.setToolTip(str(paths.data_dir()))
        self.path_label.setWordWrap(True)
        path_row.addWidget(self.path_label, 1)
        open_button = PushButton(FIF.FOLDER, "打开数据目录")
        open_button.clicked.connect(self._open_data_dir)
        path_row.addWidget(open_button)
        form.addLayout(path_row)

        self.status = CaptionLabel("")
        self.status.setStyleSheet("color: #d9822b;")
        form.addWidget(self.status)
        form.addStretch(1)
        scroll.setWidget(body)
        layout.addWidget(scroll, 1)

        buttons = QHBoxLayout()
        buttons.setContentsMargins(20, 8, 20, 14)
        buttons.addStretch(1)
        close_button = PushButton("关闭")
        close_button.clicked.connect(self.reject)
        buttons.addWidget(close_button)
        save_button = PrimaryPushButton(FIF.ACCEPT, "保存")
        save_button.setMinimumHeight(32)
        save_button.clicked.connect(self._save)
        buttons.addWidget(save_button)
        layout.addLayout(buttons)

        self._load()

    # -- state ------------------------------------------------------------
    def _load(self) -> None:
        saved = prefs.load_settings()
        profile = saved.get("profile", "openai")
        names = ["openai", "ollama", "lmstudio", "llamacpp", "echo"]
        self.preset_box.setCurrentIndex(
            names.index(profile) if profile in names else 5
        )
        self.base_url.setText(
            saved.get("base_url") or os.environ.get("MANGATL_BASE_URL", "")
        )
        self.model_name.setText(
            saved.get("model") or os.environ.get("MANGATL_MODEL", "")
        )
        if os.environ.get("MANGATL_API_KEY"):
            self.api_key.setText(os.environ["MANGATL_API_KEY"])
        self.remember_box.setChecked(
            secure.load_key(paths.secrets_path()) is not None
        )
        self.idle_spin.setValue(
            int(saved.get("worker_idle_minutes", DEFAULT_IDLE_MINUTES))
        )
        self.soft_cancel_box.setChecked(
            bool(
                saved.get("soft_cancel_tasks", saved.get("soft_cancel_region", False))
            )
        )
        self.auto_preview_box.setChecked(bool(saved.get("auto_preview_default", True)))
        self.env_label.setText(
            f"Python {sys.version.split()[0]} · 程序目录 {paths.app_root().name}"
        )
        self.env_label.setToolTip(str(paths.app_root()))
        self._refresh_key_state()

    def _open_data_dir(self) -> None:
        """Open Explorer without Qt's ShellExecute warning; copy the path on failure."""
        directory = paths.data_dir()
        directory.mkdir(parents=True, exist_ok=True)
        try:
            os.startfile(str(directory))  # type: ignore[attr-defined]
            return
        except (AttributeError, OSError):
            pass
        # Windows shell launch can be denied (restricted session); show the same
        # directory inside the app instead of failing silently.
        QApplication.clipboard().setText(str(directory))
        DataBrowserDialog(directory, self).exec()

    def _refresh_key_state(self) -> None:
        configured = bool(os.environ.get("MANGATL_API_KEY"))
        self.key_label.setText("翻译 API：" + ("已配置" if configured else "未配置"))

    def _apply_preset(self) -> None:
        from mangatl.adapters.translators.openai_compat import PROFILES as TABLE

        profile = PROFILES[self.preset_box.currentIndex()]
        if profile == "echo":
            self.base_url.setText("")
            self.model_name.setText("")
            self.api_key.setEnabled(False)
            self.api_key.setPlaceholderText("回显原文模式不需要 Key")
            return
        if profile is None:
            self.api_key.setEnabled(True)
            return
        base, model, needs_key = TABLE[profile]
        self.base_url.setText(base)
        self.model_name.setText(model)
        self.api_key.setEnabled(needs_key)
        self.api_key.setPlaceholderText(
            "本地模型通常不需要 Key" if not needs_key else "MANGATL_API_KEY，例如 sk-…"
        )

    def _save(self) -> None:
        profile = PROFILES[self.preset_box.currentIndex()] or "openai"
        key = self.api_key.text().strip()
        base = self.base_url.text().strip()
        model = self.model_name.text().strip()
        switched_to_echo = False
        if profile == "openai" and not key:
            # Neither a key nor a local profile: keep the pipeline usable by echoing
            # the source text instead of refusing to save.
            profile = "echo"
            switched_to_echo = True
            self.preset_box.setCurrentIndex(PROFILES.index("echo"))
            self.status.setText("未配置 Key，已切换为回显原文")
        values = {
            "profile": profile,
            "base_url": base,
            "model": model,
            "worker_idle_minutes": int(self.idle_spin.value()),
            "soft_cancel_tasks": bool(self.soft_cancel_box.isChecked()),
            "auto_preview_default": bool(self.auto_preview_box.isChecked()),
            "api_ready": True,
            "switched_to_echo": switched_to_echo,
        }
        prefs.save_settings(values)
        if profile == "echo":
            for variable in ("MANGATL_API_KEY", "MANGATL_BASE_URL", "MANGATL_MODEL"):
                os.environ.pop(variable, None)
            prefs.clear_api_key()
        else:
            if key:
                os.environ["MANGATL_API_KEY"] = key
            else:
                os.environ.pop("MANGATL_API_KEY", None)
            if base:
                os.environ["MANGATL_BASE_URL"] = base
            else:
                os.environ.pop("MANGATL_BASE_URL", None)
            if model:
                os.environ["MANGATL_MODEL"] = model
            else:
                os.environ.pop("MANGATL_MODEL", None)
            if key and self.remember_box.isChecked():
                stored = prefs.save_api_key(key)
                self.status.setText(
                    "已保存" if stored else "DPAPI 不可用，Key 仅本次有效"
                )
            else:
                prefs.clear_api_key()
        self._refresh_key_state()
        self.applied.emit(values)
        self.accept()
