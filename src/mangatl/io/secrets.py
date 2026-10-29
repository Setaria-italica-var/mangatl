"""Protect the translator API key with Windows DPAPI.

DPAPI ties the ciphertext to the current Windows user (and machine), so the key file
is useless if copied elsewhere and nothing is written in plain text. On non-Windows
platforms the functions return ``None`` and the GUI keeps the key in memory only.
"""

from __future__ import annotations

import base64
import ctypes
import json
import os
from ctypes import wintypes
from pathlib import Path

CRYPTPROTECT_UI_FORBIDDEN = 0x1


class _Blob(ctypes.Structure):
    _fields_ = [
        ("cbData", wintypes.DWORD),
        ("pbData", ctypes.POINTER(ctypes.c_char)),
    ]


def _make_blob(data: bytes) -> _Blob:
    buffer = ctypes.create_string_buffer(data, len(data))
    return _Blob(len(data), ctypes.cast(buffer, ctypes.POINTER(ctypes.c_char)))


def protect(text: str) -> bytes | None:
    """Encrypt with DPAPI for the current user."""
    if os.name != "nt" or not text:
        return None
    crypt32 = ctypes.windll.crypt32
    kernel32 = ctypes.windll.kernel32
    source = _make_blob(text.encode("utf-8"))
    entropy = _make_blob(b"mangatl")
    result = _Blob()
    ok = crypt32.CryptProtectData(
        ctypes.byref(source),
        None,
        ctypes.byref(entropy),
        None,
        None,
        CRYPTPROTECT_UI_FORBIDDEN,
        ctypes.byref(result),
    )
    if not ok:
        return None
    try:
        return ctypes.string_at(result.pbData, result.cbData)
    finally:
        kernel32.LocalFree(result.pbData)


def unprotect(data: bytes) -> str | None:
    """Decrypt a DPAPI blob created by :func:`protect`."""
    if os.name != "nt" or not data:
        return None
    crypt32 = ctypes.windll.crypt32
    kernel32 = ctypes.windll.kernel32
    source = _make_blob(data)
    entropy = _make_blob(b"mangatl")
    result = _Blob()
    ok = crypt32.CryptUnprotectData(
        ctypes.byref(source),
        None,
        ctypes.byref(entropy),
        None,
        None,
        CRYPTPROTECT_UI_FORBIDDEN,
        ctypes.byref(result),
    )
    if not ok:
        return None
    try:
        return ctypes.string_at(result.pbData, result.cbData).decode("utf-8")
    finally:
        kernel32.LocalFree(result.pbData)


def save_key(path: Path, api_key: str) -> bool:
    """Write the encrypted key atomically; returns False when unsupported."""
    blob = protect(api_key)
    if blob is None:
        return False
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {"api_key": base64.b64encode(blob).decode("ascii")}
    temp = path.with_name(path.name + ".tmp")
    temp.write_text(json.dumps(payload), encoding="utf-8")
    os.replace(temp, path)
    return True


def load_key(path: Path) -> str | None:
    """Read and decrypt the stored key; never raises."""
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
        blob = base64.b64decode(raw.get("api_key", ""))
    except (OSError, ValueError, KeyError):
        return None
    return unprotect(blob)


def clear_key(path: Path) -> None:
    path.unlink(missing_ok=True)
