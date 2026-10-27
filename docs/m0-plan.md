# M0：可运行的骨架与 Spike 计划

> 目标：在不依赖 GUI、不接翻译、不接真实模型的前提下，把「载入 → 检测 → OCR → 抹字」这条链路跑通，
> 并建立可回归的样本集。M0 结束时，剩下的工作只是把三个适配器换成真模型。

## 1. 范围

**做**

- 项目状态（`project.json`，阶段位掩码，断点续跑）
- 三个适配器协议（Detector / Ocr / Inpainter）与注册表
- 编排服务（逐页执行、单页失败隔离、每页落盘）
- CLI（`python -m mangatl run <dir>`）
- 离线 stub（无 torch / 无 numpy / 无网络也能跑通）
- 端到端测试

**不做**（留给 M1/M2）

- 真实模型推理、模型下载
- 翻译、排版、渲染
- GUI、打包

## 2. 已交付

```
src/mangatl/
  domain/block.py        TextBlock（bbox/text/translation/confidence/vertical/lines）
  domain/project.py      Page / Project，原子写 project.json
  adapters/base.py       Detector / Ocr / Inpainter 协议 + Registry
  adapters/stubs.py      GridDetector / EchoOcr / CopyInpainter
  core/config.py         RunConfig（不可变）+ resolve()
  core/pipeline.py       PipelineService / Event / RunSummary
  cli/main.py            argparse 入口
  __main__.py            python -m mangatl
tests/test_pipeline_stub.py   7 个用例：全阶段、跳过、force、坏页隔离、缺目录、非法阶段、事件
docs/m0-plan.md        本文件
```

## 3. 怎么跑

```bat
cd /d C:\Users\admin\Documents\deepseek-harness\default-workspace\mangatl
.venv\Scripts\activate.bat

:: 端到端（stub，几秒完成）
python -m mangatl run .\samples\vol1

:: 测试与静态检查
python -m pytest -q
python -m ruff check .
```

`<dir>` 里放图片即可；首次运行会扫目录并生成 `project.json`。产物写到 `<dir>\inpainted\`。

**预期**：每页打印 `[001.png] done: N blocks`，最后一行是 JSON 汇总
`{"total": 2, "ok": 2, "failed": 0, "skipped": 0, "blocks": 8}`。

**断点**：再次运行会跳过已完成阶段（不产生事件）；`--force` 强制重跑。

## 4. 样本集（M0 的验收材料）

准备 10 页，放到 `samples/`（不进版本库）：

| 编号 | 类型 | 用途 |
|---|---|---|
| 01–04 | 黑白日漫，**竖排**为主（单列 / 多列 / 带标点 / 带数字） | 竖排检测与 OCR |
| 05–06 | 黑白日漫，横排对话 | 常规路径 |
| 07–08 | 彩色条漫（长图切片） | 接缝与彩色背景 |
| 09–10 | 英文对白 | 英文 OCR 路由 |

## 5. 验收指标

| 项 | 目标 | 测法 |
|---|---|---|
| 端到端可跑 | 10 页无崩溃 | `mangatl run` 退出码 0 |
| 断点续跑 | 二次运行 0 事件 | 看输出 |
| 单页耗时 | ≤ 10 s（8 GB GPU） | 逐页计时 |
| 显存峰值 | ≤ 5.5 GB | `nvidia-smi` 采样 |
| 检测召回 | ≥ 95% | 人工标注 10 页的框数对比 |
| 掩膜干净度 | 明显残留 ≤ 10% 页 | 看 `inpainted/` |
| 竖排 OCR | 字符准确率 ≥ 90% | 人工比对 4 页竖排 |

## 6. 下一步：接真模型（M0.5）

按依赖从少到多推进，每步都可独立验证：

1. **Inpainter → LaMa**：只依赖 torch + numpy + opencv；先做「纯色快路径 + LaMa」两条分支。
2. **Detector → CTD**：torch + 模型权重，产出 bbox / lines / mask。
3. **OCR → manga-ocr（日）/ PP-OCR（英）**：onnxruntime 或 torch。

模型权重（约 1.2 GB）优先走 `hf-mirror.com`；下载清单写进 `data/models/manifest.json`（见
[portable-data-contract.md](portable-data-contract.md)）。

依赖安装示例：

```bat
uv pip install --python .venv\Scripts\python.exe torch --index-url https://download.pytorch.org/whl/cu124
uv pip install --python .venv\Scripts\python.exe numpy opencv-python-headless pillow onnxruntime
```

## 7. 风险

| 风险 | 处置 |
|---|---|
| 模型下载被墙 | `hf-mirror.com` + 断点续传；权重校验 sha256 |
| 8 GB 显存不够 | LaMa 1024 常驻 + 批量卸载；OOM 降 512 |
| 竖排 OCR 差 | manga-ocr 优先；行四边形透视矫正后再识别 |
| 真实图片格式多样 | 载入层统一转 RGB，保留 alpha 通道标记 |
| 测试依赖真实模型 | 保持 stub 路径永远可跑，CI 只跑 stub |
