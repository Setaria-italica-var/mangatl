"""Shared test setup.

``MANGATL_TEST_TMP`` can redirect pytest's temp root when the default one is not
writable (for example inside a restricted sandbox). By default pytest uses its
normal per-user temp directory.
"""

from __future__ import annotations

import os
import tempfile

_SCRATCH = os.environ.get("MANGATL_TEST_TMP")
if _SCRATCH:
    from pathlib import Path

    Path(_SCRATCH).mkdir(parents=True, exist_ok=True)
    tempfile.tempdir = _SCRATCH
    os.environ["TMPDIR"] = _SCRATCH
    os.environ["TEMP"] = _SCRATCH
    os.environ["TMP"] = _SCRATCH
