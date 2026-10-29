"""End-to-end test of the stub pipeline: no models, no network, no Qt."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from mangatl.adapters.stubs import CopyInpainter, EchoOcr, GridDetector
from mangatl.core.config import RunConfig
from mangatl.core.pipeline import (
    EVENT_PAGE_DONE,
    EVENT_PAGE_FAILED,
    EVENT_PAGE_SKIPPED,
    PipelineService,
)
from mangatl.domain.project import Project


def write_page(path: Path) -> None:
    """Real PNG: the pipeline measures page size, so signature-only bytes fail."""
    from PIL import Image

    Image.new("RGB", (200, 200), "white").save(path)


@pytest.fixture()
def project(tmp_path: Path) -> Project:
    for name in ("001.png", "002.png"):
        write_page(tmp_path / name)
    return Project.open(tmp_path)


def make_service(project: Project, events: list | None = None) -> PipelineService:
    return PipelineService(
        project=project,
        detector=GridDetector(columns=2, rows=2),
        ocr=EchoOcr(),
        inpainter=CopyInpainter(),
        on_event=events.append if events is not None else None,
    )


def test_pipeline_runs_all_stages(project: Project) -> None:
    # Merging is a separate feature; this test counts the raw grid boxes.
    summary = make_service(project).run(RunConfig(merge_fragments=False))

    assert summary.total == 2
    assert summary.ok == 2
    assert summary.failed == 0
    assert summary.blocks == 8  # 2 pages x 2x2 grid

    payload = json.loads((project.directory / "project.json").read_text(encoding="utf-8"))
    page = payload["pages"]["001.png"]
    assert page["stage"] == {
        "detect": 1,
        "ocr": 1,
        "translate": 1,
        "erase": 1,
        "render": 1,
    }
    assert page["blocks"][0]["text"] == "001#0"
    assert (project.directory / "inpainted" / "001.png").is_file()


def test_pipeline_skips_finished_stages(project: Project) -> None:
    make_service(project).run(RunConfig())
    events: list = []
    summary = make_service(project, events).run(RunConfig())

    assert summary.ok == 0
    assert summary.skipped == 2
    assert summary.failed == 0
    assert [event.kind for event in events] == [EVENT_PAGE_SKIPPED, EVENT_PAGE_SKIPPED]


def test_force_reruns_stages(project: Project) -> None:
    make_service(project).run(RunConfig(merge_fragments=False))
    summary = make_service(project).run(
        RunConfig(force=True, merge_fragments=False)
    )

    assert summary.ok == 2
    assert summary.blocks == 8


def test_bad_page_is_isolated(tmp_path: Path) -> None:
    write_page(tmp_path / "001.png")
    write_page(tmp_path / "002.png")
    project = Project.open(tmp_path)

    class ExplodingDetector(GridDetector):
        def detect(self, image_path: Path):  # noqa: ANN201 - test double
            if image_path.name == "002.png":
                raise RuntimeError("boom")
            return super().detect(image_path)

    events: list = []
    service = PipelineService(
        project=project,
        detector=ExplodingDetector(),
        ocr=EchoOcr(),
        inpainter=CopyInpainter(),
        on_event=events.append,
    )
    summary = service.run(RunConfig())

    assert summary.ok == 1
    assert summary.failed == 1
    assert [event.kind for event in events].count(EVENT_PAGE_FAILED) == 1
    assert (project.directory / "inpainted" / "001.png").is_file()


def test_missing_directory_raises(tmp_path: Path) -> None:
    with pytest.raises(FileNotFoundError):
        Project.open(tmp_path / "nope")


def test_unknown_stage_rejected() -> None:
    with pytest.raises(ValueError):
        RunConfig(stages=("detect", "bogus"))


def test_page_done_events(project: Project) -> None:
    events: list = []
    make_service(project, events).run(RunConfig())
    done = [event.page for event in events if event.kind == EVENT_PAGE_DONE]
    assert done == ["001.png", "002.png"]
