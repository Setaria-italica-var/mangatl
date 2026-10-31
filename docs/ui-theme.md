# 界面美化：可选开源方案与当前实现

## 现状：已迁移到 Fluent

采用 **PySide6-Fluent-Widgets**（GPL-3.0）作为控件层，叠加暗色 Qt 底座（QSS + QPalette）。
工具栏、按钮、输入框、表格、页签均为 Fluent 控件；主窗口/停靠面板用 QSS 融入暗色。
底部页签是**模块切换器**（编辑/文本块/搜索/运行/设置），页面仍在左侧列表。

## 早期自定义主题（已被 Fluent 取代）

已实现**自定义暗色工作区主题**（`gui/theme.py`）：Fusion 基底 + 深灰面板 +
单一强调色 `#4f9cf9` + 圆角控件 + 细滚动条 + Font Awesome 图标。
零额外依赖（图标可选 `qtawesome`），保持便携。

## 可选的成熟开源 UI 方案

| 项目 | 风格 | 许可 | 集成成本 | 评价 |
|---|---|---|---|---|
| [PySide6-Fluent-Widgets](https://pypi.org/project/PySide6-Fluent-Widgets/) | Windows 11 Fluent：Mica 背景、圆角卡片、侧边导航、内置标题栏 | **GPL-3.0** | 中（控件替换，约 1–2 天） | 与 Win11 最协调，组件齐全，含图标库 |
| [Qt-Material](https://qt-material.readthedocs.io/) | Material Design 亮/暗主题 | BSD-2 | 低（一行 `apply_stylesheet`） | 快速换色，控件仍是原生风格 |
| [qdarkstyle](https://github.com/ColinDuquesnoy/QDarkStyleSheet) | 专业暗色（偏 Qt） | MIT | 低 | 中性、稳妥，与当前风格接近 |
| [PyDracula](https://github.com/ag-python-qt/PyDracula) | 现代暗色 + 自定义标题栏/侧栏 | 参考为主 | 中 | 布局与配色可借鉴，非通用库 |
| [Qt-Advanced-Docking-System](https://github.com/mborges-pivotal/Qt-Advanced-Docking-System) | 可拖拽停靠布局（类 VS/PS 面板） | LGPL-2.1 | 中 | 需要复杂面板布局时值得 |
| [qtawesome](https://github.com/spyder-ide/qtawesome) | Font Awesome / Material 图标 | MIT | 已完成 | 已用于工具栏 |

## 视觉参考

- **Krita**：深灰画布、工具面板靠边、强调色克制
- **Clip Studio Paint**：深色 + 双列工具、底部页签
- **Photoshop**：中性灰、面板分组、画布最亮
- **Blender**：深色 + 顶部工作区页签（类似我们的底部页签）

## 三种可选方向

| 方向 | 实现 | 适合 |
|---|---|---|
| **A. 继续自定义暗色（当前）** | 已做，后续只调配色/间距 | 想要 PS/Krita 那种专业感，零依赖 |
| **B. Fluent（Win11 风格）** | 引入 `PySide6-Fluent-Widgets`，替换导航/按钮/标题栏 | 想要"现代应用"观感，接受 GPL 与体积 |
| **C. Material（彩色）** | 引入 `qt-material`，一行换主题 | 想要亮色/配色活泼 |

## 许可提示

- 本项目 GPL-3.0：GPL-3.0（Fluent）✅ 兼容；BSD-2/MIT（Qt-Material、qdarkstyle、qtawesome）✅；
  LGPL-2.1（高级停靠）✅（动态链接）。
- 引入 Fluent 会显著增加打包体积（含 Qt 组件与资源），与"便携单文件夹"目标需权衡。
