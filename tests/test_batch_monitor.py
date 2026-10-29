"""Batch monitor: page specs, event parsing, watchdog states and a real child run."""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
import uuid
from pathlib import Path

from PIL import Image

from mangatl.cli.main import parse_pages
from mangatl.gui.batch import (
    STATE_OK,
    STATE_SLOW,
    STATE_STUCK,
    parse_event,
    watchdog_state,
)

ROOT = Path(__file__).resolve().parents[1]


def test_parse_pages_accepts_ranges_and_lists() -> None:
    names = [f"{index:03d}.png" for index in range(1, 11)]

    assert parse_pages("", names) is None
    assert parse_pages("1-3", names) == set(names[:3])
    assert parse_pages("2,5,9-10", names) == {names[1], names[4], names[8], names[9]}
    assert parse_pages("0-99", names) == set(names)


def test_parse_event_ignores_noise() -> None:
    assert parse_event("Traceback (most recent call last):") is None
    assert parse_event('{"kind": "page-start", "page": "001.png"}') == {
        "kind": "page-start",
        "page": "001.png",
    }
    assert parse_event('{"not": "an event"}') is None
    assert parse_event("{broken json") is None


def test_watchdog_thresholds() -> None:
    assert watchdog_state(2, 60) == STATE_OK
    assert watchdog_state(30, 60) == STATE_SLOW
    assert watchdog_state(59.9, 60) == STATE_SLOW
    assert watchdog_state(60, 60) == STATE_STUCK
    assert watchdog_state(500, 60) == STATE_STUCK
    assert watchdog_state(500, 0) == STATE_OK


def test_child_process_streams_events() -> None:
    scratch = ROOT / ".tmp" / f"events-{uuid.uuid4().hex[:8]}"
    scratch.mkdir(parents=True)
    try:
        for name in ("001.png", "002.png"):
            Image.new("RGB", (200, 200), "white").save(scratch / name)
        command = [
            sys.executable,
            "-m",
            "mangatl",
            "run",
            str(scratch),
            "--stages",
            "detect,ocr",
            "--pages",
            "1",
            "--detector",
            "grid",
            "--ocr",
            "echo",
            "--events-json",
            "--heartbeat",
            "1",
        ]
        env = dict(os.environ)
        env["PYTHONIOENCODING"] = "utf-8"
        completed = subprocess.run(
            command,
            cwd=str(ROOT),
            capture_output=True,
            text=True,
            timeout=120,
            env=env,
        )
        assert completed.returncode == 0, completed.stderr
        events = [
            payload
            for line in completed.stdout.splitlines()
            if (payload := parse_event(line)) is not None
        ]
        kinds = [event["kind"] for event in events]
        assert "page-start" in kinds
        assert "stage-start" in kinds
        assert "page-done" in kinds
        assert "summary" in kinds
        assert events[-1]["ok"] == 1
        # --pages 1 keeps the second page untouched
        assert all(
            (event.get("page") or "") in {"", "001.png"} for event in events
        )
    finally:
        shutil.rmtree(scratch, ignore_errors=True)
