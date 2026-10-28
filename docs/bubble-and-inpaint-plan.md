# 气泡检测与擦除：模型方案

启发式判据在这批扫描件上的准确率已经封顶（亮窗口 49/54 过松、闭环 2/54 过紧、
亮连通域 17/54）。根因是“气泡内 vs 画面内嵌字”是一个**语义分割问题**，不是阈值问题。
结论：改用社区模型，启发式只保留为依赖缺失时的兜底。

## 1. 参考项目与模型

| 来源 | 用途 | 备注 |
|---|---|---|
| `ogkalu/comic-speech-bubble-detector-yolov8m` | YOLOv8m 气泡检测（1 类） | 默认；文件名通常是 `best.pt` |
| `ogkalu/comic-text-and-bubble-detector` | YOLOv8m，2 类：text / bubble | 同时给文字框，可代替 CTD 做交叉验证 |
| `kitsumed/yolov8m_seg-speech-bubble` | YOLOv8 分割，输出气泡多边形 | 分割头解码尚未实现 |
| `mayocream/speech-bubble-segmentation` | 分割备选 | 同上 |
| BallonsTranslator | 工程参考：CTD 检测 + 掩膜内缩 + LaMa 修复 | 我们的 `masked` 擦除思路与之同源 |
| `Carve/LaMa-ONNX`、Big-LaMa | 掩膜修复（inpainting） | 比扩散填充干净，专治“马赛克” |
| manga-ocr / RapidOCR | 文字识别 | 已在用 |

许可证：YOLOv8 系权重由 Ultralytics 训练，**AGPL-3.0**，与本工程 GPL-3.0 兼容但义务更严；
权重不随仓库分发，由用户自行下载，`models/manifest.json` 记录来源与许可。

## 2. 决策流程

```
            ┌── 有气泡模型？ ──┐
            │ 是               │ 否
            ▼                  ▼
   气泡框（YOLO）        启发式兜底（strict）
            │                  │
            └────┬─────────────┘
                 ▼
   文字块是否被气泡包含（覆盖率 ≥ 0.8）
        ├─ 是 → 擦除 + 翻译 + 排版（限制在气泡内）
        └─ 否 → 不擦、不译（画面内嵌拟声词/招牌）
```

要点：

1. **包含关系用面积占比判定**，容忍气泡边界 2–3 px；
2. 没有气泡模型时退回 `strict`（宁可不擦，不误伤画面）；
3. `--erase-blocks page:id` / `--keep-blocks page:id` 永远优先，用于手工纠正。

## 3. 擦除：掩膜 + 专用修复

已有约束保持不变（只擦文字像素、结构线保护、不涂整块）。新增：

- 气泡内（背景平坦）：用**中位色填充**，天然无痕；
- 气泡内但背景不平坦 / 画面内：用 **LaMa ONNX**（若权重存在），否则扩散填充；
- 掩膜按块内缩 1 px、闭运算补洞，避免边缘残留。

## 4. 排版：气泡几何而非文字框

有了气泡框后，排版区域用 `气泡 ∩ 文字框`：

- 左右留 8% 边距，避免压线；
- 字号按气泡内切矩形二分；
- 竖排时按气泡高度分列。

这解决“字贴气泡边”的问题；没有气泡模型时仍用文字框。

## 5. 权重放置与获取

```
data/models/
  bubble_detector.onnx     # YOLOv8 气泡检测
  lama.onnx                # 可选：LaMa 修复
  comictextdetector.pt.onnx
```

获取（在本机终端，需要能访问 HF 镜像）：

```bat
:: 推荐：项目自带下载器，不依赖 huggingface-cli
set HF_ENDPOINT=https://hf-mirror.com
uv pip install ultralytics
python -m mangatl fetch-models
```

`fetch-models` 会拉取模型卡文件列表、下载 `best.pt` 等权重，并在装了
`ultralytics` 时自动导出 `data/models/bubble_detector.onnx`。

替代方案（HF 官方 CLI 从 0.34 起改名为 `hf`，旧名 `huggingface-cli` 可能不存在）：

```bat
hf download ogkalu/comic-speech-bubble-detector --local-dir data/models/bubble-src
python -c "from huggingface_hub import snapshot_download as d; d('ogkalu/comic-speech-bubble-detector', local_dir='data/models/bubble-src')"
```

验证：`python -m mangatl probe data\models\bubble_detector.onnx` 应打印
`images [1,3,640,640]` 与 `output`/`output0` 形状。

## 6. 实施顺序

1. `adapters/detectors/bubbles.py`：ONNX YOLOv8 检测 + NMS + 包含判定（本次）
2. `--bubbles auto|model|heuristic|off` 接入流水线（本次）
3. `adapters/inpaint/lama.py`：LaMa ONNX，缺失时回退（本次）
4. 气泡内排版边距（下一步）
5. 分割模型（多边形）支持（可选）
