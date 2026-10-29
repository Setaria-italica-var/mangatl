# 引入 mit48px / mit48px_ctc 的可行性评估

## 这是什么

`mit48px` 系列是 [manga-image-translator](https://github.com/zyddnys/manga-image-translator) 的漫画专用行级 OCR：

- 输入是**单行文字图**，统一缩放到高 48px
- 两个变体：`mit48px`（自回归 + beam search，慢、准）与 `mit48px_ctc`（CTC 解码，快）
- 依赖：`torch`、`einops`
- 权重：HuggingFace `dreMaz/mit_models`（`ocr-ctc.zip` → `ocr-ctc.ckpt` + `alphabet-all-v5.txt`）

BallonsTranslator 把两者都注册成 OCR 模块，`_line_only = True`，逐文字行识别后再拼成块。

## 许可证

| 对象 | 许可 | 与本项目 GPL-3.0 |
|---|---|---|
| manga-image-translator 代码 | GPL-3.0 | 兼容，可移植，需保留来源头 |
| BallonsTranslator 移植代码 | GPL-3.0 | 兼容 |
| `mit_models` 权重 | 模型卡未标注 | 不随仓库分发，用户自行下载 |

结论：**代码可以移植**，但要在 `NOTICE` 登记来源，权重走用户下载。

## 与我们现状的匹配度

| 维度 | 评价 |
|---|---|
| 输入粒度 | 我们检测器已经产出**行级框**（`merge_lines=False`），天然匹配 |
| 日文支持 | 词表 `alphabet-all-v5` 含日文假名/汉字，但语言无关，不专门优化日语语法 |
| 强项 | 漫画装饰字、倾斜行、SFX；比 manga-ocr 更容忍艺术字体 |
| 弱项 | 正常对白的准确率不如 manga-ocr；自回归版在 CPU 上慢 |
| 体积 | torch 运行时大；ONNX 化后只需 onnxruntime |

## 推荐路线

### 阶段一：CTC 变体做二引擎（1 天）

1. 移植 `mit48px_ctc.py`（514 行，拆成 `model.py` + `runner.py` 以满足 800 行限制）
2. 依赖 `torch` + `einops`（仅此引擎可选，缺失时该名称不出现）
3. 预处理：行框裁图 → 等比缩放到高 48 → 右侧补零到 4 的倍数
4. 注册 `--ocr mit48px_ctc`，先在低分块上与 manga-ocr 对比

### 阶段二：如果有效，ONNX 化（半天）

1. 写 `tools/export_mit48px.py`：加载 ckpt → `torch.onnx.export` → 校验输出一致
2. 运行时改 onnxruntime，去掉 torch 依赖（便携版体积关键）
3. 作为 L2 第二引擎替换 RapidOCR

### 阶段三：并入校验链

```
manga-ocr → 分数低 → mit48px_ctc（行级，快） → 仍低 → L3 文本裁判 → L4 视觉
```

## 风险

1. **权重许可证不明**：模型卡没写许可，只能用户自取、不进仓库
2. **词表依赖**：必须随权重一起放 `data/alphabet-all-v5.txt`，否则解码失败
3. **CPU 速度**：CTC 单行约 30–80ms，一本 180 页约 2000 行 → 1–3 分钟，可接受
4. **收益不确定**：它在装饰字上比 manga-ocr 强，但可能仍读不出第 7 页那种密集小字；需要实测
5. **代码量**：514 行模型代码 + 预处理，属于中等移植

## 结论

**可以引入，建议先做 CTC 变体的可选引擎**（不替换默认），用第 3、7 页的低分块验证收益；
若明显优于 RapidOCR，再 ONNX 化并接入校验链。视觉模型（L4）仍作为最后兜底保留。
