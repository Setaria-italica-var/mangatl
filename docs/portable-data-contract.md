# 便携版 `data/` 目录与配置约定

适用于 v0.3.0 便携版和源码运行。目标：整个程序目录可以搬动、复制、换机器，
不写注册表，不写 `%APPDATA%`。

## 1. 目录树

```
mangatl/ 或 mangatl-portable/
├─ runtime/                   Python 解释器 + site-packages
├─ data/
│  ├─ settings.json           翻译与后台任务设置（明文，无 Key）
│  ├─ secrets.bin             可选：DPAPI 加密的 API Key
│  ├─ recent.json             最近打开的项目
│  ├─ error.log               GUI 未捕获异常（有才生成）
│  ├─ models/                 CTD、气泡、LaMa、OCR 资源
│  ├─ hf/                     HuggingFace 缓存
│  ├─ ultralytics/            气泡模型缓存
│  └─ tmp/                    后台任务临时文件
├─ tools/                     check_env / diagnose / setup / sync
├─ requirements.txt
├─ 启动.bat
└─ 诊断.bat
```

| 路径 | 可删 | 备份价值 | 说明 |
|---|---|---|---|
| `data/settings.json` | 会重建默认 | 高 | 翻译预设、空闲退出、软取消、自动预览 |
| `data/secrets.bin` | 是（需重填 Key） | 高 | DPAPI 加密，仅当前 Windows 用户可解 |
| `data/recent.json` | 是 | 低 | 最近项目列表 |
| `data/models/` | 是（可重下） | 低 | 体积大；LaMa 约 200 MB |
| `data/hf/`、`data/ultralytics/` | 是 | 无 | 推理缓存 |
| `data/tmp/` | 是 | 无 | 异常退出后可能残留，可清空 |
| `data/error.log` | 是 | 排障时保留 | 崩溃栈，不含图片/译文/Key |

## 2. `settings.json`

示例：

```json
{
  "profile": "openai",
  "base_url": "https://api.deepseek.com/v1",
  "model": "deepseek-chat",
  "worker_idle_minutes": 10,
  "soft_cancel_tasks": false,
  "auto_preview_default": true,
  "api_ready": true,
  "switched_to_echo": false
}
```

| 字段 | 类型 | 说明 |
|---|---|---|
| `profile` | string | `openai` / `ollama` / `lmstudio` / `llamacpp` / `echo` |
| `base_url` | string | OpenAI 兼容接口根地址（到 `/v1`） |
| `model` | string | 模型名 |
| `worker_idle_minutes` | int | 后台子进程空闲多少分钟退出 |
| `soft_cancel_tasks` | bool | 取消时是否等当前任务完成 |
| `auto_preview_default` | bool | 启动时是否开启实时预览 |
| `api_ready` | bool | 上次保存时是否已配置可用 Key |
| `switched_to_echo` | bool | 上次是否因缺 Key 自动切到回显 |

写入方式：`data/settings.json.tmp` → `os.replace`，避免半截 JSON。

## 3. `secrets.bin`

- 勾选“记住 Key”才生成
- 用 Windows DPAPI（当前用户 + 本机）加密，文件是二进制
- 复制到另一台电脑/另一个 Windows 用户后无法解密，需要重填
- 删除后下次启动必须重新输入 Key
- 日志、异常和 `settings.json` 都不会写入明文 Key

## 4. `recent.json`

记录最近打开的项目，供首页快速入口使用；内容是项目路径列表。
移动项目后条目可能失效，重新打开一次即可。

## 5. 模型

| 文件 | 用途 | 大小 |
|---|---|---|
| `models/comictextdetector.pt.onnx` | CTD 文字检测 | 约 90 MB |
| `models/bubble_detector.onnx` | 气泡检测 | 约 99 MB |
| `models/lama.onnx` | LaMa 精细擦除（可选） | 约 198 MB |
| `models/mit/` | MIT48px OCR 资源 | 随包 |

`fetch-models` 可以下载/补齐：

```bat
runtime\python.exe -m mangatl fetch-models --lama
runtime\python.exe -m mangatl fetch-models --list
```

## 6. 项目目录（不是 `data/`）

用户打开的漫画目录会生成：

```
<漫画目录>/
├─ project.json     页面、文本块、阶段状态（原子写入）
├─ inpainted/       擦除后的页面
└─ result/          排版结果
```

`project.json` 是断点续跑的来源；删除它会让所有页重新从检测开始。
`inpainted/`、`result/` 可删，重新运行会再生成。

## 7. 路径覆盖

| 环境变量 | 作用 |
|---|---|
| `MANGATL_HOME` | 覆盖程序根目录（默认自动识别仓库/便携版） |
| `MANGATL_DATA_DIR` | 覆盖 `data/` 目录 |
| `MANGATL_BOOTSTRAP_PYTHON` | `setup.bat` 使用的系统 Python |
| `MANGATL_API_KEY` / `MANGATL_BASE_URL` / `MANGATL_MODEL` | 覆盖翻译配置，环境变量优先 |

## 8. 备份与升级

备份只需：

```
data/settings.json
data/secrets.bin（如果需要保留 Key）
<漫画目录>/project.json
<漫画目录>/inpainted/
<漫画目录>/result/
```

升级便携版：解压新版，覆盖 `runtime/`、`启动.bat`、`tools/`，**保留 `data/`**。
模型和缓存可以重新生成，不必备份。
