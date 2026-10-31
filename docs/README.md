# 文档索引

| 文件 | 内容 |
|---|---|
| [user-guide.md](user-guide.md) | **最终用户说明**：安装、配置、运行、校对、擦除、常见问题 |
| [gui.md](gui.md) | 桌面编辑器：布局、三种预览、区域操作、悬浮工具条、后台任务 |
| [setup-windows.md](setup-windows.md) | Windows 开发/运行环境：runtime、setup.bat、代理、常见错误 |
| [launcher.md](launcher.md) | `启动.bat` / `setup.bat` / `诊断.bat` 的职责与排障 |
| [portable-data-contract.md](portable-data-contract.md) | `data/` 目录、`settings.json`、模型清单、密钥存储契约 |
| [release-notes-v0.3.0.md](release-notes-v0.3.0.md) | v0.3.0 发布说明与安装步骤 |
| [release-checklist.md](release-checklist.md) | 发布前检查：合规、便携、质量、材料 |
| [design.md](design.md) | 早期架构设计（分层、竖排规格、里程碑；部分内容已被实现取代） |
| [m0-plan.md](m0-plan.md) | M0 样本 spike 的范围与验收记录 |
| [bubble-and-inpaint-plan.md](bubble-and-inpaint-plan.md) | 气泡检测与擦除范围的设计记录 |
| [mit48px-plan.md](mit48px-plan.md) | MIT48px OCR 接入计划 |
| [ocr-verification-plan.md](ocr-verification-plan.md) | OCR 多引擎校验方案 |
| [local-vision-setup.md](local-vision-setup.md) | 本地视觉模型（llama.cpp）配置 |
| [ui-modules.md](ui-modules.md) | 右侧模块、搜索、批量面板拆分 |
| [ui-theme.md](ui-theme.md) | 暗色主题与控件样式 |

## 阅读顺序

1. **普通用户**：`README.md` → `user-guide.md`
2. **二次开发**：`README.md` → `AGENTS.md` → `design.md` 的分层部分 → `gui.md`
3. **改打包/配置**：`portable-data-contract.md` → `launcher.md` → `release-checklist.md`
4. **排障**：`setup-windows.md` → `launcher.md`；GUI 未捕获异常看 `data/error.log`
