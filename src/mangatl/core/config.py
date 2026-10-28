"""Run configuration passed explicitly into the pipeline.

There is no module-level config object: callers own the instance, so tests and
future batch runs can hold different configurations side by side.

>>> RunConfig().stages
('detect', 'ocr', 'translate', 'erase', 'render')
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

STAGE_ORDER: tuple[str, ...] = ("detect", "ocr", "translate", "erase", "render")


@dataclass(frozen=True)
class RunConfig:
    """What to run and which adapters to use."""

    src_lang: str = "ja"
    tgt_lang: str = "zh-CN"
    stages: tuple[str, ...] = STAGE_ORDER
    detector: str = "grid"
    ocr: str = "echo"
    inpainter: str = "copy"
    translator: str = "echo"
    output_dirname: str = "inpainted"
    result_dirname: str = "result"
    force: bool = False
    sfx_policy: str = "erase"
    erase_background: bool = False
    extra: dict[str, str] = field(default_factory=dict)

    def __post_init__(self) -> None:
        unknown = [stage for stage in self.stages if stage not in STAGE_ORDER]
        if unknown:
            raise ValueError(f"unknown stages: {', '.join(unknown)}")
        if self.sfx_policy not in {"keep", "erase"}:
            raise ValueError(f"unknown sfx_policy: {self.sfx_policy}")

    @property
    def enabled(self) -> frozenset[str]:
        """Stages selected for this run."""
        return frozenset(self.stages)


def resolve(base: Path, candidate: str) -> Path:
    """Resolve ``candidate`` against ``base`` unless it is already absolute.

    >>> resolve(Path("/tmp/p"), "out").as_posix()
    '/tmp/p/out'
    """
    path = Path(candidate)
    return path if path.is_absolute() else base / path
