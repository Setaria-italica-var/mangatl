"""Vision-model OCR for blocks the small engines cannot read.

Decorative lettering, dense small print and hand-drawn SFX are where manga-ocr and
RapidOCR both fail, and where a vision-language model can still read the crop. This
adapter talks to any **OpenAI-compatible vision endpoint** (a local llama.cpp server
with a Qwen2.5-VL GGUF, LM Studio, Ollama, or a cloud API), so the project does not
bundle a multi-gigabyte model.

Configuration comes from ``MANGATL_VISION_*`` and falls back to the translation
provider's ``MANGATL_*`` values, so one endpoint can serve both jobs.

It is only called for blocks that already failed the cheap checks, and its output
must pass the plausibility filter before it is used.
"""

from __future__ import annotations

import base64
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from PIL import Image

from mangatl.adapters.translators.openai_compat import _Transport

PROMPT = (
    "Transcribe the Japanese text in this manga crop. "
    "Keep the original line breaks. Output only the transcribed text, "
    "without quotes or explanation. If there is no readable text, output NOTEXT."
)
NO_TEXT = "NOTEXT"


@dataclass(frozen=True)
class VisionConfig:
    """Endpoint settings for a vision model."""

    base_url: str = ""
    api_key: str = ""
    model: str = ""
    timeout: float = 60.0
    max_side: int = 1280

    @classmethod
    def from_env(cls) -> VisionConfig:
        fallback_base = os.environ.get("MANGATL_BASE_URL", "")
        return cls(
            base_url=os.environ.get("MANGATL_VISION_BASE_URL", fallback_base),
            api_key=os.environ.get("MANGATL_VISION_API_KEY", os.environ.get("MANGATL_API_KEY", "")),
            model=os.environ.get("MANGATL_VISION_MODEL", ""),
            timeout=float(os.environ.get("MANGATL_VISION_TIMEOUT", "60")),
        )


class VisionOcr:
    """Read one block crop with a vision-language model."""

    name = "vision"

    def __init__(self, config: VisionConfig | None = None, transport: Any = None) -> None:
        self.config = config or VisionConfig.from_env()
        self._transport = transport or _Transport()

    @property
    def available(self) -> bool:
        """Whether an endpoint and model are configured."""
        return bool(self.config.base_url and self.config.model)

    def read(self, image_path: Path, bbox: tuple[int, int, int, int]) -> str:
        """Return the crop's text, or an empty string when unreadable."""
        if not self.available:
            return ""
        payload = {
            "model": self.config.model,
            "temperature": 0.0,
            "messages": [
                {
                    "role": "user",
                    "content": [
                        {"type": "text", "text": PROMPT},
                        {
                            "type": "image_url",
                            "image_url": {"url": self._data_uri(image_path, bbox)},
                        },
                    ],
                }
            ],
        }
        try:
            response = self._transport.post(
                f"{self.config.base_url.rstrip('/')}/chat/completions",
                payload,
                self.config.api_key,
                self.config.timeout,
            )
            content = response["choices"][0]["message"]["content"]
        except Exception:  # noqa: BLE001 - any provider failure means "no text"
            return ""
        return parse_reply(content)

    def _data_uri(self, image_path: Path, bbox: tuple[int, int, int, int]) -> str:
        import io

        with Image.open(image_path) as handle:
            page = handle.convert("RGB")
            x1, y1, x2, y2 = bbox
            pad = 6
            crop = page.crop(
                (
                    max(0, x1 - pad),
                    max(0, y1 - pad),
                    min(page.width, x2 + pad),
                    min(page.height, y2 + pad),
                )
            )
            if max(crop.size) > self.config.max_side:
                ratio = self.config.max_side / max(crop.size)
                size = (int(crop.width * ratio), int(crop.height * ratio))
                crop = crop.resize(size, Image.LANCZOS)
        buffer = io.BytesIO()
        crop.save(buffer, format="PNG")
        return "data:image/png;base64," + base64.b64encode(buffer.getvalue()).decode("ascii")


def parse_reply(content: str) -> str:
    """Normalise a model reply into plain text (``""`` when there is none)."""
    text = content.strip().strip('"').strip()
    if not text or NO_TEXT in text.upper():
        return ""
    lines = [line.strip() for line in text.splitlines() if line.strip()]
    return "\n".join(lines)
