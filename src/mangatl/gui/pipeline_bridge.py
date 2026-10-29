"""Build a pipeline service from the engine names chosen in the UI."""

from __future__ import annotations

import os
from pathlib import Path

from mangatl.core.pipeline import PipelineService
from mangatl.domain.project import Project

DETECTORS = ("ctd",)
OCRS = ("mit_manga", "manga_ocr", "mit48px_ctc", "rapidocr")
INPAINTERS = ("masked", "lama")
TRANSLATORS = ("openai", "echo")


def build_default_service(
    project: Project,
    detector: str = "ctd",
    ocr: str = "mit_manga",
    inpainter: str = "masked",
    translator: str = "openai",
) -> PipelineService:
    """Wire the selected engines, degrading gracefully when one is unavailable."""
    from mangatl.adapters.detectors.ctd import CtdDetector
    from mangatl.adapters.inpaint.masked import MaskedInpainter
    from mangatl.adapters.ocr.hybrid import FusionOcr
    from mangatl.adapters.ocr.manga_ocr import MangaOcrAdapter
    from mangatl.adapters.translators.echo import EchoTranslator

    detector_obj = CtdDetector()

    manga = MangaOcrAdapter()
    ocr_obj = manga
    if ocr in {"mit_manga", "mit48px_ctc"}:
        try:
            from mangatl.adapters.ocr.mit48px import DEFAULT_MODEL, Mit48pxOcr

            if Path(os.environ.get("MANGATL_MIT48_MODEL", DEFAULT_MODEL)).is_file():
                mit = Mit48pxOcr()
                ocr_obj = FusionOcr(mit, manga) if ocr == "mit_manga" else mit
        except Exception:  # noqa: BLE001 - optional engine
            ocr_obj = manga
    elif ocr == "rapidocr":
        from mangatl.adapters.ocr.rapid import RapidOcrAdapter

        ocr_obj = RapidOcrAdapter()

    if inpainter == "lama":
        from mangatl.adapters.inpaint.lama import LamaInpainter

        inpainter_obj = LamaInpainter()
    else:
        inpainter_obj = MaskedInpainter()

    translator_obj = EchoTranslator()
    if translator == "openai" and os.environ.get("MANGATL_API_KEY"):
        try:
            from mangatl.adapters.translators.openai_compat import (
                LlmConfig,
                OpenAiTranslator,
            )

            translator_obj = OpenAiTranslator(LlmConfig.from_env())
        except Exception:  # noqa: BLE001 - keep echo when the provider is unusable
            translator_obj = EchoTranslator()

    bubble_detector = None
    try:
        from mangatl.adapters.detectors.bubbles import BubbleDetector

        candidate = BubbleDetector("data/models/bubble_detector.onnx")
        if candidate.available:
            bubble_detector = candidate
    except Exception:  # noqa: BLE001 - optional model
        bubble_detector = None

    return PipelineService(
        project,
        detector_obj,
        ocr_obj,
        inpainter_obj,
        translator=translator_obj,
        bubble_detector=bubble_detector,
    )
