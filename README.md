# mangatl

本地漫画翻译桌面工具：**检测 → OCR → 翻译 → 擦除原文 → 中文排版**，日文竖排优先，也支持英文。

Windows 10/11 x64 · v0.3.0 · GPL-3.0

> 当前版本是可用的 MVP：核心流程、桌面编辑器、批量任务和便携版都已跑通；
> 不是成熟的商业产品，复杂页面仍可能需要手工校对。

## 能做什么

| 环节 | 实现 |
|---|---|
| 检测 | comic-text-detector（CTD），框 + 文字掩膜 + 气泡/拟声词角色 |
| OCR | manga-ocr（日文，含竖排）、RapidOCR、MIT48px 多套引擎可选 |
| 翻译 | 任意 OpenAI 兼容接口：DeepSeek、OpenAI、OpenRouter、Ollama、LM Studio、llama.cpp；也可选“回显原文”离线占位 |
| 擦除 | 纯色气泡快路径 + masked 扩散 + LaMa 修复；支持整页擦除和手动画笔 |
| 排版 | 字号自适应、中英断行、标点禁则、描边、旋转、竖排 |
| 编辑 | 画布逐块编辑，原文/译文/角色/样式改动实时应用 |
| 批量 | 页码范围、阶段勾选、断点续跑、子进程存活监测、失败重试 |
| 便携 | 内置 Python runtime，解压即用；数据和配置全在程序目录 |

## 下载与启动

从 [Releases](https://github.com/Setaria-italica-var/mangatl/releases) 下载：

- `mangatl-portable-v0.3.0.7z`（约 1.86 GB，已内置模型和运行时）
- `SHA256SUMS.txt`

使用：

1. 安装 [7-Zip](https://www.7-zip.org/)（已安装可跳过）
2. 解压 `mangatl-portable-v0.3.0.7z` 到任意**有写入权限**的目录，例如 `D:\Tools\MangaTL`
3. 双击 `启动.bat`
4. 启动失败时运行 `诊断.bat`，生成的环境信息在 `诊断结果.txt`

不要放在 `C:\Program Files` 或只读目录，程序需要往 `data\` 写配置和缓存。

## 第一次使用

1. **打开漫画文件夹**：只支持图片目录（`.png` / `.jpg` / `.jpeg` / `.webp` / `.bmp`），不支持 CBZ/PDF/EPUB
2. **选引擎**：底部栏分别是检测、OCR、擦除、翻译；默认 `ctd` / `mit_manga` / `masked` / `openai`
3. **配置翻译**：点右侧齿轮（`Ctrl+,`）
   - 云端：选「DeepSeek 云端」，填 API Key，或选「自定义」填任意 OpenAI 兼容地址
   - 本地：Ollama / LM Studio / llama.cpp，填对应地址和模型名
   - 没有 Key：选「回显原文（不翻译）」，可先验证检测、擦除和排版
   - 勾选「记住 Key」会用 Windows DPAPI 加密到 `data\secrets.bin`，仅当前用户可解
4. **运行**：右侧「运行」→「运行当前页」或「开始批量」
5. **校对**：右侧「编辑」面板改原文/译文/样式，停止输入约 300ms 后自动保存并重绘
6. **导出**：结果就在漫画目录的 `result\` 下，按原文件名保存

## 界面速览

- 左侧：页面缩略图列表
- 中间：画布，支持缩放、平移、框选、拖拽文本框
- 右侧：编辑 / 运行 / 搜索 等模块；设置固定在图标栏最下方
- 顶部：打开、保存、选择工具、三种预览、全屏、最小化、关闭

预览切换：

| 视图 | 快捷键 | 显示 |
|---|---|---|
| 原图 | `Ctrl+1` | 原始页面 + 检测框，可选中文本块 |
| 擦除后 | `Ctrl+2` | `inpainted/` + 红色已擦除区域，只做区域选区 |
| 排版结果 | `Ctrl+3` | `result/` + 文字框，可拖动调整 |

常用快捷键：

| 快捷键 | 动作 |
|---|---|
| `Ctrl+S` | 保存 `project.json` |
| `Ctrl+Z` | 撤销 |
| `Ctrl+1/2/3` | 原图 / 擦除后 / 排版结果 |
| `Ctrl+,` | 设置 |
| `Ctrl+G` | 跨页搜索 |
| `PageUp/PageDown` | 上一页 / 下一页 |
| `B` | 擦除视图中回到画笔 |

## 擦除视图的悬浮工具条

进入「擦除后」时，画布左上角会出现可拖动的工具条：

- **左键拖动**：橡皮，红色笔迹，松手后按当前引擎填充
- **右键拖动**：恢复，青色笔迹，把**原图像素**贴回笔迹区域
- 大小 4–200px；引擎下拉「快速 / 精细」，默认快速
- 处理时工具条内显示进度和「取消」，不弹模态窗
- 最右侧「—」最小化成一个展开图标；短按还原，按住拖动仍可移动
- 离开擦除视图时隐藏，位置不写入配置，重启回到左上角默认位置

## 从源码运行

仓库不提交 `runtime/` 和 `data/models/`（体积原因）。首次从源码运行：

1. 下载便携版并解压
2. 把便携版的 `runtime\` 和 `data\models\` 复制到仓库根目录
3. 运行 `setup.bat` 更新依赖（需要系统 Python 3.12）
4. 运行 `启动.bat`

之后启动只依赖 `runtime\python.exe`，不需要系统 Python。

常用命令：

```bat
runtime\python.exe -m mangatl gui samples\vol1
runtime\python.exe -m mangatl run samples\vol1 --stages detect,ocr,translate,erase,render
runtime\python.exe -m mangatl fetch-models --lama
runtime\python.exe tools\sync_runtime.py
```

`run` 默认使用 `openai` 翻译，需要 Key；只想验证流程可以加 `--translator echo`。

## 目录结构

```
mangatl/
├─ 启动.bat                 # 主启动脚本（仓库和便携版通用）
├─ setup.bat                # 首次安装/更新 runtime
├─ runtime/                 # 内置 Python 3.12 + 依赖（不提交 Git）
├─ data/                    # 配置、模型、缓存、密钥（不提交 Git）
├─ src/mangatl/
│  ├─ gui/                  # PySide6 界面
│  ├─ core/                 # 流水线编排、阶段状态、断点
│  ├─ domain/               # Page / TextBlock / Project
│  ├─ adapters/             # 检测 / OCR / 翻译 / 擦除
│  ├─ render/               # 横排、竖排、断行、字体测量
│  ├─ io/                   # 设置、密钥、缓存
│  ├─ engine/               # 引擎进程辅助
│  └─ cli/                  # 命令行与后台 task-worker
├─ samples/vol1/            # 10 页示例
├─ tools/                   # 环境检查、同步、打包、诊断
├─ tests/                   # pytest
└─ docs/                    # 设计与使用文档
```

漫画项目目录（用户打开的文件夹）会生成：

```
<漫画目录>/
├─ project.json             # 页面、文本块、阶段状态（原子写入）
├─ inpainted/               # 擦除后的页面
└─ result/                  # 排版结果
```

## 架构

```
GUI (PySide6)
 ├─ QProcess ──> mangatl run ...       批量 / 单页流水线
 ├─ QProcess ──> mangatl task-worker   局部重绘 / 重识别 / 翻译 / 重检测
 └─ core.PipelineService ──> adapters (CTD / OCR / 翻译 / 擦除) + render
```

- `core/`、`domain/`、`adapters/`、`render/`、`io/` 不依赖 PySide6，GUI 只是调用方
- 模型推理放在子进程，界面线程不加载模型；重任务可取消，不阻塞窗口
- 排版只有一份实现，画布预览和导出使用同一套渲染器
- 项目状态每页落盘，崩溃或关闭后可以继续

## 已知限制

- **仅 Windows 10/11 x64**；没有 macOS/Linux 打包
- **CPU 推理**，无 CUDA 加速；LaMa 首次加载约 15–35 秒，之后复用
- 不支持 CBZ/PDF/EPUB，只能打开图片文件夹
- 云端翻译必须自备 API Key；本地模型需要自己启动 Ollama / LM Studio / llama.cpp
- 手绘拟声词、复杂背景和超大页面可能需要手工修正
- 界面和提示目前仅中文

## 开发

```bat
runtime\Scripts\ruff.exe check .
runtime\python.exe -m pytest
```

工程约定见 [`AGENTS.md`](AGENTS.md)：分层依赖、单文件 ≤ 800 行、JSON 原子写入、
遥测与隐私限制。完整测试套件较慢，提交前至少跑 `tests/test_paths.py`、
`tests/test_batch_plan.py` 和与改动相关的测试。

构建便携版：

```bat
runtime\python.exe tools\build_portable_bat.py
```

生成 `dist\mangatl-portable\`；发布前用 `tools\pack_release.ps1` 压缩并生成校验。

## 文档

- [用户说明（详细版）](docs/user-guide.md)
- [界面与交互](docs/gui.md)
- [Windows 开发环境](docs/setup-windows.md)
- [便携版数据契约](docs/portable-data-contract.md)
- [启动器说明](docs/launcher.md)
- [v0.3.0 发布说明](docs/release-notes-v0.3.0.md)
- [架构设计（早期设计文档，部分内容已实现）](docs/design.md)

## 许可证与声明

- 项目以 **GPL-3.0** 发布
- Qt / PySide6 以 LGPL-3.0 动态链接
- 第三方组件、模型和移植代码来源见 [`NOTICE`](NOTICE)

机翻结果仅供个人阅读参考；公开分享请标注「机翻」。请勿用于侵权或违反当地法律的用途。
