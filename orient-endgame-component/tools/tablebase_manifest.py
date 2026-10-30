"""Strict, offline verifier for the pinned complete Syzygy three-to-five set."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path

CATALOGUE = Path(__file__).with_name("syzygy345.json")


def sha256(path):
    digest = hashlib.sha256()
    with Path(path).open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def catalogue():
    data = json.loads(CATALOGUE.read_text(encoding="utf-8"))
    return {item["name"]: item for item in data["files"]}


def verify_tablebase_manifest(path):
    """Verify all bytes against the bundled publisher catalogue; raise ValueError."""
    original = Path(path)
    if original.is_symlink():
        raise ValueError("Tablebase manifest must not be a symlink")
    path = original.resolve(strict=True)
    data = json.loads(path.read_text(encoding="utf-8"))
    if (not isinstance(data, dict) or type(data.get("schema_version")) is not int
            or data.get("schema_version") != 1 or data.get("kind") != "syzygy"
            or type(data.get("max_pieces")) is not int
            or data.get("max_pieces") != 5 or data.get("complete") is not True
            or data.get("root") != "."):
        raise ValueError("Expected complete local five-piece Syzygy manifest")
    expected = catalogue()
    rows = data.get("files")
    if not isinstance(rows, list) or len(rows) != len(expected):
        raise ValueError("Tablebase manifest must contain the complete 290-file set")
    names = [item.get("name") for item in rows if isinstance(item, dict)]
    if (len(names) != len(rows) or not all(isinstance(name, str) for name in names)
            or len(set(names)) != len(names) or set(names) != set(expected)):
        raise ValueError("Tablebase manifest file names differ from pinned complete set")
    root = path.parent
    total = 0
    for item in rows:
        reference = expected[item["name"]]
        published = item.get("published_checksum", {})
        if (type(item.get("size")) is not int or item.get("size") != reference["size"]
                or item.get("sha256") != reference["sha256"]
                or published != {"algorithm": "sha256", "value": reference["sha256"]}
                or item.get("source_url") != reference["source_url"]):
            raise ValueError("Tablebase metadata differs from publisher: " + item["name"])
        table = root / item["name"]
        if table.is_symlink() or not table.is_file() or table.resolve().parent != root:
            raise ValueError("Tablebase must be an ordinary local file: " + item["name"])
        if table.stat().st_size != reference["size"] or sha256(table) != reference["sha256"]:
            raise ValueError("Tablebase checksum or size mismatch: " + item["name"])
        total += reference["size"]
    if data.get("total_bytes") != total:
        raise ValueError("Tablebase manifest total byte count differs")
    return {"manifest": {"path": str(path), "sha256": sha256(path)},
            "root": str(root), "max_pieces": 5, "complete": True,
            "file_count": len(rows), "total_bytes": total}
