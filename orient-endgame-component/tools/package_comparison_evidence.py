#!/usr/bin/env python3
"""Package original 006 numeric evidence without tables or external engine code."""
from __future__ import annotations

import argparse
import gzip
import hashlib
import io
import json
from pathlib import Path
import tarfile

from verify_public_evidence import digest, read_json


COMPONENT = Path(__file__).resolve().parents[1]
CAMPAIGN = Path("artifacts/investigations/tablebases-006")
PREFIX = "skylance-evidence-006"
ASSET = PREFIX + ".tar.gz"
RELEASE = "https://github.com/Aurentium-Technologies/SkyLance_Endgame/releases/download/v0.1.0/"


def numeric_payload(relative):
    return (relative.suffix.lower() in (".json", ".jsonl", ".stdout", ".stderr", ".u64", ".csv", ".fen", ".txt", ".md")
            and not {"build", "target", "__pycache__", "cargo-cache"}.intersection(relative.parts))


def select_files(component):
    component = Path(component).resolve(strict=True)
    campaign = component / CAMPAIGN
    freeze = read_json(campaign / "protocol/freeze.json")
    original = Path(freeze["dataset"]["path"].split("/external/tablebases/")[0])
    selected = set()

    def add(relative):
        relative = Path(relative)
        if relative.is_absolute() or ".." in relative.parts:
            raise ValueError("unsafe package path: " + str(relative))
        path = component / relative
        if path.is_symlink() or not path.is_file():
            raise ValueError("missing ordinary comparison evidence: " + str(relative))
        if path.suffix.lower() in (".rtbw", ".rtbz", ".rtbm", ".pyc"):
            raise ValueError("table data/bytecode is not comparison evidence")
        selected.add(relative)

    for folder in ("performance/run001", "protocol", "fixtures", "verification"):
        for path in sorted((campaign / folder).rglob("*")):
            relative = path.relative_to(campaign)
            if path.is_file() and numeric_payload(relative):
                add(CAMPAIGN / relative)
    for name in ("PROTOCOL.md", "README.md", "final_audit.py", "campaign.py", "report.py",
                 "independent-audit-preflight.md", "independent-audit-final.json"):
        add(CAMPAIGN / name)
    for path in sorted((campaign / "sources").glob("*.json")):
        add(path.relative_to(component))

    def original_relative(record):
        path = Path(record["path"])
        if not path.is_absolute() or not path.is_relative_to(original):
            raise ValueError("recorded input is outside the original component")
        return path.relative_to(original)

    proof = read_json(campaign / "verification/result.json")
    for group in proof["groups"].values():
        add(original_relative(group["corpus"]))
        for record in group["outputs"].values():
            add(original_relative(record))
    add(original_relative(freeze["dataset"]))  # manifest only, never its table bytes
    for name in ("LICENSE", "tools/verify_comparison_evidence.py", "tools/verify_public_evidence.py"):
        add(name)

    omitted = []
    for role, record in [("binary/reader identity", r) for r in freeze["binaries"].values()] + [
            ("original source/build/input binding", r) for r in freeze["inputs"]]:
        if original_relative(record) not in selected:
            omitted.append({"role": role, **record})
    return component, original, sorted(selected), omitted


def build(component, public, out, force=False):
    component, original, selected, omitted = select_files(component)
    out = Path(out); out.mkdir(parents=True, exist_ok=True)
    archive = out / ASSET
    if archive.exists() and not force:
        raise ValueError("release archive exists; use --force only to rebuild the generated asset")
    rows = [{"path": "orient-endgame-component/" + path.as_posix(),
             "size": (component / path).stat().st_size, "sha256": digest(component / path)} for path in selected]
    unpublished = (json.dumps({"scope": "Recorded historical bindings whose payloads are deliberately excluded; not validated as present by the numeric audit",
                              "records": omitted}, indent=2, sort_keys=True) + "\n").encode()
    readme = b'''# Frozen 006 raw numeric evidence

This archive includes the original 540 primary samples, uint64 little-endian
query-latency sidecars, per-material/aggregate summaries, block fixtures, raw
correctness output and frozen protocols/source pins. It contains no actual
Syzygy tables, external engine source or binaries, model weights or build trees.

After checking the separately published archive SHA-256 and extracting:

    python3 -m venv .audit-venv
    .audit-venv/bin/python -m pip install numpy
    .audit-venv/bin/python orient-endgame-component/tools/verify_comparison_evidence.py --bundle-root .

The verifier checks all listed payload hashes, the original pinned independent
auditor, exact FEN-bound correctness outputs, every original-order latency array,
per-query quantiles, histograms, 1,980 per-material summaries and the fixed
100,000 whole-block bootstrap draws with seed 2026102906. It recomputes all 15
verdicts under the original wall-upper<0.95 and p95-upper<1.05 rules.

Original absolute paths remain immutable identifiers; relocation is in memory.
The numeric audit executes no reader and does not validate the existence/content
of excluded historical binary or source archives. Their original hashes/pins
remain in protocol/freeze.json and UNPUBLISHED-BINDINGS.json. This is not a new
benchmark, hardware replication, complete reader-build environment or Elo claim.
Supplementary descriptive task data is retained but is outside primary verdicts.
'''
    extras = {"README.md": readme, "UNPUBLISHED-BINDINGS.json": unpublished}
    rows += [{"path": name, "size": len(data), "sha256": hashlib.sha256(data).hexdigest()}
             for name, data in extras.items()]
    manifest = {"schema_version": 1, "kind": "skylance-006-comparison-evidence",
                "original_component_root": str(original), "files": rows,
                "scope": "Complete frozen 006 primary numeric/correctness audit; recorded-only excluded binary/source bindings",
                "excluded": ["actual table data", "external reader source and binaries", "weights", "build trees and caches"]}
    temporary = archive.with_suffix(archive.suffix + ".tmp")
    with temporary.open("wb") as raw, gzip.GzipFile(filename="", mode="wb", fileobj=raw, mtime=0) as compressed, tarfile.open(fileobj=compressed, mode="w") as tar:
        for row in rows:
            path = row["path"]
            data = extras[path] if path in extras else (component / Path(path).relative_to("orient-endgame-component")).read_bytes()
            if hashlib.sha256(data).hexdigest() != row["sha256"]:
                raise ValueError("package input changed: " + path)
            member = tarfile.TarInfo(PREFIX + "/" + path)
            member.size, member.mode, member.mtime = len(data), 0o644, 0
            tar.addfile(member, io.BytesIO(data))
        data = (json.dumps(manifest, indent=2, sort_keys=True) + "\n").encode()
        member = tarfile.TarInfo(PREFIX + "/EVIDENCE-MANIFEST.json")
        member.size, member.mode, member.mtime = len(data), 0o644, 0
        tar.addfile(member, io.BytesIO(data))
    temporary.replace(archive)
    checksum = digest(archive)
    (out / (ASSET + ".sha256")).write_text(checksum + "  " + ASSET + "\n", encoding="utf-8")
    descriptor = {"filename": ASSET, "bytes": archive.stat().st_size, "sha256": checksum,
                  "url": RELEASE + ASSET, "checksum_url": RELEASE + ASSET + ".sha256"}
    public = Path(public)
    index = read_json(public / "MANIFEST.json")
    index["comparison_release"] = descriptor
    index["scope"] = "Immutable historical 006 index plus separately checksummed raw numeric/correctness audit archive; external binary/source payloads excluded"
    (public / "MANIFEST.json").write_text(json.dumps(index, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return {"archive": str(archive), **descriptor, "files": len(rows),
            "uncompressed_bytes": sum(row["size"] for row in rows), "excluded_binding_records": len(omitted)}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--component-root", type=Path, default=COMPONENT)
    parser.add_argument("--public-dir", type=Path, default=COMPONENT.parent / "evidence/tablebases-006")
    parser.add_argument("--out", type=Path, default=COMPONENT.parent / "dist")
    parser.add_argument("--force", action="store_true")
    args = parser.parse_args()
    try:
        print(json.dumps(build(args.component_root, args.public_dir, args.out, args.force), indent=2))
    except (OSError, ValueError, TypeError, KeyError) as error:
        parser.exit(1, "Comparison evidence packaging failed: " + str(error) + "\n")


if __name__ == "__main__":
    main()
