# 漫画一键翻译工具 · 选型与架构（v0.3 · 硬件与竖排已定）

> 目标：桌面 GUI，导入文件夹 / CBZ → 检测 → OCR → API Key 翻译 → 擦除原文 → 按原样式嵌字（含竖排）→ 导出。
> 本文只做设计与选型，不含实现代码。

## 已锁定决策

| 项 | 决策 | 影响 |
|---|---|---|
| 形态 | 桌面 GUI（PySide6） | 画布、校对流、撤销栈；core 与 UI 严格解耦 |
| 语言 | 日→中为主，兼英→中 | 两套 OCR 路由与断行规则 |
| **竖排** | **日→中必须支持保留竖排** | 排版引擎要做两套布局（横/竖）+ 竖排禁则与标点旋转 |
| 硬件 | **单张 NVIDIA，8 GB 显存** | 模型档位固定；串行推理；fp16；纯色快路径必做 |
| 规模 | **单本 180 页** | 不需要数据库/多任务队列；项目 JSON + 断点足够 |
| **分发** | **只做便携版**（解压即用 zip，无安装程序） | 数据全在程序目录；无注册表/无管理员；密钥存储要换方案 |
| 许可证 | GPL-3.0 | 可移植 BallonsTranslator / manga-image-translator 代码 |
| 翻译 | 用户自备 API Key，OpenAI 兼容 | 密钥存系统钥匙串；成本可见 |

---

## 0. 一页纸

**技术栈**：Python 3.11+ / PyTorch 2.x (CUDA 12) / PySide6 / OpenCV / Pillow / pkuseg。

**两个进程**：GUI 只发命令与显示位图；engine 持有模型、串行跑六阶段，本地 socket 通信。

```
载入 → 检测(框+行+掩膜) → OCR(日:manga-ocr / 英:PP-OCR) → 翻译(LLM, JSON)
     → 抹字(纯色快路径 + LaMa) → 排版(横/竖) + 渲染(Pillow) → 导出
```

**三条原则**：
1. core 不 import Qt（否则 CLI/批处理全被拖下水）。
2. 渲染只有一份实现：画布像素 = 导出像素。
3. 推理在独立进程：OOM/崩溃/取消都不拖垮 GUI。

**8 GB 显存下的单页预算**：检测 0.3 s + OCR 1 s + 抹字 1.5 s + 渲染 0.15 s ≈ **3–4 s**，加翻译网络 2–6 s，**整页 6–10 s**，180 页约 **20–30 分钟**。

---

## 1. 需求与验收

| 需求 | 验收线 |
|---|---|
| 一键化 | 导入 → 开始 → 全自动；失败页可单独重试 |
| OCR 日 | 竖排召回 ≥ 95%，字符准确率 ≥ 92% |
| OCR 英 | 召回 ≥ 95% |
| 擦除 | 抽检 30 页，明显残留 ≤ 10% 页；气泡边框/网点不破 |
| 翻译 | 不漏块、不串块、不加戏；ID 对齐 100% |
| 嵌字（横排） | 抽检 30 页可读 ≥ 90%；不溢出、不压边 |
| **嵌字（竖排）** | **抽检 30 页可读 ≥ 90%；列首禁则 0 违规；字位相对原文行位置偏差 ≤ 0.5 em** |
| 可校对 | 改译文/改框/改样式；单页重渲染 < 300 ms |
| 成本 | 每页 token/费用可见，可设上限 |

---

## 2. 生态盘点

### 端到端项目（参考，不 fork）

| 项目 | 规模 | 许可 | 借用点 |
|---|---|---|---|
| [manga-image-translator](https://github.com/zyddnys/manga-image-translator) | 10.5k★ | GPL-3.0 | 六阶段范式、模型清单、纯色泡判断 |
| [BallonsTranslator](https://github.com/dmMaze/BallonsTranslator) | 5.2k★ | GPL-3.0 | **行合并/切分/掩膜算法可移植**、配置迁移惯例、坐标空间契约 |
| [comic-translate](https://github.com/ogkalu2/comic-translate) | 3.0k★ | Apache-2.0 | 多格式产品形态、审核 UI 信息架构 |
| [SickZil-Machine](https://github.com/KUR-creative/SickZil-Machine) | 1.5k★，停更 | AGPL-3.0 | 仅历史参考 |

### 组件

| 环节 | 选型 | 许可 | 备注 |
|---|---|---|---|
| 检测 | comic-text-detector | GPL-3.0 | 框 + 行四边形 + 文字掩膜 |
| OCR 日 | manga-ocr | MIT（复核） | 竖排强项 |
| OCR 英/中 | PaddleOCR PP-OCRv5 (ONNX) | Apache-2.0 | 轻量、可 CPU |
| 抹字 | LaMa 1024 + 纯色中位色填充 | Apache-2.0 | 快路径省 50–70% |
| 断行 | pkuseg + 禁则表 | MIT | 中文；英文按词 |
| 渲染 | Pillow + freetype | HPND | 竖排自己排 |
| 翻译 | OpenAI 兼容端点 | — | DeepSeek/OpenAI/OpenRouter/Ollama |

---

## 3. 路线与许可证

选 **自研薄 pipeline + 复用模型 + 移植 GPL 代码**。因为接受 GPL-3.0，原本要重写的检测后处理改为「移植 + 去 Qt 化」，省 2–3 周（清单见 §11）。

---

## 4. 总体架构

### 4.1 两进程 + 本地 socket

```
┌──────────────── GUI (PySide6) ────────────────┐
│ 项目 │ 运行 │ 校对(画布) │ 设置 │ 导出        │
│         命令(JSON) ↓        ↑ 事件 + 位图      │
└───────────────────────────────────────────────┘
        本地 socket (127.0.0.1, 随机端口 + token)
┌──────────────── engine (无 Qt) ───────────────┐
│ EngineServer: 任务队列 / 取消令牌 / 进度事件    │
│ PipelineService: 六阶段 + 断点 + 预算          │
│ ModelPool: 检测/OCR 常驻, 修复按需加载          │
│ Adapters: Detector / OCR / Inpainter / Translator │
└───────────────────────────────────────────────┘
        项目目录: project.json + mask/ + inpainted/ + result/ + assets/
```

用 socket 而不是 `Pipe`：GUI 崩溃后可重启并重连；将来可把 engine 放到别的机器。

### 4.2 分层

```
接口层  GUI(PySide6) │ CLI(同一命令集)
编排层  PipelineService（状态机/断点/取消/并发/预算）
阶段层  load→detect→ocr→translate→erase→render
适配层  四个 Protocol 注册表
领域层  Page·TextBlock·TextStyle·Bubble·ProjectStore
基础层  图像IO(CBZ/目录) · 缓存 · 日志 · 配置 · 字体
```

`core/ domain/ adapters/ render/ engine/` 中禁止出现 `PySide6`（CI 检查 import）。

### 4.3 目录

```
mangatl/
  core/     pipeline.py scheduler.py events.py cancel.py
  domain/   page.py block.py style.py project.py store.py
  adapters/ detectors/ ocr/ inpaint/ translators/ registry.py
  render/   layout_h.py layout_v.py linebreak.py raster.py fonts.py measure.py
  io/       cbz.py folder.py cache.py
  engine/   server.py protocol.py model_pool.py
  gui/      app.py mainwindow.py panels/ canvas/ commands.py
  cli/      main.py
  tests/    fixtures/pages/ golden/
```

### 4.4 并发

| 工作 | 位置 | 规则 |
|---|---|---|
| 推理 | engine | 全局串行；一次只驻留当前阶段所需模型 |
| 翻译 | engine 内 asyncio | 并发 2–3（8 GB 机器通常网络与显存都有限） |
| 渲染 | engine 线程池 | 按页并行 |
| GUI | 主线程 | 只换 pixmap，不做推理 |
| 取消 | 软（阶段边界）+ 硬（杀 engine 重启） |

---

## 5. 六阶段（要点）

### 5.1 载入
目录 / CBZ；EXIF 纠正；条漫长图按 1024 重叠切片 + provenance；坏图跳过。

### 5.2 检测
CTD 输出 `boxes / lines / text_mask`；后处理：行→块 → 过度合并拆分 → 散行合并 → 阅读顺序（竖排右→左）→ 稳定 ID；同时给 `ja/eng` 语言类别。
气泡安全区：MVP 用掩膜膨胀 + 邻域颜色一致性；M2 可选轻量气泡模型。

### 5.3 OCR
| 源 | 引擎 | 预处理 |
|---|---|---|
| 日（竖排） | manga-ocr | 行四边形透视矫正 → 旋转 90° → 高 48–64 px |
| 英/其他 | PP-OCRv5 | 透视矫正，保持横排 |
每块输出 `text / confidence / fg_rgb / bg_rgb / stroke_width`；低置信标 `needs_review`。
注音小行：MVP 并入主行并标记，避免当台词翻译。

### 5.4 翻译
OpenAI 兼容；整页批量 + JSON 契约（`blocks[{id,text}]`）；ID 校验 → 缺块补发 → 逐块单发。
上下文：上一页摘要 + 术语表 + 角色名；预算内滑动窗口。
防加戏：只译不解释、不增删；长度异常 ±40% 重试一次。
缓存：`hash(model+prompt_ver+glossary_ver+src)`；短句（“！”“……”）直接命中。
成本：每次运行出 token/费用报告；可设硬上限。

### 5.5 抹字
掩膜 = 文字掩膜（优先）+ 块矩形（保底），膨胀 `0.06×字高`（≥2 px）。
**纯色快路径**：块内背景标准差低 → 中位色填充，跳过模型（漫画中占 50–70%）。
慢路径：LaMa 1024（块裁切 + 32 px 上下文）；8 GB 下可常驻；OOM 降 512 → CPU。
自检：抹后二次检测，仍有响应 → 二次膨胀重抹。
SFX：默认保留不擦（可配置音译/意译）。

### 5.6 排版
两个策略共享「测量 → 适配 → 断行 → 绘制」四步：

- 横排：按词/字断行，行高 = `em × line_spacing`，居中/左/右。
- **竖排：见 §7 完整规格**（列、禁则、标点旋转、纵中横）。
- 字号：原文估计 ×1.15 起，二分下降，下限 0.6×原文；仍放不下 → 缩字距 → 加宽 3% → 标 `needs_review`。
- 字体：思源黑体/思源宋体/霞鹜文楷（OFL），按“黑体/宋体/手写”三分类；缺字回退。
- 描边：由 fg/bg 色差估计宽度；先描边后填充。
- 角度：整块渲染到透明层再旋转。

---

## 6. 语言对特化

| 维度 | 日→中 | 英→中 |
|---|---|---|
| 检测 | CTD `ja` | CTD `eng` |
| OCR | manga-ocr（竖排旋转） | PP-OCRv5 en |
| 输出方向 | **默认跟随原文**（竖排→竖排，可强制横排） | 横排 |
| 断行 | 按字 + 禁则 | 按词断，再按字排 |
| 标点 | `「」`→竖排引号/横排“”；`…`→`……`；`。、` 右上定位 | `"`→“”，`!?`→全角 |
| 难点 | 竖排标点、长音、注音、敬称 | 全大写强调、椭圆气泡居中 |
| 提示词 | 敬称一致、语气口语化、`さん` 不逐字译 | 全大写→“！”/加粗；`...`→`……` |
| SFX | 默认保留 | 默认保留 |

---

## 7. 竖排排版规格（v1，本项目重点）

> 目标：中文竖排读起来要像中文竖排，而不是“把横排文字转 90 度”。

### 7.1 方向与坐标
- `src_is_vertical`：行四边形长宽比 > 1.2 且多行 → 竖排；否则横排。目标方向默认 = 源方向。
- 块局部坐标系：原点左上，**列沿 −x（右→左）**，字符沿 +y。
- 每个字符占一个 `em × em` 方格；列推进 `adv = em + letter_spacing`；列间 `gap = em × line_spacing`。

### 7.2 适配（先算列数，再算字号）
```
n_rows = floor(area_h / em)
n_cols_max = floor((area_w + gap) / (adv + gap))
需要: ceil(N / n_rows) ≤ n_cols_max   （N = 字符数，含标点）
```
不满足 → `em` 二分下降（下限 0.6×原字号）→ 缩 `letter_spacing` 至 −0.05em → 仍不行标 `needs_review` 并允许溢出 3%。

### 7.3 断列与禁则
- 从右往左逐列填充，**列首禁则**：`。，、；：？！）」』】〕〉》` 以及 `ー`、`ぁぃぅぇぉっゃゅょ` 小字假名不得出现在列首。
- 命中禁则时优先「追い込み」（把上一字符挤进本列，若本列未满）→ 否则「追い出し」（把违规字符推到下一列首并整体后移一列）。
- 列尾禁则：`（「『【〔〈《` 不得留在列尾。
- 连续 ASCII 单词/数字不拆（整体换列），超长串才按字符拆。

### 7.4 标点与特殊字形
| 字符 | 处理 |
|---|---|
| `。、` | 画在格子**右上**（偏移 `+0.40em, −0.30em`），不居中 |
| `「」『』（）［］` | 旋转 90°（开括号在列首侧、闭括号在列尾侧） |
| `…`、`—`、`?!` | 整字旋转 90°（视觉为纵向） |
| `ー`（长音） | 旋转 90°，且禁止列首 |
| 全角空格 | 占一格，不绘制 |
| 数字/拉丁 1–2 字符 | **纵中横**：同一格内左右并排，各 0.5em 宽 |
| 数字/拉丁 ≥3 字符 | 整段旋转 90°（回転） |

### 7.5 对齐与行内位置
- 竖排对齐：默认顶部（`align=top`），可配居中/底部；最后列（最左）自然为最短列。
- 字符在格内 `anchor='mm'` 居中，标点按上表偏移。
- 与原文位置对齐：块内第一列右边缘 = 原文最右行右边缘；列推进按 `adv + gap`，误差 ≤ 0.5em。

### 7.6 渲染细节
- 逐字绘制；旋转字符先画到 `2em×2em` 透明层再旋转 90°，避免旋转后的抗锯齿错位。
- **先描边后旋转**：保证描边宽度视觉一致；旋转层的描边不可二次缩放。
- 透明底合成时用整数像素对齐，避免半像素糊边。
- 竖排不做字距均摊（`text-justify`），保持自然节奏。

### 7.7 竖排验收用例（回归集必备）
1. 纯竖排、右→左、单列气泡。
2. 竖排多列、列数刚好/不足/溢出各一。
3. 含 `「」`、`…`、`ー`、`！？` 的连续标点。
4. 含 `12`、`OK`、`2026` 的纵中横/回転。
5. 中文长句（15 字以上）需要折列。
6. 原文竖排但译文很短（单列）。
7. 竖排 + 角度 15°。
8. 繁体竖排（`「」` 与 `。、` 的定位差异）。

---

## 8. GUI 设计

### 8.1 五个页面

| 页面 | 关键交互 |
|---|---|
| 项目 | 打开目录/CBZ、最近项目、拖拽入队 |
| 运行 | 阶段进度、逐页表（状态/耗时/费用）、取消、重试失败页、ETA |
| 校对 | 画布 + 块列表 + 译文编辑 + 样式 + 对比（详见 8.2） |
| 设置 | 模型/设备、翻译 profile、字体、术语表、输出 |
| 导出 | 格式（CBZ/目录）、命名、质量、是否附对照图 |

### 8.2 画布
- `QGraphicsView` + `QGraphicsPixmapItem`；滚轮缩放、空格平移、`Ctrl+0` 适配。
- `Tab` 切换渲染结果/原图；半透明叠加看擦除效果。
- 覆盖层（块框、行四边形、编号、`needs_review` 高亮）只在 GUI 画，不进导出。
- **WYSIWYG**：画布像素 = 导出像素；改完发 `render_page` 取回新位图，不做第二套预览。
- 单页重渲染目标 < 300 ms；超大页降采样预览、导出用全分辨率。

### 8.3 校对流（180 页目标 15 分钟）
1. 跑完自动进入逐页校对，只停在 `needs_review` 页。
2. 块列表按阅读顺序（竖排右→左）；`Tab` 下一块、`Enter` 聚焦译文。
3. 译文框下方显示原文与置信度，低置信标黄。
4. `Ctrl+Enter` 重渲染；`Ctrl+Shift+Enter` 重渲染并跳下一待校块。
5. 顶部进度“已校对 42/180，待复核 7”。
6. 编辑进 `QUndoStack`，粒度单块/单页。

### 8.4 状态同步
- 唯一真相在 engine 的 `project.json`；GUI 持有视图模型 + 自己的撤销栈。
- 编辑 → `apply_edit(id, patch)` → engine 校验 → 原子落盘 → 事件回传 → GUI 更新。
- 崩溃恢复：读 `project.json` + `stage` 位掩码，提示“3 页未完成，继续？”。

### 8.5 快捷键
`A/D` 翻页、`Tab` 下一块、`Ctrl+Enter` 重渲染、`Ctrl+Z/Y` 撤销、`0–9` 透明度、`Space` 看原图、`Ctrl+F/G` 查找。

---

## 9. 数据契约

```json
{
  "schema": 3,
  "source": {"kind": "cbz", "path": "vol1.cbz", "pages": 180},
  "config": {"src": "ja", "tgt": "zh-CN", "keep_vertical": true,
             "models": {"det": "ctd@1", "ocr": "manga-ocr@base", "inpaint": "lama@1024"}},
  "pages": {
    "001.jpg": {
      "size": [1600, 2400],
      "stage": {"detect": 1, "ocr": 1, "translate": 1, "erase": 0, "render": 0},
      "blocks": [{
        "id": 0, "bbox": [820,120,1180,460], "lines": [[[..]]], "vertical": true,
        "text": "おはよう", "translation": "早上好", "confidence": 0.97,
        "style": {"font": "sans", "size": 34, "fg": [20,20,20], "bg": [250,250,250],
                  "stroke": 2.0, "line_spacing": 1.15, "align": "top",
                  "writing_mode": "vertical", "angle": 0},
        "erased": "lama", "reviewed": false, "needs_review": false
      }]
    }
  },
  "budget": {"tokens_in": 0, "tokens_out": 0, "cost": 0.0}
}
```

要点：阶段位掩码（断点）、`reviewed` 与 `needs_review` 分离、原子写、`assets/<sha256>`、`schema` 只补不覆盖。

---

## 10. 扩展点

| 注册表 | 契约 | 内置 |
|---|---|---|
| Detector | `detect(img) -> boxes, lines, mask` | ctd |
| OCR | `recognize(crops, lang) -> texts, conf` | manga-ocr, ppocr |
| Inpainter | `erase(img, mask, blocks) -> img` | lama, solid-fill |
| Translator | `translate(blocks, ctx) -> blocks` | openai-compatible |

装饰器注册 + 目录扫描；依赖缺失只降级该实现；**不用 AST 反射**（避免 BT 的“两份真相”）。

---

## 11. GPL-3.0 复用与合规

### 直接移植（去 Qt 化，保留版权头）
| 来源 | 文件 | 用途 |
|---|---|---|
| BallonsTranslator | `textlines_merge.py` | 行合并、四边形排序 |
| BallonsTranslator | `split_text_region.py` | 过度合并时按间隙切分 |
| BallonsTranslator | `textblock_mask.py`（`canny_flood`） | 行内文字掩膜细化 |
| BallonsTranslator | `imgproc_utils.py` | `rotate_polygons`/`union_area` |
| BallonsTranslator | `textblock.py::group_output / examine_textblk / merge_textlines` | 检测后处理核心 |
| manga-image-translator | 检测/OCR/修复推理封装 + 模型下载 | 适配层 |
| manga-image-translator | 文本后处理/断行工具 | 标点、断行 |

### 参考思路但重写
字号自适应、描边、气泡安全区、配置迁移惯例。

### 合规清单
- [ ] `LICENSE`=GPL-3.0；`NOTICE` 列移植来源；每个移植文件保留版权头。
- [ ] 提供完整对应源码。
- [ ] Qt/PySide6（LGPL-3.0）：动态链接、one-dir 打包（`.dll` 可替换）、附 LGPL 文本。
- [ ] 模型权重清单（名称/来源/许可/sha256）。
- [ ] 字体 OFL，保留版权与保留字体名。
- [ ] 不内置 Key；Key 存系统钥匙串（DPAPI / Keychain / libsecret）。

---

## 12. 质量难点

| 难点 | 对策 |
|---|---|
| 检测过度合并/漏检 | 三重拆分 + 掩膜密度兜底 + 接缝检查 |
| **竖排列首禁则** | 追い込み/追い出し + 8 条竖排回归用例 |
| **竖排标点定位** | `。、` 右上偏移；括号/长音旋转；回归图 diff |
| 中文断行 | pkuseg + 禁则 |
| 字号溢出 | 二分降字号 → 缩字距 → 加宽 3% → `needs_review` |
| 字体不符 | 三分类 + 手动覆盖；M3 接字体识别 |
| 抹字残留/过度 | 按字高膨胀 + 二次检测 + 只取文字连通域 |
| LLM 串块/加戏 | ID 校验 + 缺块补发 + 单块回退 + 长度重试 |
| 注音 | MVP 并入主行；M2 记录位置并小字渲染 |
| SFX | 默认不擦不译 |
| 条漫接缝 | 重叠切片 + 只合并贴边块（BT #1377 教训） |

---

## 13. 8 GB 显存档位与性能

### 13.1 模型档位（默认）
| 模型 | 精度 | 显存 | 常驻策略 |
|---|---|---|---|
| comic-text-detector | fp16 | ~0.8–1.2 GB | 常驻 |
| manga-ocr（日） | fp16 | ~0.8–1.2 GB | 常驻 |
| PP-OCRv5（英，ONNX） | fp16/int8 | ~0.3–0.5 GB | 常驻 |
| LaMa 1024 | fp16 | ~2.5–3.5 GB | 按需，页批次结束后可卸 |
| 峰值 | | **4.5–5.5 GB** | 8 GB 有余量 |

策略：
- 检测+OCR 常驻（约 2 GB），抹字前加载 LaMa，**一个批次（如 20 页）结束后卸载**，避免长时间占用。
- 输入长边 1280（检测）/1536（修复可到 2048 但要监控）；`torch.cuda.amp.autocast` + `channels_last`。
- OOM 兜底：捕获 `OutOfMemoryError` → 降分辨率/降 tile → 最后退 CPU（慢但能跑完）。
- `PYTORCH_CUDA_ALLOC_CONF=expandable_segments:True` 减少碎片。

### 13.2 时间预算（单页 1600×2400）
| 阶段 | 时间 |
|---|---|
| 检测 | 0.25–0.4 s |
| OCR | 0.6–1.5 s |
| 翻译 | 2–6 s（网络） |
| 抹字 | 1–2 s（快路径 <0.3 s） |
| 渲染 | 0.1–0.2 s |
| 合计 | **6–10 s**（180 页 ≈ 20–30 min） |

### 13.3 成本
单页 400–900 输入 / 300–700 输出 token；一本 180 页约几毛到几块（随模型档位）。内置预算上限与实时统计。

### 13.4 单本 180 页带来的简化
- 不需要 SQLite/任务队列服务；`project.json` + 阶段位掩码即可。
- 断点恢复 = 读 JSON + 跳过已完成页；不做分布式锁。
- 导出前只校验“未校对页”数量，不做版本管理。
- 内存上限：同时只持 1 页原图 + 1 页渲染图 + 相邻页预取（≤ 3 页）。

---

## 14. 里程碑

| 阶段 | 周期 | 交付 | 验收 |
|---|---|---|---|
| **M0 Spike** | 3–5 天 | 10 页（含 4 页竖排）脚本级跑通 | 确认抹字与竖排是主要瓶颈 |
| **M1 核心** | 2 周 | core + engine + CLI + 项目 JSON + 断点 + 纯色快路径 | 50 页无人值守；单页 < 10 s |
| **M2 排版+校对骨架** | 2–3 周 | 横/竖两套布局、禁则、标点、纵中横；GUI 只读画布 + 改译 + 重渲染 | 竖排 8 条回归全绿；抽检可读 ≥ 90% |
| **M3 产品化** | 2–4 周 | 五页 GUI、术语表、费用面板、CBZ 导出、打包、首启下载模型 | 非技术用户可完成全流程 |

竖排从 M2 第一周就开始做，不要留到最后——它牵扯测量、断行、渲染三处。

---

## 15. 风险

| 风险 | 处置 |
|---|---|
| 8 GB 显存 OOM | 档位表 + 自动降级 + 批次卸载 + 纯色快路径 |
| 竖排细节“能看但不像中文竖排” | 8 条回归用例 + golden 图 diff（每次改排版必跑） |
| GPL 传染 | 已接受；按 §11 清单执行 |
| Qt LGPL 合规 | one-dir、动态链接、附许可证 |
| 模型 1–2 GB 下载 | 分阶段按需 + 断点续传 + 镜像 |
| LLM 不稳定 | JSON 契约 + ID 校验 + 单块回退 |
| engine 崩溃 | GUI 检测断线 → 重启 → 断点续跑 |
| 范围蔓延 | 只做翻译与嵌字，不做绘图/改图 |

---

## 16. 与 BallonsTranslator 的取舍

**借**：阶段位掩码、纯色快路径、配置加载修补、六个坐标空间契约、资产安全、行合并/切分算法。

**躲**：流水线寄生 UI（headless 仍建 MainWindow）、AST 懒加载双份真相、`shared`/`pcfg` 全局单例、类属性当实例状态、QThread+QMutex 承载推理、100 KB 上帝模块（本方案单文件 ≤ 800 行，CI 检查）。

---

## 17. 待确认

1. **SFX 默认“保留不擦”**是否符合预期？
2. 竖排译文里**数字/英文**的处理：默认纵中横（≤2 字符）+ 回転（≥3 字符），可接受吗？
3. GUI 界面语言：只做简体中文，还是中英双语？
4. 是否需要「保留原文对照页」（输出时每页附原图）？

## 18. 分发形态：只做便携版（解压即用）

**结论：一个 zip，解压到任意目录，双击 `MangaTL.exe` 即用。无安装程序、无注册表、无管理员权限、无卸载残留。**

### 18.1 目录与包型

```
MangaTL-portable/
  MangaTL.exe
  _internal/             # Python / Qt / torch / 依赖（不要改）
  data/                  # models / fonts / config.json / logs
  projects/              # 默认项目目录
  LICENSE  NOTICE
  source/                # 本项目完整源码（GPL 合规，几 MB）
  使用说明.txt
```

| 包 | 内容 | 压缩后 | 解压后 | 适用 |
|---|---|---|---|---|
| `full` | 程序 + 全部模型 | 2.4–2.8 GB | 5–6 GB | **默认发布**（便携的核心诉求是离线可用） |
| `lite` | 程序，模型首启下载 | 1.8–2.2 GB | 3.5–4 GB | 弱网 / 小 U 盘 |

- CUDA 版 torch 在无 N 卡机器上会自动退 CPU 运行，**不必单独发 CPU 包**。
- 格式：主发 `.zip`（资源管理器双击即可解压，不依赖 7-Zip）；同内容另附 `.7z` 可再小约 20%。

### 18.2 便携版的 6 个特殊约束

1. **可写性**：启动探测 `data/` 是否可写；不可写（Program Files、`C:\` 根、只读 U 盘）→ 弹窗要求换目录，**不静默回退到 AppData**（否则就不叫便携版）。
2. **单实例按目录**：用 `data/.lock` 而不是全局互斥体，允许新旧两份副本同时运行对比。
3. **路径**：中文/空格/深层目录都要支持，文件 IO 用 `\\?\` 兜底；所有路径相对程序目录，U 盘盘符变化不影响。
4. **硬件自适应**：每次启动重新探测 GPU，配置里 `device=auto`（同一 U 盘插到不同机器）。
5. **API Key（便携版最容易翻车的点）**：DPAPI 绑定「当前机器 + 当前用户」，换台电脑就解不开。三选一：
   - 默认：**不保存**，每次会话输入；
   - 可选：设主密码，Argon2id + ChaCha20-Poly1305 加密存 `data/secrets.enc`（可跨机带走）；
   - 不提供明文保存。
6. **更新**：无自更新。新版解压到新目录，或覆盖 `MangaTL.exe` + `_internal/`，保留 `data/` 即继承配置与项目。

### 18.3 双击后的启动流程

```
双击 MangaTL.exe
  → 取 data/.lock（已在运行则激活已有窗口）
  → 0.3 s 出 Splash
  → 检查 data/ 可写 → 不可写则提示并退出
  → 校验模型清单：缺失 → 下载页（镜像 / 断点续传 / 导入离线模型包）
  → 起 engine 子进程（同一个 exe + 隐藏参数 --engine），socket 握手 + token
  → 探测 GPU/显存 → 档位（≥8 GB：LaMa 1024；4–6 GB：768；无 GPU：CPU）
  → 主窗口出现，模型后台预热（不阻塞 UI）
```

### 18.4 工程要点（Windows 上真会踩的坑）

- **单 exe 双角色**：GUI 与 engine 共用同一个二进制（`--engine` 自派发），避免两套 PyInstaller 包重复 2.5 GB 依赖。
- **`--noconsole` + 日志重定向**：engine 的 stdout/stderr 必须写 `data/logs/engine.log`；Windows 上父进程不读管道会把子进程写阻塞（死锁），这不是理论问题。
- **DLL 顺序**：先加载 `vcruntime140/msvcp140` 再加载 Qt（BallonsTranslator 的 `preload_msvc_runtime` 就是为这个）；cudnn/cublas 用 `os.add_dll_directory` 显式加目录。
- **体积裁剪**：排除 `torch/include`、`torch/test`、`*.lib`、`tkinter`、`matplotlib`；**不要**用 UPX 压 cudnn/cublas（会随机崩溃）。
- **CI**：`windows-latest` 构建 + smoke test（启动 splash + 跑 1 页），产出 `MangaTL-portable-{full,lite}-vX.Y.Z.zip` 与 `.sha256`。
- **SmartScreen**：未签名 exe 首次运行会提示「更多信息 → 仍要运行」，写进 `使用说明.txt`；后续再考虑签名。

### 18.5 合规（便携版反而更好做）

- **源码随包**：`source/` 放本项目源码 + `NOTICE` 列移植来源，直接满足 GPLv3 的 accompany 要求（无需书面承诺）。
- Qt/PySide6（LGPL-3.0）：`onedir` 保留可替换的 Qt DLL、附 LGPL 文本、不静态链接。
- 模型与字体：`data/models/LICENSES.txt` 列名称/来源/许可/sha256。

---

### 附：M0 执行清单（3–5 天）

1. 样本 10 页：**竖排日漫 4 页**（单列/多列/带标点/带数字）、横排日漫 2 页、彩色条漫 2 页、英文 2 页。
2. 先串「检测 → OCR → 抹字」，只评估掩膜质量与竖排识别率。
3. 用固定译文单独调竖排布局（§7 的 8 条用例），把 LLM 完全隔离。
4. 接一个 provider 跑端到端，记录耗时/token/失败模式。
5. 产出：翻车清单 + 最终模型档位 + 竖排回归 golden 图。
