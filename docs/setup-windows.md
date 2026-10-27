# Windows 开发环境搭建（从零开始）

> 目标：一台没装过 Python 的 Windows 10/11，30 分钟内能跑测试、能推 GitHub。
> 全程不需要管理员权限。

## 0. 检查家底

打开 **cmd**（不是 PowerShell，命令更通用）：

```bat
where py
py -0p
```

- 有 `py` 且列出 `-V:3.12` → 可直接用
- 没有 3.12 → 装 [Python 3.12.10](https://www.python.org/ftp/python/3.12.10/python-3.12.10-amd64.exe)，装时勾 **py launcher**
- 不要用 3.14 跑本项目：torch / onnxruntime 的 cp314 轮子覆盖不全

> 如果敲 `python` 弹出微软商店或提示"不是内部或外部命令"：
> 设置 → 应用 → 高级应用设置 → **应用执行别名** → 关掉 `python.exe`、`python3.exe`。
> 之后一律用 `py -3.12` 或激活 venv 后的 `python`，不要依赖系统 PATH 里的裸 `python`。

## 1. 进项目、建 venv

```bat
cd /d C:\Users\admin\Documents\deepseek-harness\default-workspace\mangatl
py -3.12 -m venv .venv
.venv\Scripts\activate.bat
python -V
```

提示符应变成 `(.venv) C:\...\mangatl>`，`python -V` 应输出 `Python 3.12.10`。
**每次新开窗口都要重新执行 `.venv\Scripts\activate.bat`。**

## 2. 选一条装依赖的路

### A. 镜像（推荐，最快）

```bat
set PIP_CONFIG_FILE=NUL
python -m pip install -e ".[dev]" ^
  --index-url https://pypi.tuna.tsinghua.edu.cn/simple ^
  --trusted-host pypi.tuna.tsinghua.edu.cn ^
  --timeout 30 --retries 2
```

`PIP_CONFIG_FILE=NUL` 让 pip 忽略 `%APPDATA%\pip\pip.ini`——那个文件常被安全软件锁成只读，读它容易带进意料外的源。

### B. 官方源 + 代理（需要节点能下 Fastly）

先验 30 秒，确认节点对 `files.pythonhosted.org` 不是零吞吐：

```bat
curl -s --proxy http://127.0.0.1:7897 https://pypi.org/simple/six/ | findstr whl
curl -o NUL --max-time 30 -w "code=%{http_code} speed=%{speed_download}\n" ^
  --proxy http://127.0.0.1:7897 "<上一步的 wheel 地址>"
```

`speed` 明显大于 0（比如几十万字节/秒）才继续：

```bat
set PIP_CONFIG_FILE=NUL
python -m pip install -e ".[dev]" ^
  --index-url https://pypi.org/simple ^
  --proxy http://127.0.0.1:7897 ^
  --timeout 30 --retries 2
```

注意：代理必须写 `http://`，不是 `https://`；Clash 要切「全局 / Global」。

### `-e .` 静默卡住（本机实测必现）

**现象**：`pip install -e ".[dev]"` 无任何输出、也不报错；`Ctrl+C` 后日志里只有 `ERROR: Operation cancelled by user`。
**原因**：pip 的 build isolation 会临时建环境再装 `hatchling`，子进程输出被捕获，看不到进度。
**做法**：装一次 hatchling，之后永久加 `--no-build-isolation`：

```bat
python -m pip install hatchling --index-url https://pypi.tuna.tsinghua.edu.cn/simple --trusted-host pypi.tuna.tsinghua.edu.cn --timeout 10 --retries 0
python -m pip install -e ".[dev]" --no-build-isolation --index-url https://pypi.tuna.tsinghua.edu.cn/simple --trusted-host pypi.tuna.tsinghua.edu.cn --timeout 10 --retries 0 -v
```

若报 `BackendUnavailable`：`python -m pip show hatchling` 的 `Location` 必须在 `.venv\Lib\site-packages` 下，否则用 `python -m pip install --force-reinstall hatchling`。

## 3. 验证

```bat
python -c "import mangatl; print(mangatl.__version__)"
python -m ruff check .
python -m pytest
```

预期：

```
0.3.0.dev0
All checks passed!
1 passed
```

> 直接敲 `ruff` / `pytest` 不认时，用 `python -m ruff` / `python -m pytest`——venv 的 Scripts 偶尔没进当前 PATH。

## 4. 推 GitHub

`github.com:443` 在国内常被 TLS 重置，但 `github.com:22` 通常可用，所以走 SSH：

```bat
ssh-keygen -t ed25519 -C "mangatl"
type %USERPROFILE%\.ssh\id_ed25519.pub | clip
```

浏览器：GitHub → Settings → SSH and GPG keys → New SSH key → 粘贴。

```bat
ssh -T git@github.com
git remote add origin git@github.com:<你的账号>/mangatl.git
git push -u origin main
```

若 22 也不通，在 `%USERPROFILE%\.ssh\config` 里加：

```
Host github.com
  HostName ssh.github.com
  Port 443
  User git
```

## 5. 每次开工（就两行）

```bat
cd /d C:\Users\admin\Documents\deepseek-harness\default-workspace\mangatl
.venv\Scripts\activate.bat
```

## 常见故障对照表

| 症状 | 原因 | 处理 |
|---|---|---|
| `'python' 不是内部或外部命令` | 商店占位符已关、3.12 不在 PATH | 用 `py -3.12`，或激活 venv |
| `python` 弹出微软商店 | 应用执行别名未关 | 关掉 `python.exe` / `python3.exe` 别名 |
| `.[dev]curl is not a valid editable requirement` | 两条命令粘成了一行 | 一条一条执行 |
| `ProxyError ... _ssl.c:993 handshake timed out` | 代理写成了 `https://` | 改成 `http://127.0.0.1:7897` |
| `SSL: UNEXPECTED_EOF_WHILE_READING` | 直连 pypi/github 被重置 | 走镜像，或代理 + Global 模式 |
| `PermissionError: pip.ini` | 配置文件被安全软件锁写 | 不要改它，用 `PIP_CONFIG_FILE=NUL` |
| 连接建立但下载速度 0 | 节点到 Fastly CDN 不通 | 换节点 / 换网络 / 离线 wheels |
| 卡在 `Resolving` 或构建 | build isolation 在下载 | `--no-build-isolation`（先装 hatchling） |

## 离线兜底（网络彻底不通时）

在能上网的机器上（同 Python 3.12、同 win_amd64）：

```bat
python -m pip download -e ".[dev]" -d wheels --index-url https://pypi.org/simple
```

把 `wheels\` 拷到本机后：

```bat
python -m pip install --no-index --find-links wheels -e ".[dev]"
```
