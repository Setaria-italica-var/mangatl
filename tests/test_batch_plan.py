"""Batch planning: which pages run, which are skipped as already done."""

from __future__ import annotations

from mangatl.domain.project import Page
from mangatl.gui.batch import plan_pages

STAGES = ("detect", "ocr", "translate", "erase", "render")


def _page(name: str, done: tuple[str, ...] = ()) -> Page:
    page = Page(name=name)
    for stage in done:
        page.stage[stage] = 1
    return page


def test_resume_skips_pages_with_all_stages_done() -> None:
    pages = [_page("001.png", STAGES), _page("002.png", ("detect",)), _page("003.png")]

    run, skip = plan_pages(pages, ("detect", "ocr"), 1, 3, resume=True, force=False)

    assert run == ["002.png", "003.png"]
    assert skip == ["001.png"]


def test_resume_only_checks_selected_stages() -> None:
    pages = [_page("001.png", ("detect",)), _page("002.png", STAGES)]

    run, skip = plan_pages(pages, ("detect",), 1, 2, resume=True, force=False)

    assert run == []
    assert skip == ["001.png", "002.png"]


def test_force_ignores_stage_flags() -> None:
    pages = [_page("001.png", STAGES), _page("002.png", STAGES)]

    run, skip = plan_pages(pages, STAGES, 1, 2, resume=True, force=True)

    assert run == ["001.png", "002.png"]
    assert skip == []


def test_range_is_inclusive_and_clipped() -> None:
    pages = [_page(str(index)) for index in range(1, 6)]

    run, _ = plan_pages(pages, STAGES, 2, 4, resume=False, force=False)

    assert run == ["2", "3", "4"]
    assert plan_pages(pages, STAGES, 4, 99, resume=False, force=False)[0] == ["4", "5"]
    assert plan_pages(pages, STAGES, 9, 20, resume=False, force=False)[0] == []


def test_no_resume_runs_everything_in_range() -> None:
    pages = [_page("001.png", STAGES), _page("002.png")]

    run, skip = plan_pages(pages, STAGES, 1, 2, resume=False, force=False)

    assert run == ["001.png", "002.png"]
    assert skip == []
