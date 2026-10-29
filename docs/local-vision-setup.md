# 启用视觉模型（L4）读取装饰字体

## 为什么需要

纯文本校验只能判断「这段像不像日文」，无法还原看错的内容。实测：16 个低分块里，
LLM 文本修复只救回 2 个，其余都只能返回空。装饰字体、密集小字、手写 SFX 必须**看图**。

## 方案选择

| 方式 | 难度 | 显存 | 说明 |
|---|---|---|---|
| **Ollama**（推荐） | ★ | ~3 GB | 一条命令拉模型，自带 OpenAI 兼容接口 |
| llama.cpp `llama-server` | ★★ | ~3 GB | 需手动下载 GGUF + mmproj |
| 云端视觉 API | ★ | 无 | 需要支持图片的 key（DeepSeek 目前不支持） |

## 方案一：Ollama（最简单）

```bat
:: 1. 安装 Ollama（官网下载 Windows 安装包）
:: 2. 拉取视觉模型
ollama pull qwen2.5vl:3b

:: 3. 确认服务在跑（默认 11434）
curl http://127.0.0.1:11434/v1/models
```

跑流水线：

```bat
python -m mangatl run samples\vol1 --detector ctd --ocr manga_ocr ^
  --inpainter masked --translator openai --target-lang 简体中文 ^
  --vision-model "qwen2.5vl:3b" ^
  --vision-base-url "http://127.0.0.1:11434/v1" ^
  --force
```

API key 不需要：适配器允许空 key（Ollama 不校验）。

## 方案二：llama.cpp

1. 下载 llama.cpp Windows 版本（`llama-server.exe`）
2. 下载 GGUF 模型（走 HF 镜像）：

```bat
set HF_ENDPOINT=https://hf-mirror.com
uv pip install huggingface_hub
python -c "from huggingface_hub import hf_hub_download as d; d('unsloth/Qwen2.5-VL-3B-Instruct-GGUF', 'Qwen2.5-VL-3B-Instruct-Q4_K_M.gguf', local_dir='data/models/vl'); d('unsloth/Qwen2.5-VL-3B-Instruct-GGUF', 'mmproj-F16.gguf', local_dir='data/models/vl')"
```

3. 启动服务：

```bat
llama-server -m data\models\vl\Qwen2.5-VL-3B-Instruct-Q4_K_M.gguf ^
  --mmproj data\models\vl\mmproj-F16.gguf ^
  --host 127.0.0.1 --port 8080 -c 4096
```

4. 跑流水线：

```bat
python -m mangatl run samples\vol1 --detector ctd --ocr manga_ocr ^
  --inpainter masked --translator openai --target-lang 简体中文 ^
  --vision-model "qwen2.5-vl-3b" ^
  --vision-base-url "http://127.0.0.1:8080/v1" ^
  --force
```

## 行为与预算

- 只有**气泡内**且 `ocr_score < 0.5` 的块会送视觉模型
- 每页最多 **6 块**，按分数从低到高
- 输出必须通过合理性校验（≥0.6 且优于原分）才会被采用
- 结果标记 `ocr_source="vision"`，仍写 `needs_review=True`
- 服务不可用时自动跳过，不影响其余流程

## 验证

```bat
python -c "import json,collections;d=json.load(open('samples/vol1/project.json',encoding='utf-8'));bs=[b for p in d['pages'].values() for b in p['blocks']];print(collections.Counter(b['ocr_source'] for b in bs))"
```

出现 `vision` 说明生效。

## 许可提示

- Qwen2.5-VL 权重：Apache-2.0（可商用）
- 模型不随本项目分发，由用户自行下载
- 云端 API 时，漫画图片会离开本机——与项目的本地化原则冲突，需自行权衡
