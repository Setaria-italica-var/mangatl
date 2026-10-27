"""Run configuration passed explicitly into the pipeline.

There is no module-level config object: callers own the instance, so tests and
future batch runs can hold different configurations side by side.

>>> RunConfig().stages
('detect', 'ocr', 'erase')
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

STAGE_ORDER: tuple[str, ...] = ("detect", "ocr", "erase")


@dataclass(frozen=True)
class RunConfig:
    """What to run and which adapters to use."""

    src_lang: str = "ja"
    tgt_lang: str = "zh-CN"
    stages: tuple[str, ...] = STAGE_ORDER
    detector: str = "grid"
    ocr: str = "echo"
    inpainter: str = "copy"
    output_dirname: str = "inpainted"
    force: bool = False
    extra: dict[str, str] = field(default_factory=dict)

    def __post_init__(self) -> None:
        unknown = [stage for stage in self.stages if stage not in STAGE_ORDER]
        if unknown:
            raise ValueError(f"unknown stages: {', '.join(unknown)}")

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
