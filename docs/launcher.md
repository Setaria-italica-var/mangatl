# 启动与安装脚本

项目不再提供 exe。仓库和便携版都使用同一套 bat 脚本，依赖版本只写在
`requirements.txt` / `requirements-dev.txt`，改依赖不需要改启动器。

## 文件职责

| 文件 | 作用 |
|---|---|
| `启动.bat` | 主入口：设置项目根目录 → 检查 `runtime\python.exe` → 运行 `tools/check_env.py` → 启动 `mangatl gui` |
| `launch.bat` | 英文别名，直接调用 `启动.bat` |
| `setup.bat` | 首次安装/更新 `runtime\Lib\site-packages`，调用 `tools/setup_env.py` |
| `诊断.bat` | 便携版专用：生成环境诊断文件；仓库源码用 `runtime\python.exe tools\diagnose.py` |
| `tools/check_env.py` | 校验依赖版本、模型文件和可导入性；失败时给出缺失项 |
| `tools/setup_env.py` | 用系统 Python 3.12 作为安装器，按 requirements 安装到 `runtime\` |
| `tools/sync_runtime.py` | 把 `src/mangatl` 同步到 `runtime\Lib\site-packages\mangatl` |

## 首次安装

要求：Windows 10/11 x64，系统 Python 3.12（仅安装时需要）。

```bat
setup.bat
```

脚本会：

1. 查找 `py -3.12` / `python3.12` / `python`（可用 `MANGATL_BOOTSTRAP_PYTHON` 指定）
2. 确认 `runtime\` 已存在（便携包自带；新克隆仓库需先从便携包复制）
3. `pip install --target runtime\Lib\site-packages -r requirements.txt`
4. 安装完成后由 `check_env.py` 验证

需要开发依赖（ruff、pytest）：

```bat
setup.bat --dev
```

## 日常启动

```bat
启动.bat
启动.bat samples\vol1
```

也可以直接调用：

```bat
runtime\python.exe -m mangatl gui samples\vol1
```

`启动.bat` 会设置：

```bat
MANGATL_HOME=<程序目录>
PYTHONUTF8=1
PYTHONIOENCODING=utf-8
```

所以配置、模型、缓存都在程序目录，不写注册表和 `%APPDATA%`。

## 更新依赖

1. 修改 `requirements.txt`
2. 运行 `setup.bat`
3. 重新运行 `check_env.py` 或直接启动

## 更新源码

仓库开发时改完 `src/mangatl` 后：

```bat
runtime\python.exe tools\sync_runtime.py
```

便携版发布时由 `tools/build_portable_bat.py` 复制源码和 runtime。

## 诊断

```bat
诊断.bat
```

会输出 Python 版本、关键依赖、模型文件、路径和导入错误到 `诊断结果.txt`。仓库源码可运行
`runtime\python.exe tools\diagnose.py > 诊断结果.txt`。
GUI 未捕获异常写入 `data\error.log`。

## 常见错误

| 现象 | 处理 |
|---|---|
| `缺少 runtime\python.exe` | 重新解压便携包，或确认 `setup.bat` 成功 |
| `环境检查未通过` | 看 `check_env.py` 输出的缺失依赖，运行 `setup.bat` |
| `找不到可用的 Python 3.12` | 安装 Python 3.12，或设置 `MANGATL_BOOTSTRAP_PYTHON` |
| 双击闪退 | 在 cmd 里运行 `启动.bat` 看错误；再运行 `诊断.bat` |
| 依赖下载慢/失败 | 配置 pip 镜像或代理后重试 `setup.bat` |

## 便携包结构

```
mangatl-portable/
├─ 启动.bat
├─ 诊断.bat
├─ 使用说明.txt
├─ requirements.txt
├─ runtime/            Python + 依赖 + mangatl 包
├─ data/               模型、设置、缓存
└─ tools/              check_env / diagnose
```
