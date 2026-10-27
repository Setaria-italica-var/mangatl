# mangatl

**一键化本地漫画翻译：检测 → OCR → LLM 翻译 → 擦除原文 → 按原样式嵌字（含竖排）。**

桌面 GUI，便携版（解压即用）。日→中为主，兼英→中。

> 状态：**设计阶段（v0.3）**。架构与契约已冻结，代码尚未开始实现。
> 设计文档见 [`docs/design.md`](docs/design.md)。

---

## 它解决什么问题

现有开源方案（manga-image-translator、BallonsTranslator 等）能跑通流程，但普遍存在两个问题：

1. **嵌字是"贴上去的"**：字号、断行、标点、竖排都不够讲究，成品需要大量手工返工。
2. **架构把你锁死**：要么绑死 Qt（headless 也要拉起整套窗口），要么是几千行的脚本，二次开发成本高于重写。

mangatl 的取舍：

- **排版是一等公民**：中文竖排按真正的竖排规则排——列推进、列首/列尾禁则、`。、` 右上定位、括号与长音旋转、纵中横/回転。
- **core 不 import Qt**：GUI 只是订阅者，CLI 与批处理共用同一条流水线。
- **两个进程**：模型跑在独立 engine 进程里，OOM 与崩溃不拖垮界面。
- **渲染只有一份实现**：画布上看到的像素，就是导出的像素。

## 特性

- 文本检测：comic-text-detector（框 + 行四边形 + 文字掩膜）
- OCR：日文 manga-ocr（竖排）/ 英中等 PP-OCRv5
- 翻译：任意 OpenAI 兼容端点（DeepSeek / OpenAI / OpenRouter / Ollama / vLLM），术语表 + 上下文 + 成本统计
- 擦除：纯色气泡快路径 + LaMa 修复，掩膜自检
- 排版：字号自适应、中英断行、禁则、描边、角度、竖排
- 校对：画布 + 逐块编辑 + 单页重渲染（< 300 ms）
- 便携：单 zip，数据全在程序目录，无注册表、无管理员权限

## 架构

```
GUI (PySide6)  ──命令/事件──  engine 进程（无 Qt）
项目│运行│校对│设置│导出       PipelineService: load→detect→ocr→translate→erase→render
                               ModelPool / 四类适配器注册表
                                            │
                               data/ (配置/模型/字体) + projects/ (项目)
```

详细设计：[`docs/design.md`](docs/design.md)（含竖排规格、8 GB 显存档位、里程碑）。
便携版数据契约：[`docs/portable-data-contract.md`](docs/portable-data-contract.md)。

## 目录

```
src/mangatl/
  core/      流水线编排：阶段状态机、断点、取消、预算
  domain/    Page / TextBlock / TextStyle / ProjectStore
  adapters/  detectors / ocr / inpaint / translators（注册表 + Protocol）
  render/    横排与竖排布局、断行、字体测量、光栅化
  io/        CBZ / 文件夹 / 缓存
  engine/    引擎进程：server / protocol / model_pool
  gui/       PySide6 界面
  cli/       命令行
docs/        设计文档、便携版契约、用户说明、调研笔记
```

## 路线图

| 阶段 | 内容 | 状态 |
|---|---|---|
| M0 | 10 页样本 spike，验证抹字与竖排 | 未开始 |
| M1 | core + engine + CLI + 断点 | 未开始 |
| M2 | 横/竖排版 + 校对骨架 | 未开始 |
| M3 | 完整 GUI + 便携打包 | 未开始 |

## 开发

```bash
python -m venv .venv && . .venv/Scripts/activate   # Windows
pip install -e ".[dev]"
ruff check .
pytest
```

要求 Python ≥ 3.11；GPU 可选（CUDA 12 推荐，CPU 亦可运行但慢 3–5 倍）。

工程约定见 [`AGENTS.md`](AGENTS.md)——尤其是「core 不得 import Qt」与「单文件 ≤ 800 行」。

## 许可证

GPL-3.0。完整源码随二进制分发（便携包里带 `source/`）。
Qt/PySide6 以 LGPL-3.0 动态链接。

第三方组件、移植代码来源与模型许可见 [`NOTICE`](NOTICE)。

## 免责声明

- 机翻结果仅供个人阅读参考；公开分享时请显著标注「机翻」。
- 请勿用于侵犯版权或违反所在地区法律的用途。
- 翻译需自备 API Key，Key 默认不落盘。
