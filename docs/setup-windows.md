# Windows 开发与运行环境

## 0. 两条路径

| 场景 | 做法 |
|---|---|
| 只想运行 | 解压便携版，双击 `启动.bat`；不需要装 Python |
| 改代码 / 跑测试 | 需要系统 Python 3.12 执行一次 `setup.bat`，之后仍用 `runtime\python.exe` |

仓库里的 `runtime\` 就是实际运行环境：Python 3.12 + `requirements.txt` 里的依赖 +
`mangatl` 包。启动器不会使用系统 Python（除了 `setup.bat` 首次安装）。

> **新克隆的仓库没有 `runtime\`**（已在 `.gitignore` 中）。开始前先下载便携版，
> 把它的 `runtime\` 和 `data\models\` 复制到仓库根目录；否则 `setup.bat` 会提示
> 缺少 runtime。

## 1. 检查系统

- Windows 10/11 64 位
- 磁盘至少 6 GB 可用（runtime + 模型 + 项目输出）
- 联网（首次装依赖、下载模型/翻译请求）

```bat
py -3.12 -V
```

如果没有 `py -3.12`，安装 [Python 3.12](https://www.python.org/downloads/windows/)，
安装时勾选 Python Launcher。

> 不要用 Python 3.14：torch / onnxruntime 的 cp314 轮子覆盖不全。

## 2. 初始化 runtime

```bat
cd /d <仓库目录>
setup.bat
```

`setup.bat` 调用 `tools/setup_env.py`：

1. 查找 `py -3.12` / `python3.12` / `python`
2. 确认仓库内 `runtime\` 存在
3. 按 `requirements.txt` 安装到 `runtime\Lib\site-packages`
4. 完成后可直接启动

需要 ruff / pytest：

```bat
setup.bat --dev
```

如果下载慢，先设置 pip 镜像再运行：

```bat
set PIP_INDEX_URL=https://pypi.tuna.tsinghua.edu.cn/simple
set PIP_TRUSTED_HOST=pypi.tuna.tsinghua.edu.cn
setup.bat
```

需要代理时：

```bat
set HTTPS_PROXY=http://127.0.0.1:7890
set HTTP_PROXY=http://127.0.0.1:7890
setup.bat
```

## 3. 校验与启动

```bat
runtime\python.exe tools\check_env.py
启动.bat
```

`check_env.py` 会检查依赖版本、模型和 `mangatl` 导入；缺什么会直接打印。
便携版启动失败会提示运行 `诊断.bat`；源码环境可运行 `runtime\python.exe tools\diagnose.py`。

直接跑 GUI / CLI：

```bat
runtime\python.exe -m mangatl gui samples\vol1
runtime\python.exe -m mangatl run samples\vol1 --translator echo --force
```

## 4. 开发循环

```bat
runtime\python.exe tools\sync_runtime.py
runtime\Scripts\ruff.exe check .
runtime\python.exe -m pytest tests\test_paths.py
```

改完 `src/mangatl` 后必须同步到 runtime，否则 `runtime\python.exe -m mangatl`
仍会加载旧代码。GUI 开发通常直接跑：

```bat
runtime\python.exe -m mangatl gui samples\vol1
```

完整测试套件较大，建议先跑与改动相关的文件，再跑全量。

## 5. 模型

模型在 `data\models\`：

```
comictextdetector.pt.onnx   检测
bubble_detector.onnx        气泡
lama.onnx                   精细擦除（可选，约 200 MB）
mit/                        OCR 资源
```

缺少 LaMa 时：

```bat
runtime\python.exe -m mangatl fetch-models --lama
```

其他模型下载：

```bat
runtime\python.exe -m mangatl fetch-models --list
runtime\python.exe -m mangatl fetch-models
```

## 6. 构建便携版

```bat
runtime\python.exe tools\build_portable_bat.py
```

输出 `dist\mangatl-portable\`，包含：

- `runtime\`（Python + site-packages）
- `data\`（模型）
- `启动.bat`、`诊断.bat`
- `tools\check_env.py`、`diagnose.py`

发布压缩包：

```powershell
powershell -ExecutionPolicy Bypass -File tools\pack_release.ps1 -Version 0.3.0
```

7-Zip 会生成单卷或分卷，并写 `SHA256SUMS.txt`。

## 7. 常见错误

| 错误 | 原因 / 处理 |
|---|---|
| `缺少 runtime\python.exe` | 没解压完整，或 `setup.bat` 失败 |
| `环境检查未通过` | 依赖版本不匹配；重跑 `setup.bat` |
| `ModuleNotFoundError: mangatl` | 运行了错误的 Python；用 `runtime\python.exe` |
| GUI 报 Qt 平台插件错误 | `runtime\` 不完整，重新解压/安装 |
| 模型下载失败 | 检查网络；LaMa 可手动放 `data\models\lama.onnx` |
| 启动闪退 | cmd 运行 `启动.bat` 看 traceback，或跑 `诊断.bat` |

## 8. 目录与数据

- `MANGATL_HOME` 覆盖程序根目录
- `MANGATL_DATA_DIR` 覆盖 `data/` 目录
- 不写注册表、不写 `%APPDATA%`
- 项目状态写在用户打开的漫画目录：`project.json`、`inpainted/`、`result/`

详见 [portable-data-contract.md](portable-data-contract.md)。
