# AGENTS.md — 工程约定

本文件是**硬约束**，不是建议。新增代码、重构、评审都以此为准；与本文冲突的 PR 直接打回。

## 1. 分层与依赖方向

```
gui ──▶ core ──▶ stages ──▶ adapters / render / io
cli ──▶ core                    │
                          domain（不依赖上层）
engine ──▶ core / adapters
```

- **`core/`、`domain/`、`adapters/`、`render/`、`io/`、`engine/` 不得 `import PySide6`**（CI 检查）。
- 依赖只能自上而下；`domain` 不得 import 任何上层模块。
- 跨层通信只通过 `core/events.py` 定义的事件与 `core/protocol.py` 定义的命令。

## 2. 文件与函数规模

- 单文件 ≤ **800 行**（CI 检查）。超过就拆，而不是加注释分区。
- 单函数 ≤ **80 行**；嵌套 ≤ 4 层。
- 禁止 100 KB 级"上帝模块"——这是本项目立项的直接原因之一。

## 3. 状态与副作用

- **禁止全局可变单例**（不设 `shared.py`、不设模块级 `cfg` 对象）。配置通过 `RunConfig` 显式传入。
- 类属性只放不可变默认值；实例配置一律在 `__init__` 里 `deepcopy` 后持有。
- 所有 JSON 写入：`tmp` 文件 → 校验 → `os.replace`。禁止直接覆写。
- 文件路径一律相对程序目录或项目目录；**仅**用户显式选择的项目路径可用绝对路径，并置 `portable=false`。
- 不写注册表、不写 `%APPDATA%`、不写系统临时区（除 `data/tmp/`）。

## 4. 渲染

- 只有 `render/` 能产生像素；GUI 只能显示 `render/` 的输出。
- 横排与竖排共享「测量 → 适配 → 断行 → 绘制」四步，差异只在布局策略。
- 排版改动必须附带 golden 图 diff（`tests/golden/`），否则不予合并。
- 坐标空间必须在类型里写清楚（page / block-local / em-cell / device），禁止隐式混用。

## 5. 模型与推理

- 推理只在 `engine` 进程；GUI 线程中禁止任何模型调用。
- 模型加载/卸载统一走 `engine/model_pool.py`，禁止在业务代码里直接 `torch.load`。
- 任何新模型必须：在 `models/manifest.json` 注册（sha256 + size + license + urls）、提供 CPU 兜底、给出显存估算。
- OOM 必须降级而不是崩溃：降分辨率 → 降 tile → CPU。

## 6. 外部调用（翻译）

- 只实现 OpenAI 兼容协议；不写厂商专用 SDK。
- 请求/响应必须是 JSON 契约，逐块 ID 校验；缺块补发，单块失败保留原文。
- Key 只存在内存或 `secrets.enc`；**任何日志、异常、崩溃报告都不得包含 Key**。
- 每次调用记录 token 与耗时；成本可查、可设上限。

## 7. 测试

- 纯函数（断行、字号适配、禁则、颜色估计）必须有单元测试。
- 每个阶段至少一个"端到端小样本"测试（1 页图 + 固定假数据）。
- 竖排 8 条用例（见 `docs/design.md` §7.7）是发版门槛。
- 提交前本地跑：`ruff check . && pytest`。

## 8. 代码风格

- Python 3.11+，`from __future__ import annotations` 可选；公开函数必须有类型标注与返回类型。
- 允许 `Any` 只出现在适配器边界（模型输入输出）。
- 错误处理：业务失败用自定义异常（`core/errors.py`）；禁止裸 `except:`。
- 用户可见文案走 `tr()`（GUI）或英文常量（CLI），代码里不写中文提示。
- 注释只写"为什么"与不变量；不写"做了什么"。

## 9. 提交与评审

- 提交信息：`type(scope): summary`，type ∈ feat/fix/refactor/perf/docs/test/chore/build。
- 一个 PR 只做一件事；重构与功能分开。
- PR 描述必须写：改了什么、为什么、怎么验证、对旧项目/旧配置的兼容性影响。
- 涉及排版的 PR 附 before/after 图；涉及性能的 PR 附测量数据。

## 10. 许可证

- 本项目 GPL-3.0。
- 从 BallonsTranslator / manga-image-translator 移植的文件，**保留原版权头**并在 `NOTICE` 登记；不得"洗掉"来源。
- 新增第三方依赖需在 `NOTICE` 增补许可证信息；GPL 不兼容的许可证（如专有、部分 CC）一律不得引入。
- 字体只用 OFL/Apache 许可，且不得重命名后分发。

## 11. 隐私

- 默认不记录漫画原文与译文；`debug` 级别记录时必须启动时明示。
- 不上传任何图片或文本到自制服务器；只调用用户配置的翻译端点。
- 崩溃报告默认只含栈与版本号，不含用户内容。

## 12. 编码

- 所有文本文件（`.md` / `.txt` / `.py` / `.toml` / `.json`）一律 **UTF-8 无 BOM**，换行走 LF（`.gitattributes` 已配）。
- **禁止**用 `Get-Content ... | Set-Content` 或 `[IO.File]::WriteAllText` 改写含中文的文件：PowerShell 会按系统代码页（GBK）解码 UTF-8，回写后中文变成私用区乱码，`git diff` 看不出来。
  需要改中文文档时用编辑器或 `python -c` 显式 `encoding="utf-8"` 读写。
- `tests/test_encoding.py` 会扫描全部文本文件，出现非法 UTF-8 或私用区字符即失败；提交前跑一次 `python -m pytest`。

