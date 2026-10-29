# 一键启动器（mangatl-launcher.exe）

## 它做什么

双击后按顺序执行：

1. 找 Python：`runtime\python`（内置运行时）→ `.venv` → 系统 `python`/`py`（≥3.10）
2. 没有虚拟环境时用系统 Python 创建 `.venv`
3. 检查依赖：PySide6、qfluentwidgets、numpy、Pillow、onnxruntime、torch、mangatl
4. 缺依赖：优先从 `wheels\` 离线安装，否则在线 `pip install -e .[gui]`
5. 检查模型：CTD、气泡检测、MIT48px OCR 与字典
6. 缺模型：调用 `python -m mangatl fetch-models`
7. 启动 `python -m mangatl gui`

任何一步失败都会打印原因并暂停（双击窗口不会一闪而过）。

## 使用

```bat
mangatl-launcher.exe            :: 双击即可
mangatl-launcher.exe --check    :: 只体检，不安装不启动
mangatl-launcher.exe --no-launch
mangatl-launcher.exe samples\vol1
```

不打包 exe 也可以直接跑：

```bat
launch.bat
```

## 构建 exe

```bat
python tools/build_launcher.py            :: 单文件 dist\mangatl-launcher.exe（约 8 MB）
python tools/build_launcher.py --onedir   :: 目录版 dist\mangatl-launcher\
```

单文件版运行时会解压到系统临时目录；如果公司策略禁止写临时目录，用目录版。

## 便携部署结构

```
mangatl\
├─ mangatl-launcher.exe      ← 双击
├─ pyproject.toml
├─ src\mangatl\...
├─ data\models\...           ← 模型（可预先放好）
├─ wheels\                   ← 可选：离线 wheel 包
├─ .venv\                    ← 可选：已装好的环境
└─ launch.bat
```

把整个 `mangatl` 文件夹拷到 U 盘/移动硬盘即可，不需要安装程序。

## 离线安装依赖

在联网机器上：

```bat
pip download -d wheels -e .[gui]
```

把 `wheels\` 一起拷过去，启动器会先用 `--no-index --find-links wheels` 安装。

## 私有 pip 源

```bat
set MANGATL_PIP_INDEX=https://pypi.tuna.tsinghua.edu.cn/simple
mangatl-launcher.exe
```

## 模型下载

- 必需模型缺失时启动器会自动调用 `fetch-models`
- 可选 LaMa 局部重绘权重（约 208 MB，支持断点续传）：

```bat
python -m mangatl fetch-models --lama
```
