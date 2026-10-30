#!/usr/bin/env python3
"""Freeze an original Orient binary, source archive and build provenance."""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import pathlib
import re
import shlex
import shutil
import subprocess
import tarfile
from datetime import datetime, timezone

from tablebase_manifest import verify_tablebase_manifest

ROOT = pathlib.Path(__file__).resolve().parents[1]


def digest(path):
    h = hashlib.sha256()
    with pathlib.Path(path).open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            h.update(block)
    return h.hexdigest()


def command(args):
    result = subprocess.run(args, cwd=ROOT, capture_output=True, text=True, check=False)
    return {"argv": args, "exit_code": result.returncode,
            "stdout": result.stdout.strip(), "stderr": result.stderr.strip()}


def source_files():
    paths = [ROOT / name for name in ("CMakeLists.txt", "CMakePresets.json", "LICENSE", "README.md")]
    for directory in ("src", "include", "tests", "tools", "docs", "learning", "third_party/fathom"):
        for path in sorted((ROOT / directory).rglob("*")):
            if path.is_file() and "__pycache__" not in path.parts and path.suffix != ".pyc":
                paths.append(path)
    return sorted(path for path in paths if path.is_file())


def build_reproduction(preset):
    """Retain legacy presets, or describe this component's explicit build."""
    if (ROOT / "CMakePresets.json").is_file():
        return [shlex.join(["cmake", "--preset", preset]),
                shlex.join(["cmake", "--build", "--preset", preset])]
    build = pathlib.Path("build") / preset
    options = {"CMAKE_BUILD_TYPE": "Release"}
    cache = ROOT / build / "CMakeCache.txt"
    if cache.is_file():
        for line in cache.read_text(encoding="utf-8").splitlines():
            match = re.fullmatch(r"(CMAKE_BUILD_TYPE|ORIENT_[A-Z0-9_]+):(BOOL|STRING)=(.*)", line)
            if match:
                options[match[1]] = match[3]
    configure = ["cmake", "-S", ".", "-B", str(build)]
    configure.extend(f"-D{name}={value}" for name, value in sorted(options.items()))
    return [shlex.join(configure), shlex.join(["cmake", "--build", str(build)])]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--binary", required=True)
    parser.add_argument("--out", required=True, help="New checkpoint directory")
    parser.add_argument("--label", required=True)
    parser.add_argument("--preset", default="release")
    parser.add_argument("--test-log", help="Optional CTest LastTest.log from this build")
    parser.add_argument("--extra-binary", action="append", default=[], help="Additional executable built from this source tree")
    parser.add_argument("--tablebase-manifest", help="Verified complete local five-piece Syzygy manifest")
    parser.add_argument("--syzygy-cache", type=int, default=0, help="Pinned WDL cache size in MiB (0..256)")
    args = parser.parse_args()
    if not 0 <= args.syzygy_cache <= 256:
        raise SystemExit("--syzygy-cache must be between 0 and 256 MiB")
    if args.syzygy_cache and not args.tablebase_manifest:
        raise SystemExit("--syzygy-cache requires --tablebase-manifest")
    tables = verify_tablebase_manifest(args.tablebase_manifest) if args.tablebase_manifest else None
    binary = pathlib.Path(args.binary).resolve(strict=True)
    if not os.access(binary, os.X_OK):
        raise SystemExit("Binary is not executable")
    out = pathlib.Path(args.out).resolve()
    out.mkdir(parents=True, exist_ok=False)
    files = source_files()
    hashes = {str(path.relative_to(ROOT)): digest(path) for path in files}
    target = out / "orient"
    shutil.copy2(binary, target)
    archive = out / "source.tar.gz"
    with tarfile.open(archive, "w:gz") as tar:
        for path in files:
            tar.add(path, arcname=str(path.relative_to(ROOT)), recursive=False)
    if any(digest(ROOT / name) != value for name, value in hashes.items()):
        raise SystemExit("Sources changed while freezing: incomplete checkpoint must not be used")
    record = {"schema_version": 1, "label": args.label,
              "created_utc": datetime.now(timezone.utc).isoformat(),
              "binary": {"path": str(target), "sha256": digest(target),
                         "original_path": str(binary)},
              "source_archive": {"path": str(archive), "sha256": digest(archive)},
              "sources": hashes, "preset": args.preset,
              "additional_binaries": {},
              "compiler": command(["c++", "--version"]),
              "cmake": command(["cmake", "--version"]),
              "version": command([str(target), "--version"]),
              "git": command(["git", "status", "--short"]),
              "reproduction": build_reproduction(args.preset)}
    if tables is not None:
        manifest_copy = out / "tablebase-manifest.json"
        shutil.copy2(tables["manifest"]["path"], manifest_copy)
        record["tablebases"] = {**tables,
            "manifest_copy": {"path": str(manifest_copy), "sha256": digest(manifest_copy)},
            "options": {"SyzygyProbeLimit": 5, "SyzygyCache": args.syzygy_cache}}
        upstream = ROOT / "third_party" / "fathom" / "UPSTREAM.json"
        if upstream.is_file():
            record["tablebases"]["reader"] = json.loads(upstream.read_text(encoding="utf-8"))
    for value in args.extra_binary:
        extra = pathlib.Path(value).resolve(strict=True)
        if extra.name == "orient" or extra.name in record["additional_binaries"] or not os.access(extra, os.X_OK):
            raise SystemExit("Additional binary needs a unique executable basename")
        destination = out / extra.name
        shutil.copy2(extra, destination)
        record["additional_binaries"][extra.name] = {"path": str(destination), "sha256": digest(destination)}
    build = ROOT / "build" / args.preset
    for filename in ("CMakeCache.txt", "compile_commands.json", "build.ninja"):
        path = build / filename
        if path.is_file():
            shutil.copy2(path, out / filename)
    if args.test_log:
        log = pathlib.Path(args.test_log).resolve(strict=True)
        shutil.copy2(log, out / "LastTest.log")
        record["test_log"] = {"path": str(out / "LastTest.log"), "sha256": digest(out / "LastTest.log")}
    # The complete manifest is the checkpoint's readiness marker.
    with (out / "checkpoint.json").open("x") as stream:
        json.dump(record, stream, indent=2, sort_keys=True)
        stream.write("\n")
    print(json.dumps({"binary": str(target), "sha256": record["binary"]["sha256"],
                      "manifest": str(out / "checkpoint.json")}))


if __name__ == "__main__":
    main()
