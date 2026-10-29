# 一键启动（launch.bat / tools/launcher.py）

不再提供 exe：单文件版需要在系统临时目录解压，公司电脑/杀软环境下容易被拦；
目录版又和直接跑脚本没区别。现在统一用 **launch.bat**，功能完全一致。

## 使用

```bat
launch.bat                :: 双击，或从命令行运行
launch.bat --check        :: 只体检，不安装、不启动
launch.bat samples\vol1   :: 指定漫画目录
```

也可以直接：

```bat
.venv\Scripts\python.exe tools\launcher.py
```

## 启动器做什么

1. 找 Python：`runtime\python`（内置运行时）→ `.venv` → 系统 `python`/`py`（≥3.10）
2. 没有虚拟环境时用系统 Python 创建 `.venv`
3. 检查依赖：PySide6、qfluentwidgets、numpy、Pillow、onnxruntime、torch、mangatl
4. 缺依赖：优先从 `wheels\` 离线安装，否则在线 `pip install -e .[gui]`
5. 检查模型：CTD、气泡检测、MIT48px OCR 与字典
6. 缺模型：调用 `python -m mangatl fetch-models`
7. 启动 `python -m mangatl gui`

失败会打印原因并暂停，窗口不会一闪而过；日志写在 `mangatl-launcher.log`，
未捕获异常写 `mangatl-launcher-crash.log`。

## 便携部署结构

```
mangatl\
├─ launch.bat                ← 双击
├─ pyproject.toml
├─ src\mangatl\...
├─ data\models\...           ← 模型（可预先放好）
├─ wheels\                   ← 可选：离线 wheel 包
├─ .venv\                    ← 可选：已装好的环境
└─ tools\launcher.py
```

整个 `mangatl` 文件夹拷到 U 盘即可，不需要安装程序。

## 离线安装依赖

在联网机器上：

```bat
pip download -d wheels -e .[gui]
```

把 `wheels\` 一起拷过去，启动器会先用 `--no-index --find-links wheels` 安装。

## 私有 pip 源

```bat
set MANGATL_PIP_INDEX=https://pypi.tuna.tsinghua.edu.cn/simple
launch.bat
```

## 模型下载

- 必需模型缺失时启动器自动调用 `fetch-models`
- 可选 LaMa 局部重绘权重（约 208 MB，支持断点续传）：

```bat
.venv\Scripts\python.exe -m mangatl fetch-models --lama
```
