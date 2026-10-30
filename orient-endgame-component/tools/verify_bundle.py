#!/usr/bin/env python3
"""Verify this extracted component's listed bytes and local published tables.

No files are written, no external project is consulted and no network is used.
Build outputs created later may be unlisted; the manifest describes the bundle.
"""
from __future__ import annotations

import hashlib
import importlib.util
import json
import ntpath
from pathlib import Path, PurePosixPath
import re
import stat
import sys


def unique_object(pairs):
    value = {}
    for key, item in pairs:
        if key in value:
            raise ValueError("duplicate JSON key: " + key)
        value[key] = item
    return value


def relative_path(value):
    if not isinstance(value, str) or not value or "\\" in value or ":" in value:
        raise ValueError("bundle paths must be nonempty relative POSIX paths")
    path = PurePosixPath(value)
    if (not path.parts or path.is_absolute() or ntpath.splitdrive(value)[0]
            or any(part in (".", "..") for part in path.parts)
            or path.as_posix() != value):
        raise ValueError("unsafe or noncanonical bundle path: " + value)
    return path


def ordinary_file(root, relative):
    path = root
    for part in relative.parts:
        path = path / part
        if path.is_symlink():
            raise ValueError("symlinks are not bundle files: " + relative.as_posix())
    if not stat.S_ISREG(path.lstat().st_mode):
        raise ValueError("expected an ordinary file: " + relative.as_posix())
    if not path.resolve(strict=True).is_relative_to(root):
        raise ValueError("file escapes the bundle root: " + relative.as_posix())
    return path


def digest(path):
    before = path.stat()
    value = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            value.update(chunk)
    after = path.stat()
    if (before.st_dev, before.st_ino, before.st_size, before.st_mtime_ns) != (
            after.st_dev, after.st_ino, after.st_size, after.st_mtime_ns):
        raise ValueError("file changed during verification: " + str(path))
    return value.hexdigest(), after.st_size


def verify_bundle(root):
    root = Path(root).resolve(strict=True)
    manifest_path = ordinary_file(root, relative_path("BUNDLE-MANIFEST.json"))
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"), object_pairs_hook=unique_object)
    if (not isinstance(manifest, dict) or type(manifest.get("schema_version")) is not int
            or manifest["schema_version"] != 1):
        raise ValueError("expected bundle manifest schema_version 1")
    rows = manifest.get("files")
    if not isinstance(rows, list) or not rows:
        raise ValueError("bundle manifest must list its files")
    seen, total = set(), 0
    for row in rows:
        if not isinstance(row, dict) or not {"path", "size", "sha256"} <= set(row):
            raise ValueError("each bundle file needs path, size and sha256")
        relative = relative_path(row["path"])
        name = relative.as_posix()
        if name == "BUNDLE-MANIFEST.json":
            raise ValueError("the bundle manifest cannot include its own hash")
        if name in seen:
            raise ValueError("duplicate bundle file: " + name)
        seen.add(name)
        if type(row["size"]) is not int or row["size"] < 0:
            raise ValueError("invalid file size: " + name)
        if not isinstance(row["sha256"], str) or not re.fullmatch(r"[0-9a-fA-F]{64}", row["sha256"]):
            raise ValueError("invalid SHA-256: " + name)
        actual_hash, actual_size = digest(ordinary_file(root, relative))
        if actual_size != row["size"] or actual_hash != row["sha256"].lower():
            raise ValueError("bundle file size or checksum differs: " + name)
        total += actual_size

    dataset = manifest.get("dataset")
    if not isinstance(dataset, dict):
        raise ValueError("bundle manifest must identify its local table dataset")
    data_relative = relative_path(dataset.get("manifest"))
    if data_relative.as_posix() not in seen:
        raise ValueError("the dataset manifest must also be a listed bundle file")
    data_path = ordinary_file(root, data_relative)
    module_path = ordinary_file(root, relative_path("tools/tablebase_manifest.py"))
    if "tools/tablebase_manifest.py" not in seen or "tools/syzygy345.json" not in seen:
        raise ValueError("the local dataset verifier and publisher catalogue must be listed")
    spec = importlib.util.spec_from_file_location("orient_bundle_tablebase_manifest", module_path)
    if spec is None or spec.loader is None:
        raise ValueError("cannot load the bundled dataset verifier")
    verifier = importlib.util.module_from_spec(spec)
    # Import the local verifier without creating __pycache__ in the bundle.
    previous_bytecode_setting = sys.dont_write_bytecode
    sys.dont_write_bytecode = True
    try:
        spec.loader.exec_module(verifier)
    finally:
        sys.dont_write_bytecode = previous_bytecode_setting
    checked = verifier.verify_tablebase_manifest(data_path)
    expected_table_rows = json.loads(data_path.read_text(encoding="utf-8"))["files"]
    for row in expected_table_rows:
        name = (data_relative.parent / row["name"]).as_posix()
        if name not in seen:
            raise ValueError("a table file is absent from the bundle manifest: " + name)
    return {"status": "passed", "files": len(rows), "bytes": total,
            "dataset_files": checked["file_count"], "dataset_bytes": checked["total_bytes"],
            "scope": "all listed bundle files plus the published complete five-piece collection"}


def main():
    try:
        result = verify_bundle(Path(__file__).resolve().parents[1])
    except (OSError, ValueError, TypeError, KeyError, ImportError) as error:
        print("Bundle verification failed: " + str(error), file=sys.stderr)
        return 1
    print(json.dumps(result, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
