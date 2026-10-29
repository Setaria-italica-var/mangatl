"""Build the default pipeline for the editor's "run this page" action."""

from __future__ import annotations

import os
from pathlib import Path

from mangatl.core.pipeline import PipelineService
from mangatl.domain.project import Project


def build_default_service(
    project: Project, stages: tuple[str, ...] | None = None
) -> PipelineService:
    """Wire the best available engines into a pipeline service.

    Missing optional pieces degrade instead of failing: no MIT48 weights means
    manga-ocr alone, no API key means the echo translator, no bubble model means
    the heuristic annotation inside the pipeline.
    """
    from mangatl.adapters.detectors.ctd import CtdDetector
    from mangatl.adapters.inpaint.masked import MaskedInpainter
    from mangatl.adapters.ocr.hybrid import FusionOcr
    from mangatl.adapters.ocr.manga_ocr import MangaOcrAdapter
    from mangatl.adapters.translators.echo import EchoTranslator

    detector = CtdDetector()
    manga = MangaOcrAdapter()
    ocr = manga
    try:
        from mangatl.adapters.ocr.mit48px import DEFAULT_MODEL, Mit48pxOcr

        if Path(os.environ.get("MANGATL_MIT48_MODEL", DEFAULT_MODEL)).is_file():
            ocr = FusionOcr(Mit48pxOcr(), manga)
    except Exception:  # noqa: BLE001 - optional engine
        ocr = manga

    translator = EchoTranslator()
    if os.environ.get("MANGATL_API_KEY"):
        try:
            from mangatl.adapters.translators.openai_compat import (
                LlmConfig,
                OpenAiTranslator,
            )

            translator = OpenAiTranslator(LlmConfig.from_env())
        except Exception:  # noqa: BLE001 - keep echo when the provider is unusable
            translator = EchoTranslator()

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
        detector,
        ocr,
        MaskedInpainter(),
        translator=translator,
        bubble_detector=bubble_detector,
    )
