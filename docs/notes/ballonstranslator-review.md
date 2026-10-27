# BallonsTranslator 架构评审

- 评审对象：`dmMaze/BallonsTranslator`（PyQt6 漫画/条漫机翻工具），`dev` 分支，代码对应 `v1.5.20` 之后的提交 `eeaddaa`（2026-10-23 合入 PR #1377）
- 代码来源：GitHub 直连在本机不可用（`github.com` / `raw.githubusercontent.com` / `cdn.jsdelivr.net` 均超时），改用 Gitee 镜像 `gitee.com/mirrors/BallonsTranslator` 读取 `dev` 分支原文；另参考仓库 `AGENTS.md`、`README.md`、`doc/ui/text_engine.md` 与 GitHub API 的文件树/提交信息
- 已逐行阅读：`launch.py`、`modules/base.py`、`modules/lazy_registry.py`、`utils/registry.py`、`utils/proj_imgtrans.py`、`utils/textblock.py`、`modules/translators/base.py`、`ui/io_thread.py`；另通读 `AGENTS.md` 与 `doc/ui/text_engine.md` 两份架构契约
- 未逐行阅读（按结构、文档与接口推断）：`ui/mainwindow.py`(121 KB)、`ui/text_engine/effects/renderer.py`(192 KB)、`ui/module_manager.py`(109 KB)、`ui/run_pipeline_dialog.py`(63 KB) 等；文末列出这些不确定项

---

## 0. 一句话结论

这是一套**工程纪律明显高于同类的个人项目**：注册表 + 懒加载、模型生命周期、配置向后兼容、Qt 线程约束都有清晰约定（`AGENTS.md` 几乎是一份小型架构规范），核心模块也带 doctest；`ui/text_engine` 更有一份罕见的、把坐标空间与失效链写死的契约文档。
但**领域编排仍寄生在 Qt UI 层**（headless 只是“无窗 GUI”），`text_engine` 与主窗口已长成 100 KB 级的“上帝模块”，且存在**类级可变参数被实例配置就地改写**这类会随项目规模放大的隐患。总体评价：**可维护性中上，分层不合格，扩展点是干净的，重构窗口正在关闭**。

---

## 1. 项目形态与技术栈

| 维度 | 现状 |
|---|---|
| 语言/框架 | Python（README 要求 ≤3.12）、Qt 抽象层 `qtpy`（默认 PyQt6，兼容 PySide6/PyQt5/PySide2） |
| 深度学习 | PyTorch **可选**（`torch_available()` / `require_torch()`），CUDA / XPU / MPS / DirectML(`privateuseone`) / ROCm(ZLUDA) 多后端 |
| 领域库 | OpenCV、shapely、numpy、python-docx、piexif、可选 PaddleOCR / CTranslate2 / onnxruntime / llama.cpp 类运行时 |
| 分发 | 源码运行 + 免配置 zip + 启动期自举（`ensure_core_requirements`、`torch_install_helper`、`package_installer`、`updater`） |
| 版本 | `v1.5.20`（2026-10-18），仍在活跃开发（5.2k stars，237 open issues） |

运行形态有两种，但**共用同一套对象图**：

```
python -m ballontranslator [--headless] [--exec_dirs ...] [--ldpi ...] [--proj-dir ...]
```

关键事实（`launch.py::main`）：**headless 模式并不是另一条代码路径**，它只是把 Qt 平台插件换成 `-platform offscreen`，然后照样 `MainWindow(app, config, ...)`，最后不 `show()`。这一点决定了下面第 6 节最重要的架构判断。

---

## 2. 全局结构

```
                          ┌──────────────────────────┐
                          │ launch.py                │  CLI 解析 / 自举装依赖 /
                          │  (16 KB)                 │  Qt 初始化 / 字体注册 / 锁
                          └────────────┬─────────────┘
                                       │ 构造（headless 也构造）
                          ┌────────────▼─────────────┐
                          │ ui/mainwindow.py (121 KB)│  ← 事实上的应用服务层
                          │  RunPipelineDialog(63 KB)│     四阶段流程编排
                          └───┬───────────┬──────────┘
             ┌────────────────┘           └───────────────┐
   ┌─────────▼──────────┐                        ┌─────────▼──────────┐
   │ utils/proj_imgtrans│  项目状态/持久化        │ modules/*          │ 检测/OCR/翻译/修复
   │  (52 KB)           │  pages: {img: [TextBlock]} │  base / lazy_registry │
   └─────────┬──────────┘  image_info: finish_code  └─────────┬──────────┘
             │                                              │
   ┌─────────▼──────────┐                        ┌─────────▼──────────┐
   │ utils/textblock.py │  领域模型（43 KB）      │ utils/registry.py  │ Registry + ModuleSpec
   │  + fontformat      │                        │  (mmcv 血统)        │
   │  + text_effects    │                        └────────────────────┘
   └─────────┬──────────┘
   ┌─────────▼──────────────────────────────────────────────┐
   │ ui/text_engine/  渲染与排版子系统                        │
   │  annotations 102K · renderer 192K · cards 121K          │
   │  effects/* (filters, paint, panel, shadow)              │
   │  editing/* (commands, manager 58K, widgets 43K)         │
   │  formatting/* · layout · font_family                    │
   └────────────────────────────────────────────────────────┘

  全局单例：utils/shared.py（shared.DEBUG / LDPI / FONT_REGISTRY…）
            utils/config.py 的 pcfg（模块参数、翻译前后处理规则、嵌字开关…）
```

数据流（一键机翻）：`图片 → 检测(TextBlock 雏形+lines) → OCR(填充 text / 颜色 / 字体提示) → 翻译(textblk.translation) → 修复(mask→inpainted) → 排版+渲染 → result/`，每页完成后写 `image_info[page]['finish_code']`（`RunStatus` 位掩码），支持断点续跑与“只重跑某阶段”。

---

## 3. 分层拆解

### 3.1 启动层 `launch.py`
职责异常集中，但每段都有明确理由，属于“可读的意大利面”：

- `disable_bundled_windows_user_site()`：打包版 Python 运行时要屏蔽用户 site-packages，否则会串环境。
- `preload_msvc_runtime()`：**在 Qt 之前**加载 `msvcp140.dll`。注释写得很清楚——PyQt6 会用 `AddDllDirectory` 注册自带 Qt/bin，导致后续 PyTorch 解析到旧版 MSVC 运行库。这是踩过坑的痕迹，也是“桌面 + ML 运行时”这类项目的典型伤疤。
- `application_arguments()`：按 Qt 版本与字体后端拼 `-platform windows:fontengine=gdi|freetype`。
- 字体：先快照系统字体族，再注册 `fonts/` 下随包字体，构建 `shared.FONT_REGISTRY`（`utils/font_registry.py`），并给 Qt 不认的字体族登记别名（`ui/text_engine/font_family.py`）。
- 启动即自愈依赖：`ensure_core_requirements(...)` 返回 True 就 `restart()`（`os.execv`）。
- 全局锁：`setup_locks()` 把 `QMutex` 塞进 `utils/lock.py` 的 `RUNTIME_LOCKS`，供模型加载串行化。

评价：**这里把“环境即程序”做到了极致**（自装 torch、自选镜像、自更新），好处是小白可用，代价是启动路径长、失败面大、难以在容器/CI 中稳定复现。

### 3.2 领域状态层 `ProjImgTrans`（`utils/proj_imgtrans.py`）
- 状态：`pages: Dict[图片名, List[TextBlock]]` + `_pagename2idx/_idx2pagename` + `_image_info`（每页 `finish_code`、宽高、`translation_target`、可选的 `llm_visual_summary`）+ 项目级 `llm_compact_memory`。
- 磁盘布局：`<proj>/imgtrans_<dir>.json`（主状态）+ `mask/*.png` + `inpainted/*.png` + `result/*` + `assets/<sha256>.<ext>`。
- 迁移策略很克制：`normalize_textblock_effect_payload()` 把老的扁平字段（`opacity`/`stroke_width`/`bg_colors`…）折进 `FontFormat.text_effects`；未知版本号只告警不阻塞；`text_layout_version` 处理竖排对齐语义变更。
- `import_raster_asset()`：内容寻址的不可变资产仓库，**带字节上限(32 MiB)/像素上限/解码上限(256 MiB)、同签名校验、临时文件+`os.replace` 原子落盘、`assets` 目录逃逸检查**。这块的安全意识明显高于项目平均水平，是全文最“工程化”的一段代码。

### 3.3 模块层：Registry + ModuleSpec + 懒加载
```
@register_translator('google')  ──┐
@register_OCR('mit48px')         ├─ 装饰器写入 Registry（值可以是 ModuleSpec 或类）
@register_inpainter('lama_...')  │
@register_textdetectors('ctd') ──┘
```
- `utils/registry.py`：**mmcv Registry 的裁剪版**，新增 `ModuleSpec`（静态元数据：key/import_path/class_name/params/languages/依赖…）、`register_lazy_module()`、`resolve_module()`、`get_spec()`；`resolve()` 时才 `importlib.import_module`。
- `modules/lazy_registry.py`（33 KB）是整套设计里最有意思、也最危险的一块：**用 AST 而不是 import 来产出模块元数据**。
  - `_scan_file()` 解析 `@register_*('key')` 装饰器与类体里的 `params` / `download_file_list` / `dependencies` / `lang_map`；
  - `SafeEval` 是一个白名单解释器，支持常量/列表/字典/比较/`DEVICE_SELECTOR()`/`list(dict.keys())`/`os.path.join` 等极小子集，无法求值就返回 `UNKNOWN`；
  - 动机写在文件头：“builds registry metadata from AST so startup never imports module code”，即**启动不 import torch**，让 UI 秒开、让“没装 paddle”的用户仍能在下拉框里看到并选择（选中后逐级报缺失依赖）。
- `BaseModule`：`params`（带 `value`/`data_type`/`options` 的元数据字典）、`_load_model_keys`、`load_model()`（`QMutex` 串行）、`unload_model()`（含第三方 `unload_model()` 不接受 `empty_cache` 的兼容分支）、`all_model_loaded()`、`__del__` 兜底释放。

### 3.4 翻译子系统
`BaseTranslator` 的契约很薄，因此贡献者门槛低（README 也这么宣传）：
```
_setup_translator()  # 填 lang_map、建客户端
_translate(list[str]) -> list[str]
```
外层 `translate()` 负责：空文本短路、按需加载模型、`concate_text` + `TranslateContext.Page` 决定是否拼接、用 `textblk_break='\n##\n'` 拆分并校验条数、`postprocess_translation_text()` 固定顺序（繁简转换 → 全文模式下的 normalize/substitute/letter_case）。
`translate_textblk_lst()` 里有一段“选中块是否等于整页”的判定，用来决定是否把本次结果提交进 LLM 上下文窗口——这是为 LLM 场景长出来的、明显不属于基类语义的参数（`project`/`page_key`/`commit_history_window`），作者用 docstring 明确“基础翻译器忽略这些关键字”。

### 3.5 渲染排版子系统 `ui/text_engine/`
这是全项目**设计最自觉**的子系统，`doc/ui/text_engine.md` 把它写成了一份真正的架构契约，核心是一条单向装配链：

```
TextBlock + FontFormat               持久化状态（项目 JSON）
  → TextBlkItem + QTextDocument      运行期文本/编辑模型（Qt 富文本）
  → SceneTextLayout                  字形整形 + 放置（横排/竖排两套）
  → TextEffectRenderer               带 padding 的源图表面 + 效果合成
  → TextItemGeometryController       边界、坐标映射、交互命中
  → QGraphicsScene                   交互 / 视图 / 导出
```

文档还明确规定了几条“不可越界”的契约，这些正好解释了代码为什么长成这样：

- **持久化边界**：只有 `TextBlock`/`FontFormat` 进项目 JSON；`QTextDocument`、光标、IME、layout 记录、pixmap、cache 都是派生状态，永不落盘。
- **坐标系显式化**：project/page、item-local logical、item-local source（含效果 padding）、item-local visual、parent/scene、device 六个空间，必须经 `geometry.py`/`transforms/` 映射，“不允许只改一个消费者”。
- **失效链单一归属**：文本变更→layout；度量/书写模式→layout；效果栈→renderer；效果外扩→geometry；视觉变换→geometry。刷新“发布一个 settled generation”，缓存必须有界可释放。
- **富文本是 `QTextDocument` 的扩展层而非 CSS 引擎**：`annotations.py` 保留 Qt 表达不了的语义（`text-emphasis`、`text-combine-upright` 纵中横、ruby、字距/行距精确值），用 `data-btrans-*` 承载行为型数据，并要求双绑定往返一致。
- **编辑/撤销**：`QTextDocument` 拥有内容历史，`TextEditCommand`/`TextItemEditCommand` 桥接画布；一次逻辑操作只产生一个用户可见命令，撤销不得递归产生命令；`Canvas` 用 `QUndoStack` 的 clean marker 记账，且“合并进旧命令”要保守地让保存标记失效。UTF-16 单位、IME preedit 事务性都有明确约束。

按文件看：`annotations.py`(102 KB) = 富文本/注解模型，`effects/renderer.py`(192 KB) = 合成与栅格边界，`effects/cards.py`(121 KB) = 特效卡片 UI，`editing/manager.py`(58 KB) + `commands.py`(32 KB) = 命令栈，`effects/filters/` = 滤镜注册表（bloom/glitch/grain/noise/gaussian…），`formatting/`、`layout*.py`、`geometry.py`、`transforms/` 各司其职。

评价：**职责划分是清楚的，问题在于“单文件承载了过多协作细节”**——renderer 一个文件要同时处理 padding 计算、表面分配、效果合成顺序、缓存与预览，所以膨胀到 192 KB；这不是“没有设计”，而是“设计没有继续往下切”。

### 3.6 UI 层
`mainwindow.py`(121 KB) + `module_manager.py`(109 KB) + `run_pipeline_dialog.py`(63 KB) 承担了：菜单/工具栏、项目打开与页切换、模块参数面板生成、运行队列与进度、撤销重做接线、LLM 上下文编辑器、OCR/翻译/修复的“选中区域”操作。
`ui/io_thread.py` 提供 `ThreadBase`、`ImgSaveThread`（写盘队列）、`ImgTransProjFileIOThread`、`ExportDocThread`/`ImportDocThread`、`MergeThread`（对指定 JSON 的若干页做竖/横/先竖后横的框合并，然后整体回写该 JSON）。

---

## 4. 四条关键机制（细节）

### A. 懒加载：启动不 import torch
`init_module_registries()` → `init_lazy_module_registries()` → 对 `modules/{translators,textdetector,inpaint,ocr}` 及 `custom_modules/` 逐文件 `_scan_file()`，产出 `ModuleSpec` 注册进 Registry。
设计收益非常具体：`DEVICE_SELECTOR()` 在 AST 阶段被替换成 `_device_selector()`，用 `importlib.metadata.version('torch')` + `torch.__version__` 的本地版本后缀（`+cu121`/`+rocm`/`+xpu`）+ 驱动探测来推断设备选项，**全程不 import torch**。
代价：`params` 现在有“两份真相”——源码里的类属性，和 AST 扫描出的 spec；两者一旦漂移，UI 下拉框就会与真实行为不一致。作者显然意识到了，写了 `validate_lazy_module_specs()` 与 `metadata_warnings`，但校验发生在扫描期，缺少“AST 结果 vs 实际实例化后 params”的一致性测试。

### B. 模型生命周期
```
load_model()  → aquire_model_loading_lock() → _load_model() → release
unload_model(empty_cache) → 对 _load_model_keys 中的属性逐个 unload/setattr(None)
```
- 锁是 `QMutex`（Qt 原语，本身不依赖事件循环），但模块层的加载路径由此隐含“Qt 已初始化”这一前提——这也是 headless 必须照样建 `QApplication` 的原因之一。
- `low_vram_mode` 从 `params` 里读字符串键 `'low vram mode'`（带空格），与其它地方 `'low_vram_mode'` 风格不统一，属于历史包袱。
- `soft_empty_cache()` 除了 `torch.cuda.empty_cache()`，还在 posix 上 `malloc_trim(0)`，并为 cuda/xpu/mps 分别处理——细节到位。

### C. 参数体系
`params` 的形态是：
```python
{'device': {'type': 'selector', 'options': [...], 'value': 'cuda', 'data_type': str},
 'inpaint_size': {'type': 'selector', 'options': [512,1024,2048], 'value': 1536}}
```
`patch_module_params(cfg, defaults)` 负责：丢弃未知键、补齐新键、按 `data_type` 强转、类型不符则回落默认值、把键顺序对齐默认值、打 `__param_patched` 标记。`merge_config_module_params()` 在加载期对每个模块跑一遍，并对 `device` 选择器做“把当前值补进 options”的修复（老配置里存了 `privateuseone:0` 但 options 为空的情况）。
这套“**配置即持久化状态、加载时修补**”的做法与 `AGENTS.md` 的“被动加载只警告、不覆盖、给新字段默认值”完全一致，是整个项目最自洽的部分。

### D. 项目持久化与向后兼容
- 原子写：`proj_path.tmp` → `os.replace`；可选 `.backup`。
- 页与文件解耦：JSON 里的页可能已不在磁盘（`not_found_pages`），磁盘新增页也会被补进来（`new_pages`）。
- Word 往返：`dump_doc()` 把每个 TextBlock 的 `vars()` 序列化进裁剪图的 **JPEG EXIF UserComment**（`piexif`），`load_doc()` 再用正则扫 docx XML、读 EXIF 还原。思路巧妙（Word 里图片+表格天然对齐），但**对图片重编码/压缩极敏感**，且 `re.findall(r'<w:tbl>(.*?)</w:tbl>', ...)` 这种 XML 正则解析属于典型脆弱点。

---

## 5. 架构优点（有据可查）

1. **扩展点收敛得好**：新增翻译器/OCR/修复器/检测器只需一个装饰器 + `params`，`custom_modules/` 支持第三方投放（`_is_custom_module_file()` 对自定义模块的错误是 warning 而非 crash）。
2. **启动性能被当成需求对待**：`torch` 可选、AST 懒注册、`DEVICE_SELECTOR` 免 import，直接换来“没装 GPU 库也能开界面”。
3. **向后兼容是制度化的**：`patch_module_params`、`normalize_textblock_effect_payload`、`text_layout_version`、`LLM_VISUAL_SUMMARY_VERSION`、`.backup`、`warn_ignored_legacy_effects()`——不是零散补丁，而是统一的“迁移 + 告警”惯例。
4. **Qt 线程纪律明确**：`AGENTS.md` 用整节规定“长耗时不得在 GUI 线程”、“不要用 lambda 捕获 QObject”、“outside-click 过滤器的注册/注销时机”；`io_thread.py` 也确实是队列 + 信号。
5. **安全边界意识**：资产导入的字节/像素/解码三重上限与目录逃逸校验、`secret_store.py`（凭据不落明文 config）、`SafeEval` 不执行任意代码——这三件事在同规模项目里很少同时出现。
6. **doctest 密度高**：`BaseModule`、`ModuleSpec`、`patch_module_params`、`TextBlock.normalize_*`、`ProjImgTrans` 的资产/摘要校验都带可执行示例，等于“接口即测试”。
7. **有一个真正的“文字引擎契约”**：`doc/ui/text_engine.md` 把持久化边界、六个坐标空间、失效链归属、撤销/保存标记、UTF-16 与 IME 事务写成硬规则，并指定每个关注点的 owner 文件。多数同类项目根本没有这一层，而它是这个 192 KB 渲染器还能被维护下去的前提。

---

## 6. 问题清单（按影响排序）

### P1 —— 结构性，越晚越贵

**P1-1 领域编排寄生在 UI 层；headless 是“无窗 GUI”而非独立服务**
`launch.py` 在 headless 下仍然构造 `MainWindow`，只是不 `show()`。这意味着：批处理/服务器/CI 场景必须拉起完整 Qt widget 树（含字体库、主题、编辑器控件），任何“启动即崩”的 UI 问题都会扩散到 CLI；也意味着四阶段流水线无法在没有 Qt 的环境（容器、纯 Python 调用）里复用。
这是全套问题里**最值得先动**的一处：把 pipeline 抽成不依赖 Qt 的 `PipelineService`（输入：项目 + 模块注册表 + 配置；输出：进度事件），`MainWindow` 退化为它的订阅者。

**P1-2 五个 100 KB 级“上帝模块”**
`text_engine/effects/renderer.py` 192 KB、`ui/mainwindow.py` 121 KB、`text_engine/effects/cards.py` 121 KB、`ui/module_manager.py` 109 KB、`text_engine/annotations.py` 102 KB；另有 12 个 40–90 KB 的文件。
后果不是“难看”，而是：① 任何改动都要全量 `py_compile` 与手工回归；② 无法给渲染逻辑写不依赖 QWidget 的单测；③ 多人在同一文件上冲突。
`text_engine` 的职责表其实很清晰（见 3.5），所以 `renderer.py` 的 192 KB 不是“混了四件事”，而是**一个 owner 内部把 padding 计算、表面分配、效果合成、缓存与预览全摊平在一个文件里**。按“表面/合成/缓存/预览”四段切开，接口不变，回归面立刻下降。

**P1-3 类级 `params` 被实例配置就地改写（真实 bug 风险）**
`BaseModule.__init__`：
```python
standardize_module_params(self.params)          # 就地改类属性
params = patch_module_params(params, self.params, self)  # 又就地改类属性
self.params.update(params)                      # 把实例值写回类属性
```
`self.params` 是**类属性**，不是实例属性。于是：
- 同一模块的两个实例（多项目、预览实例、测试实例）会**共享并互相覆盖**参数；
- 类默认值被运行期配置污染，`get_spec().params_copy()` 拿到的“默认值”其实已被改过；
- 现有代码之所以没暴雷，是因为长期只有单例 + 单项目，属于“靠使用方式幸存的隐患”。
修法很轻：`__init__` 里 `self.params = deepcopy(type(self).params)` 后再 patch，`standardize_module_params` 也改成在副本上跑。

### P2 —— 设计债，会持续放慢迭代

**P2-1 “两份真相”：AST 元数据 vs 类属性**
`lazy_registry` 用白名单解释器复刻了 `params` 的求值语义。模块作者只要写了 `DEVICE_SELECTOR()` 之外的调用（比如 `make_params()`、`f-string`、`datetime`），AST 就会退化为 `UNKNOWN`，UI 下拉框空掉——而运行期一切正常。`validate_lazy_module_specs()` 只能事后告警。
建议：加一条“**扫描结果 vs 实例化后 params**”的一致性测试（对每个 registered key 断言 `spec.params == cls.params`），把漂移变成 CI 红灯而不是用户 bug。

**P2-2 全局可变单例 `shared` 与 `pcfg`**
`modules/translators/base.py` 直接 `from ...config import pcfg` 并在 `translate()` 里读 `pcfg.module.translate_context`、`pcfg.mt_sublist`；`shared` 里塞了 `DEBUG/LDPI/HEADLESS/FONT_REGISTRY/args` 等。
后果：模块层无法在“另一份配置”下实例化（也就无法做多语言并行、无法给 headless 传显式配置），单测必须改全局。建议引入最小 `ConfigProvider` 协议（或 contextvar），`MainWindow` 负责注入。

**P2-3 `TextBlock` 是上帝对象**
43 KB、约 40 个字段，同时承担：几何（`lines/xyxy/min_rect/angle/vec/norm` + `cv2.findHomography` 透视取区域）、样式（几乎所有属性都转发给 `fontformat`）、OCR 产物（`text`/`fg_colors`/`bg_colors`/`_detected_font_*`）、持久化迁移（`deprecated_attributes`）、渲染辅助（`text_alpha_mask`）。
`__post_init__` 里 `del self.deprecated_attributes`（删除字段）和 `__getattribute__` 拦截 `'pts'` 都是“补丁式演化”的症状。建议拆成 `TextGeometry` / `TextStyle`(已基本是 `FontFormat`) / `OcrResult` / `BlockCodec` 四块，`TextBlock` 只做组合。

**P2-4 Word 往返依赖 EXIF + 正则解析 docx**
见 4-D。建议：docx 内改为“隐藏表格列存 JSON”或独立 sidecar `.json`；解析用 `python-docx` 的 API/`lxml`，而不是 `re.findall(r'<w:tbl>...')`。

### P3 —— 可立刻修的具体问题

| 位置 | 问题 | 说明 |
|---|---|---|
| `utils/proj_imgtrans.py::load_from_dict` | `new_pages` 未重置 | 每次 `load()`/`load_from_json()`（失败回滚会再 load 一次）都会**累加**新页名单，重载后出现重复项 |
| `utils/proj_imgtrans.py::save` | `except: raise Exception(f'...{self.to_dict()}')` | 吞掉原始 traceback，且把整个项目字典塞进异常消息（可能二次抛错）；应 `raise` 并记日志 |
| `utils/textblock.py::group_output` | 死代码 | `split_textblk` 分支被注释掉，`textblock_splitted` 只剩“要不要 adjust_bbox”的作用，读代码的人会误判语义 |
| `utils/registry.py` | 遗留 mmcv 路径不可用 | `get()` 里 `self._scope` 从未定义（`scope` 属性被注释），`_add_children` 断言 `registry.scope`；带点号的 key 或父子注册会 `AttributeError`。要么删干净，要么补实现+测试 |
| `utils/registry.py::_register_module` | 覆盖语义隐式 | 懒 spec 被真类替换时不校验 `class_name` 是否一致（`register_lazy_module` 校验了，这里没校验） |
| `ui/io_thread.py::MergeThread` | 中文硬编码 | `'区域合并失败'`、`'合并 {img_name} 失败'`、`print(...)` 直出；其余 UI 都走 `self.tr()`，i18n 不一致。且它直接 `json.dump(..., indent=2)` 重写整个项目文件，会改变用户文件格式 |
| `modules/base.py` | `low vram mode` 键名带空格 | 与 `low_vram_mode` 混用，靠 `low_vram_mode` 属性兜底，易错 |
| 文档站点 `advanced/headless-mode` | 与代码漂移 | 文档称 headless 会设 `config.module.load_model_on_demand = True`，现 `launch.py` 只设 `empty_runcache=False`（可能在 `MainWindow` 内置，但文档引用的 `launch.py:189-191` 已失效） |

---

## 7. 建议路线（按投入产出）

**短期（1–2 天，低风险）**
1. 修 P3 表中的 `new_pages` 重置、`save()` 异常、`MergeThread` 的 i18n 与 JSON 重写（改成“仅更新 pages 字段、保留原缩进”或至少备份）。
2. 给 `BaseModule.__init__` 加 `deepcopy`，消掉 P1-3（改动 <10 行，收益最大）。
3. 加一条一致性测试：`for key in REGISTRY.module_dict: assert registry.get_spec(key).params == registry.resolve_module(key).params`（先在 translator/ocr 上跑）。

**中期（1–2 周）**
4. 抽 `PipelineService`：把“检测→OCR→翻译→修复→渲染→存盘”从 `MainWindow` 挪出，定义 `ProgressEvent`/`CancelToken`；`MainWindow` 只做信号适配。先只搬一条路径（整页 Run），headless 走新服务，GUI 保留旧路径并行验证，再切换。
5. `renderer.py` 按“表面/合成/缓存/预览”四段切开；`cards.py` 与 `annotations.py` 先只做“文件内分区 + 明确入口”，不追求一次拆完。
6. `shared`/`pcfg` 收敛为注入式 `ConfigProvider`（可先用 `contextvars` 过渡，避免大改调用点）。

**长期（1–2 月）**
7. `TextBlock` 拆分为几何/样式/OCR/编解码四类，`BlockCodec` 统一负责 v0→v1 迁移与 docx/JSON/txt 三种格式。
8. 把 `SafeEval` 白名单收敛为“声明式参数描述器”（例如模块用 `Param(...)` 构造，AST 与运行期共用同一构造），从根上消灭两份真相。

---

## 8. 证据与不确定性

**可直接核对的证据**
- `launch.py`：headless 仍 `MainWindow(...)`，仅 `-platform offscreen`；`preload_msvc_runtime()` 在 Qt 之前；`ensure_core_requirements` 后 `restart()`。
- `modules/base.py`：`standardize_module_params(self.params)` 与 `self.params.update(params)` 直接改类属性；`load_model()` 用 `QMutex`。
- `lazy_registry.py` 文件头注释“builds registry metadata from AST so startup never imports module code”，`SafeEval` 白名单，`_scan_file()` doctest。
- `proj_imgtrans.py`：`RASTER_ASSET_MAX_SOURCE_BYTES = 32 MiB`、`_decode_raster_asset_snapshot` 的 64 Mpx/256 MiB 限制、`commonpath` 逃逸检查、`os.replace` 原子落盘；`new_pages` 在 `load_from_dict` 中只 `append`。
- `textblock.py`：`del self.deprecated_attributes`、`__getattribute__` 的 `'pts'` 分支、`group_output` 中被注释的 `split_textblk` 调用。
- `registry.py`：`# self._scope = ...` 被注释，但 `get()` 仍引用 `self._scope`。
- `io_thread.py`：`MergeThread` 的中文字面量与 `print()`。

**不确定 / 未验证**
- 四阶段流程的具体编排位置（`MainWindow` 还是 `RunPipelineDialog`）——我未逐行读这两个文件，只确认了“headless 复用 MainWindow”与 `RunStatus`/`finish_code` 的存在；结论“编排在 UI 层”基于此推断，建议用 `rg "def run_imgtrans|RunStatus.FIN_DETECT"` 复核。
- `text_engine` 的文档契约写得很细，但**文档与实现是否完全一致未逐条验证**（例如 `geometry.py` 是否真是唯一的边界/映射所有者、`annotation` 的 `data-btrans-*` 是否真的只在必需处出现）。建议抽查 `TextItemGeometryController` 的调用点与 `annotations.py` 的导出路径。
- 测试体系：提交信息提到“36 tests per Qt binding, 20 doctests”，说明存在测试，但我未取到测试目录清单，故本文不对覆盖率下判断。
- 版本一致性：镜像 `dev` 与 GitHub `dev` 可能差几个提交，语义应一致，但行号/细节不保证。

**复现方式**（本机 GitHub 不通时）
```
https://raw.giteeusercontent.com/mirrors/BallonsTranslator/raw/dev/<path>
# 例：ballontranslator/modules/base.py
```
