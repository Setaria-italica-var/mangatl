"""Tests for the model fetcher (URL building only; no network)."""

from __future__ import annotations

from pathlib import Path

from mangatl.tools.fetch import weight_files


def test_weight_files_builds_mirror_urls() -> None:
    info = {
        "siblings": [
            {"rfilename": "best.pt"},
            {"rfilename": "config.yaml"},
            {"rfilename": "README.md"},
            {"rfilename": ".gitattributes"},
        ]
    }

    files = weight_files(info, "https://hf-mirror.com", "ogkalu/comic-speech-bubble-detector")

    names = [name for name, _url in files]
    assert names == ["best.pt", "config.yaml"]
    assert files[0][1] == (
        "https://hf-mirror.com/ogkalu/comic-speech-bubble-detector/resolve/main/best.pt"
    )


def test_weight_files_skips_docs_and_git_metadata() -> None:
    info = {
        "siblings": [
            {"rfilename": "LICENSE"},
            {"rfilename": "notes.md"},
            {"rfilename": "model.onnx"},
        ]
    }

    names = [name for name, _url in weight_files(info, "https://hf-mirror.com", "x/y")]

    assert names == ["model.onnx"]


def test_weight_files_handles_endpoint_with_trailing_slash() -> None:
    info = {"siblings": [{"rfilename": "best.pt"}]}

    files = weight_files(info, "https://hf-mirror.com/", "a/b")

    assert files[0][1].startswith("https://hf-mirror.com/a/b/resolve/main/")


def test_destination_layout_is_flat(tmp_path: Path) -> None:
    info = {"siblings": [{"rfilename": "sub/best.pt"}]}

    files = weight_files(info, "https://hf-mirror.com", "a/b")

    assert files[0][0] == "sub/best.pt"
