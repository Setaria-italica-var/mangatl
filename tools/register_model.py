"""Fill a model's sha256 and size in ``models/manifest.json`` after download.

Usage:
    python tools/register_model.py data/models/bubble_detector.onnx --name bubble_detector

Keeps the manifest sorted by name and prints the entry it wrote.
"""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path

MANIFEST = Path("models/manifest.json")


def digest(path: Path) -> tuple[str, int]:
    """Return the sha256 and byte size of a file."""
    hasher = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1 << 20), b""):
            hasher.update(chunk)
    return hasher.hexdigest(), path.stat().st_size


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("model", type=Path)
    parser.add_argument("--name", required=True)
    parser.add_argument("--license", default="")
    parser.add_argument("--url", action="append", default=[])
    parser.add_argument("--manifest", type=Path, default=MANIFEST)
    args = parser.parse_args()

    if not args.model.is_file():
        print(f"error: {args.model} does not exist")
        return 2

    sha256, size = digest(args.model)
    data = json.loads(args.manifest.read_text(encoding="utf-8"))
    entries = [item for item in data["models"] if item.get("name") != args.name]
    entry = {
        "name": args.name,
        "file": str(args.model).replace("\\", "/"),
        "license": args.license,
        "urls": args.url,
        "sha256": sha256,
        "size": size,
    }
    entries.append(entry)
    entries.sort(key=lambda item: item["name"])
    data["models"] = entries

    temporary = args.manifest.with_suffix(".json.tmp")
    temporary.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    temporary.replace(args.manifest)
    print(json.dumps(entry, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
