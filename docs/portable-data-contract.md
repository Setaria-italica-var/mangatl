# 便携版 `data/` 目录与配置约定（v1）

> 适用：MangaTL 便携版（解压即用）。这份约定是**打包前必须冻结的契约**：代码、安装包、`使用说明.txt` 都以此为准。

## 0. 四条总则

1. **可搬迁**：`data/` 内除「用户显式选择的项目路径」外，不得出现绝对路径；所有默认路径相对 `data/` 或程序根。
2. **只写自己**：不写注册表、不写 `%APPDATA%`、不写 `C:\ProgramData`；所有状态都在 `data/`。
3. **原子 + 可恢复**：任何 JSON 写入走 `*.tmp` → `os.replace`；`config.json` 保留 1 份 `.bak`。
4. **向前兼容**：未知字段不删（收进 `_unknown`），新字段给默认值；**低版本程序读到高 schema 只读不写**，防止回退时丢配置。

---

## 1. 目录树

```
data/
  config.json              用户配置（唯一可手工编辑的文件）
  secrets.enc              可选：加密后的 API Key（默认不存在）
  models/
    manifest.json          模型清单（随包发布，只读）
    LICENSES.txt           模型/字体许可证汇总
    .state.json            已安装校验状态（运行时生成，可删）
    ctd/ ocr/ inpaint/ ... 模型权重
  fonts/
    builtin/               随包内置（思源黑体/宋体、霞鹜文楷）
    user/                  用户放入的字体
  logs/
    app.log  engine.log    （5 MB × 3 轮转）
  cache/
    translate/             译文缓存（可删）
    render/                预览缓存（可删）
  state/
    .lock                  单实例锁（按目录）
    last_session.json      窗口几何 / 最后打开的项目
  tmp/                     下载临时文件、渲染中间层
```

| 目录 | 可删 | 备份价值 | 说明 |
|---|---|---|---|
| `config.json` | 否（会重建默认） | **高** | 用户配置 |
| `secrets.enc` | 否 | 高 | 加密 Key，丢了重填 |
| `models/` | 是 | 低 | 体积大，可重下；`manifest.json` 不要删 |
| `fonts/user/` | 否 | 中 | 用户自备字体 |
| `logs/` | 是 | 低 | 排障用 |
| `cache/` | 是 | 无 | 删了只影响速度 |
| `state/` | 是 | 无 | 锁与窗口位置 |

---

## 2. `config.json`

```json
{
  "schema": 1,
  "app": {
    "ui_lang": "zh-CN",
    "first_run_done": false,
    "last_version": "0.3.0"
  },
  "hardware": {
    "device": "auto",
    "tier": "auto",
    "precision": "auto",
    "max_side_detect": 1280,
    "max_side_inpaint": 2048,
    "batch_pages": 20,
    "unload_inpaint_after_batch": true
  },
  "paths": {
    "projects_dir": "../projects",
    "models_dir": "models",
    "fonts_dir": "fonts",
    "log_level": "info"
  },
  "pipeline": {
    "src_lang": "ja",
    "tgt_lang": "zh-CN",
    "keep_vertical": "auto",
    "ocr_ja": "manga_ocr",
    "ocr_other": "ppocr",
    "inpaint_engine": "auto",
    "solid_fastpath": true,
    "sfx_policy": "keep",
    "export_format": "cbz"
  },
  "translate": {
    "active_profile": "deepseek",
    "profiles": [
      {
        "id": "deepseek",
        "name": "DeepSeek",
        "base_url": "https://api.deepseek.com/v1",
        "model": "deepseek-chat",
        "key_ref": "deepseek",
        "temperature": 0.3,
        "max_tokens": 4096,
        "timeout": 60,
        "rpm": 30,
        "json_mode": true
      }
    ],
    "history": {"enabled": true, "budget_tokens": 8192},
    "glossary_path": "",
    "cache": true
  },
  "render": {
    "font_sans": "Source Han Sans SC",
    "font_serif": "Source Han Serif SC",
    "font_hand": "LXGW WenKai",
    "size_scale": 1.0,
    "stroke_mode": "auto",
    "vertical_align": "top"
  },
  "ui": {"theme": "dark", "zoom": "fit", "show_overlay": true},
  "advanced": {"debug": false, "cache_limit_mb": 512, "threads": 4},
  "_unknown": {}
}
```

### 字段规则

| 段 | 关键字段 | 取值 | 备注 |
|---|---|---|---|
| `app` | `ui_lang` | `zh-CN` / `en-US` | 界面语言 |
| `hardware` | `device` | `auto` / `cuda:0` / `cpu` | **默认 auto**：便携版每台机器重新探测 |
| | `tier` | `auto` / `high`(1024) / `mid`(768) / `low`(512) | 显存档位，auto = ≥8 GB 取 high |
| | `precision` | `auto` / `fp16` / `bf16` / `fp32` | auto 依 GPU 能力 |
| `pipeline` | `keep_vertical` | `auto` / `always` / `never` | auto = 跟随原文方向 |
| | `sfx_policy` | `keep` / `translate` / `erase` | 默认 keep |
| `translate` | `key_ref` | 字符串 | 只存**引用名**，绝不存 Key 本身 |
| | `rpm` | 整数 | 请求频率上限，防限流 |
| `render` | `stroke_mode` | `auto` / `manual` | 描边宽度由色差估计或手填 |
| `advanced` | `cache_limit_mb` | 整数 | 超过后按 LRU 淘汰 `cache/` |

### 写入规则
- 修改走「读 → 改 → 校验 → 原子写」，写前把旧文件复制为 `config.json.bak`（只留 1 份）。
- 校验失败（类型不符/越界）→ 用默认值替换该字段并写日志，**不阻塞启动**。
- `_unknown` 原样保留；UI 不展示。

---

## 3. `models/manifest.json`

```json
{
  "schema": 1,
  "updated": "2026-10-20",
  "models": [
    {
      "id": "ctd",
      "stage": "detect",
      "version": "1.0.0",
      "license": "GPL-3.0",
      "source": "https://github.com/dmMaze/comic-text-detector",
      "required": true,
      "vram_mb": 1200,
      "files": [
        {
          "path": "ctd/ctd.pt",
          "sha256": "<64 位十六进制>",
          "size": 123456789,
          "urls": [
            "https://hf-mirror.com/.../ctd.pt",
            "https://huggingface.co/.../ctd.pt"
          ]
        }
      ]
    },
    {
      "id": "lama",
      "stage": "inpaint",
      "version": "1024",
      "license": "Apache-2.0",
      "required": true,
      "vram_mb": 3200,
      "files": [{"path": "inpaint/lama.pt", "sha256": "...", "size": 0, "urls": ["..."]}]
    }
  ]
}
```

### 规则
- `path` 相对 `models/`，正斜杠，**禁止 `..`**；越界即拒绝加载。
- `sha256` 与 `size` 必填；下载到 `tmp/<name>.part`，校验通过后 `os.replace` 落位。
- `urls` 至少 1 条，按顺序尝试；失败换下一条。
- 启动只读 `manifest.json` + `.state.json` 判断“是否已装”；完整哈希校验放在「设置 → 模型 → 检查文件」按需执行（避免每次启动扫 2 GB）。
- `required=false` 的模型（如英文 OCR）缺失只提示，不阻塞。
- `.state.json` 记录 `{id, version, files:[{path, sha256, mtime, size}]}`；manifest 版本变化即失效。

### `LICENSES.txt` 格式（人工可读，随包发布）
```
[ctd] comic-text-detector
  source : https://github.com/dmMaze/comic-text-detector
  license: GPL-3.0
  files  : ctd/ctd.pt  sha256=...

[font] Source Han Sans SC
  source : https://github.com/adobe-fonts/source-han-sans
  license: SIL OFL 1.1（保留字体名）
```

---

## 4. `fonts/`
- `builtin/` 只读，随包三款：思源黑体（对话）、思源宋体（旁白）、霞鹜文楷（手写/独白）。
- `user/` 用户自放 `.ttf/.otf`；启动时扫描并注册，不复制、不改名。
- 回退链：`用户选择 → 思源黑体 → 系统 CJK → 内置兜底`。
- OFL 要求：不重命名内置字体、不单独售卖；LICENSES 里注明来源。

---

## 5. `cache/`
- `translate/<sha256>.json`：`{src_text, translation, model, prompt_ver, glossary_ver, created_at}`；键 = 上述字段拼接后的哈希。
- `render/` 默认关闭（页面渲染结果存在项目目录，便于校对），只在“缩略图/对比图”时启用。
- 淘汰：`cache_limit_mb` 超限后按 `created_at` LRU 删除；整目录可安全删除。

---

## 6. `logs/`
- `app.log`（界面/操作）、`engine.log`（检测/OCR/翻译/抹字/渲染）。
- 5 MB × 3 轮转；级别 `info`（默认）/`debug`（设置里开，重启生效）。
- **隐私红线**：任何级别都不得记录 API Key；默认不记录原文与译文；`debug` 才记录文本，且启动时明确提示“日志将包含漫画文本”。

---

## 7. `state/`
- `.lock`：`{"pid": 1234, "started_at": "...", "host": "PC-NAME"}`。启动时若文件存在，先探活（同 pid 且进程在 → 激活已有窗口；否则视为残留，接管并覆盖）。
- `last_session.json`：`{last_project, window_geometry, zoom}`。窗口几何放这里而不是 `config.json`，避免关闭时频繁写配置。

---

## 8. `secrets.enc`（可选）

```json
{
  "v": 1,
  "kdf": {"algo": "argon2id", "m": 65536, "t": 3, "p": 1, "salt": "<b64>"},
  "cipher": {"algo": "chacha20poly1305", "nonce": "<b64>"},
  "entries": {
    "deepseek": {"api_key": "<encrypted>", "updated_at": "..."}
  }
}
```

- 只有「设置 → 用主密码加密保存」被勾选时才创建；默认**不落盘任何 Key**。
- 解密失败（密码错/文件损坏）→ 提示重输，**不删除文件**（防止误删导致全部配置丢失）。
- 主密码不存储、不记忆；会话内只保存在内存。
- 便携版不依赖 DPAPI（换机必失效），所以强调主密码方案。

---

## 9. `projects/`（项目目录自包含）

```
projects/<书名>/
  project.json
  source/           源图副本（CBZ 解包或文件夹复制进来）
  mask/             抹字掩膜
  inpainted/        抹字结果
  result/           导出结果
  assets/           用户导入的图片/贴图（内容寻址）
```

- 优先**复制源图**进 `source/`，保证整个项目目录可整体拷走（便携版的核心价值）。
- 若用户选择“引用原文件”，`project.json` 记相对路径；跨盘时退化为绝对路径并标 `"portable": false`，移动后提示“源文件丢失，请重新指定”。
- 项目内不得出现指向 `data/` 的绝对路径；模型与字体通过 `id` 引用。

---

## 10. 版本与迁移

| 场景 | 行为 |
|---|---|
| `schema` 相同 | 正常读写；未知键进 `_unknown` |
| 低 → 高（升级） | 逐版本迁移函数，**幂等**；迁移前自动 `config.json.pre-vN.bak` |
| 高 → 低（降级） | **只读模式**：可运行、可导出，禁止写回配置；顶部提示“配置来自更新版本” |
| 字段类型非法 | 该字段回默认 + 日志警告，其余字段保留 |

---

## 11. 便携性检查清单（CI 必跑）

- [ ] 打包产物 `grep` 不到绝对路径、用户名、`AppData`、`Program Files`。
- [ ] `data/` 中除用户显式选择项外，无绝对路径。
- [ ] 中文目录、含空格目录、深层目录（≥ 8 层）各跑一次完整流程。
- [ ] 放到只读目录启动 → 明确报错并退出，不产生半截文件。
- [ ] 同目录双开 → 第二个激活第一个；不同目录双开 → 两个都能跑。
- [ ] 删掉 `cache/`、`logs/`、`state/`、`secrets.enc` 后均能正常启动。
- [ ] 把整个目录重命名 / 换盘符 / 拷到另一台机器，项目仍能打开（源图在 `source/` 时）。
- [ ] 模型缺一个 `required` 项 → 引导下载；缺 `optional` 项 → 仅提示。
- [ ] 降级测试：用 v(N+1) 生成的配置启动 v(N)，确认只读不写。
