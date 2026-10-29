"""Shared test setup: keep temporary files inside the workspace.

The system temp directory is not writable in sandboxed runs, so point both
``tempfile`` and pytest at ``.tmp/`` before any test imports something that writes.
"""

from __future__ import annotations

import os
import tempfile
from pathlib import Path

_SCRATCH = Path(__file__).resolve().parents[1] / ".tmp" / "pytest-tmp"
_SCRATCH.mkdir(parents=True, exist_ok=True)
tempfile.tempdir = str(_SCRATCH)
os.environ["TMPDIR"] = str(_SCRATCH)
os.environ["TEMP"] = str(_SCRATCH)
os.environ["TMP"] = str(_SCRATCH)
