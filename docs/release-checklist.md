# 发布检查清单

每次公开发布（打 tag 前）逐条检查。当前发布形态：**单目录便携版 + 7z 压缩包 + GitHub Release**，
没有 exe 安装器，也没有 full/lite 之分。

## 许可证与合规

- [ ] `LICENSE` 为 GPL-3.0 全文
- [ ] `NOTICE` 登记移植代码、第三方组件和模型许可证
- [ ] Release 关联源码 tag；GitHub 自动生成的 Source code 压缩包可用
- [ ] Qt/PySide6 以 LGPL-3.0 动态链接，`runtime/` 内 DLL 可替换
- [ ] 模型与字体许可证清单齐全，未重命名分发 OFL 字体
- [ ] 仓库无 API Key、无 `data/`、无漫画样本版权内容

## 便携性

- [ ] 产物中搜索不到 `C:\Users\...`、`AppData`、`Program Files` 等绝对路径
- [ ] 解压到中文路径、含空格路径、深层路径各启动一次
- [ ] 整个目录改名 / 换盘 / 拷到另一台没装 Python 的 Windows 能启动
- [ ] 删除 `data/tmp/`、`data/hf/` 后能正常启动
- [ ] 只读目录启动时给出明确提示，而不是半截写入
- [ ] `启动.bat` 的 CRLF、UTF-8 无 BOM 正确

## 版本与配置

- [ ] `pyproject.toml` 的 version 与 tag 一致
- [ ] `settings.json` 缺失/损坏时能回退默认值
- [ ] `project.json` 原子写入；旧 schema 能打开或给出明确错误
- [ ] `data/secrets.bin` 换用户/换机器后不会导致崩溃，只提示重填 Key
- [ ] `requirements.txt` 能通过 `setup.bat` 在新 runtime 上装好

## 质量门槛

- [ ] `runtime\Scripts\ruff.exe check .` 通过
- [ ] 相关 pytest 通过；至少 `test_paths.py`、`test_encoding.py`、`test_gui_audit.py`
- [ ] 用 `samples/vol1` 跑通：打开 → 检测 → OCR → 翻译（echo）→ 擦除 → 排版
- [ ] 手动擦除：左键擦除、右键恢复、大小、快速/精细、最小化、画面外笔迹
- [ ] 批量：范围、阶段、跳过已完成、停止、失败重试
- [ ] CPU-only 机器跑完一页；断网时给出可读错误
- [ ] 抽查 30 页：排版可读、无明显残留文字

## 材料与分发

- [ ] `docs/release-notes-vX.Y.Z.md` 已更新：变更、安装、已知问题、校验
- [ ] `启动.bat`、`诊断.bat`、`使用说明.txt` 已随包更新
- [ ] `tools/pack_release.ps1` 生成压缩包和 `SHA256SUMS.txt`
- [ ] 压缩包大小 < 2 GB（否则用 `-VolumeMB 900` 分卷）
- [ ] 在干净 Windows 上解压、启动、打开样例、跑一页
- [ ] 打 tag `vX.Y.Z` 并推送
- [ ] GitHub Release：选择 tag、贴说明、上传压缩包和 SHA256，发布

## 发布后

- [ ] 下载 Release 附件，重新校验 SHA256
- [ ] 检查 Release 页面下载链接和安装说明可读
- [ ] 收集首日启动失败/崩溃日志，确认无高频环境问题
