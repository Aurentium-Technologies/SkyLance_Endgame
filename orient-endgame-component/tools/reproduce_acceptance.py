#!/usr/bin/env python3
"""Freeze and test a selected current source against the unchanged 007 gates.

The historical 007 reproducer intentionally selects historical snapshots. This
controller accepts an explicit candidate, freezes it, and binds every measured
binary to that new source manifest. It never edits an existing campaign.
"""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tarfile

from experiment import artifact, compute_lease, write_json
from tablebase_manifest import verify_tablebase_manifest

ROOT = Path(__file__).resolve().parents[1]
SOURCE_DIRS = ("src", "include", "third_party/fathom", "tools", "tests", "external/fathom-upstream")
SOURCE_TOP = ("CMakeLists.txt", "CMakePresets.json", "LICENSE", "README.md")


def digest(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def verify_snapshot(snapshot, manifest):
    rows = manifest.get("files")
    if not isinstance(rows, list) or not rows:
        raise ValueError("source snapshot must contain files")
    seen = set()
    for row in rows:
        relative = Path(row["path"])
        if relative.is_absolute() or ".." in relative.parts or relative.as_posix() in seen:
            raise ValueError("unsafe or duplicate source snapshot path")
        seen.add(relative.as_posix())
        path = snapshot / relative
        if path.is_symlink() or not path.is_file() or path.stat().st_size != row["size"] or digest(path) != row["sha256"]:
            raise ValueError("frozen source changed: " + str(relative))
    actual = {p.relative_to(snapshot).as_posix() for p in snapshot.rglob("*") if p.is_file()}
    if actual != seen:
        raise ValueError("source snapshot has unlisted files")


def freeze_source(source, out, role):
    source, out = Path(source).resolve(), Path(out).resolve()
    target, record = out / "sources" / role, out / (role + "-source.json")
    if target.exists() or record.exists():
        if not target.is_dir() or not record.is_file():
            raise ValueError("incomplete existing source snapshot")
        value = json.loads(record.read_text())
        if value.get("role") != role or value.get("source") != str(source):
            raise ValueError("existing snapshot has a different source or role")
        verify_snapshot(target, value)
        return target
    if not (source / "CMakeLists.txt").is_file() or not (source / "src/search.cpp").is_file():
        raise ValueError("candidate/baseline must be a complete component source")
    target.mkdir(parents=True, exist_ok=False)
    paths = []
    for directory in SOURCE_DIRS:
        base = source / directory
        for path in sorted(base.rglob("*")) if base.is_dir() else []:
            if "__pycache__" in path.parts or "target" in path.parts or path.suffix in (".pyc", ".pyo"):
                continue
            if path.is_symlink():
                raise ValueError("source snapshot refuses symlinks: " + str(path))
            if path.is_file():
                paths.append(path)
    paths += [source / name for name in SOURCE_TOP if (source / name).is_file()]
    rows = []
    for path in sorted(paths):
        relative = path.relative_to(source)
        destination = target / relative
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(path, destination)
        rows.append({"path": relative.as_posix(), "size": destination.stat().st_size, "sha256": digest(destination)})
    git = subprocess.run(["git", "rev-parse", "HEAD"], cwd=source, text=True, capture_output=True)
    value = {"schema_version": 1, "role": role, "source": str(source),
             "git_base": git.stdout.strip() if git.returncode == 0 else None,
             "frozen_at_utc": datetime.now(timezone.utc).isoformat(), "files": rows}
    write_json(record, value)
    verify_snapshot(target, value)
    return target


def remap_root(value, oldroot, newroot):
    if isinstance(value, dict):
        return {k: remap_root(v, oldroot, newroot) for k, v in value.items()}
    if isinstance(value, list):
        return [remap_root(v, oldroot, newroot) for v in value]
    if isinstance(value, str) and value.startswith(str(oldroot) + "/"):
        return str(newroot) + value[len(str(oldroot)):]
    return value


def run(argv, label, out, cwd):
    with (out / (label + ".log")).open("x") as log:
        subprocess.run([str(x) for x in argv], stdout=log, stderr=subprocess.STDOUT, check=True, cwd=cwd)
    print(label + " complete", flush=True)


def prepare(args, out, historical, dataset):
    if (out / "correctness-config.json").exists():
        raise ValueError("prepared campaign exists; choose a new output directory")
    out.mkdir(parents=True, exist_ok=True)
    baseline = args.baseline_source or historical / "baseline-source"
    sources = {"baseline": freeze_source(baseline, out, "baseline"),
               "candidate": freeze_source(args.candidate_source, out, "candidate")}
    protocol = out / "protocol"; protocol.mkdir(exist_ok=False)
    original = (historical / "protocol/PROTOCOL.md").read_text()
    (protocol / "PROTOCOL.md").write_text(
        "# Investigation 008: post-review source confirmation\n\n"
        "Apply the unchanged 007 workloads, five AB/BA pairs and numerical gates\n"
        "below to the frozen pre-007 baseline and explicitly selected current\n"
        "candidate. Preserve every sample and failed run. This is a new run, not\n"
        "a replacement for historical 007 evidence or a competitor/Elo claim.\n"
        "The base commit identifies the checkout; per-file source hashes bind the\n"
        "actual compiled snapshot, including any intentional uncommitted files.\n\n"
        + original)
    variants = {}
    with compute_lease("reader-008-source-builds"):
        for name, source in sources.items():
            dirs = {}
            for kind in ("native", "diagnostic"):
                build = out / "build" / (name + "-" + kind); dirs[kind] = build
                run(["cmake", "-S", source, "-B", build, "-DCMAKE_BUILD_TYPE=Release", "-DORIENT_NATIVE=ON",
                     "-DORIENT_FATHOM_DYNAMIC_CATALOG=" + ("ON" if name == "candidate" else "OFF"),
                     "-DORIENT_FATHOM_FIVE_PIECE_CATALOG=OFF", "-DORIENT_FATHOM_DIAGNOSTICS=" + ("ON" if kind == "diagnostic" else "OFF")],
                    name + "-" + kind + "-configure", out, source)
                targets = (["orient-reader-memory"] if kind == "diagnostic" else
                           ["orient", "orient-reader-compare", "orient-tablebase-ordered-probe", "orient-tablebase-bench"])
                run(["cmake", "--build", build, "--parallel", args.jobs, "--target", *targets],
                    name + "-" + kind + "-build", out, source)
            native, diagnostic = dirs["native"], dirs["diagnostic"]
            row = {k: artifact(native / f) for k, f in {"engine": "orient", "reader": "orient-reader-compare",
                   "probe": "orient-tablebase-ordered-probe", "search": "orient-tablebase-bench",
                   "build_cache": "CMakeCache.txt", "compile_commands": "compile_commands.json"}.items()}
            row.update({k: artifact(diagnostic / f) for k, f in {"diagnostics": "orient-reader-memory",
                        "diag_build_cache": "CMakeCache.txt", "diag_compile_commands": "compile_commands.json"}.items()})
            row.update(io="mmap", profiling_enabled=False, diagnostics_enabled=False); variants[name] = row
        upstream = out / "build/upstream-ordered"
        run(["g++-13", "-std=c++20", "-O3", "-DNDEBUG", "-march=native", "-pthread", "-DORIENT_REFERENCE_READER", "-DTB_NO_HELPER_API",
             "-DORIENT_PRESERVE_TABLEBASE_ORDER", "-Iinclude", "-Iexternal/fathom-upstream/src", "tools/tablebase_probe.cpp", "src/chess.cpp",
             "-x", "c++", "external/fathom-upstream/src/tbprobe.c", "-o", upstream], "upstream-build", out, args.evidence_root)
    archives = {}
    for name, source in sources.items():
        archive = out / (name + "-source.tar.gz")
        with tarfile.open(archive, "w:gz") as tar:
            tar.add(source, arcname=name + "-source", recursive=True)
        archives[name] = artifact(archive)
    controller_names = ("verify_improvements.py", "measure_improvements002.py", "audit_improvements002.py", "audit_saved_run.py")
    freeze = {"schema_version": 1, "source_files": [artifact(p) for source in sources.values() for p in sorted(source.rglob("*")) if p.is_file()],
              "source_archive": archives["candidate"], "baseline_archive": archives["baseline"],
              "baseline_snapshot": artifact(out / "baseline-source.json"), "candidate_snapshot": artifact(out / "candidate-source.json"),
              "protocol": artifact(protocol / "PROTOCOL.md"), "historical_protocol": artifact(historical / "protocol/PROTOCOL.md"),
              "tool_files": [artifact(historical / name) for name in controller_names] + [artifact(Path(__file__))]}
    write_json(protocol / "freeze.json", freeze)
    template = json.loads((historical / "correctness-config.json").read_text())
    oldroot = template["tablebase_manifest"]["path"].split("/external/tablebases/")[0]
    common = {"variants": variants, "tablebase_manifest": artifact(args.tables_manifest),
              "freeze": artifact(protocol / "freeze.json"), **freeze}
    config = remap_root(template, oldroot, args.evidence_root)
    config.update(common); config["upstream"] = {"probe": artifact(upstream)}
    write_json(out / "correctness-config.json", config)
    performance = remap_root(json.loads((historical / "performance-config002.json").read_text()), oldroot, args.evidence_root)
    performance.update(common); performance["logical_cpu"] = min(os.sched_getaffinity(0))
    # The result file does not exist until the exact-answer phase finishes.
    performance.pop("correctness", None)
    write_json(out / "performance-config-template.json", performance)
    write_json(out / "run-source-binding.json", {"schema_version": 1,
               "scope": "pre-007 baseline versus frozen current source; unchanged 007 acceptance protocol",
               "baseline": artifact(out / "baseline-source.json"), "candidate": artifact(out / "candidate-source.json"),
               "freeze": artifact(protocol / "freeze.json"), "dataset": dataset,
               "commands": {"prepare": sys.argv, "python": sys.version, "compiler": subprocess.check_output(["g++-13", "--version"], text=True)}})
    print("Prepared frozen current-source comparison. Next run --stage correctness.", flush=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", required=True, type=Path)
    parser.add_argument("--evidence-root", type=Path, default=ROOT,
                        help="component root containing preserved 007 controllers/snapshots/fixtures")
    parser.add_argument("--candidate-source", type=Path, default=ROOT,
                        help="actual current component source to freeze; never silently selects historical candidate")
    parser.add_argument("--baseline-source", type=Path)
    parser.add_argument("--tables-manifest", type=Path)
    parser.add_argument("--jobs", type=int, choices=(1, 2, 3), default=3)
    parser.add_argument("--stage", choices=("prepare", "correctness", "performance", "audit", "all"), default="all")
    args = parser.parse_args(); args.evidence_root = args.evidence_root.resolve(); out = args.out.resolve()
    args.tables_manifest = (args.tables_manifest or args.evidence_root / "external/tablebases/syzygy/3-4-5/manifest.json").resolve()
    historical = args.evidence_root / "artifacts/investigations/tablebases-007"
    dataset = verify_tablebase_manifest(args.tables_manifest)
    stages = ("prepare", "correctness", "performance", "audit") if args.stage == "all" else (args.stage,)
    for stage in stages:
        if stage == "prepare":
            prepare(args, out, historical, dataset)
            continue
        for name in ("baseline", "candidate"):
            verify_snapshot(out / "sources" / name, json.loads((out / (name + "-source.json")).read_text()))
        if stage == "correctness":
            run([sys.executable, historical / "verify_improvements.py", "--config", out / "correctness-config.json",
                 "--out", out / "verification/correctness-001"], "correctness", out, args.evidence_root)
        elif stage == "performance":
            if (out / "performance-config002.json").exists():
                raise ValueError("performance stage was already attempted; preserve it and choose a new run")
            config = json.loads((out / "performance-config-template.json").read_text())
            config["correctness"] = artifact(out / "verification/correctness-001/result.json")
            write_json(out / "performance-config002.json", config)
            run([sys.executable, historical / "measure_improvements002.py", "--config", out / "performance-config002.json",
                 "--out", out / "performance/acceptance-002"], "performance", out, args.evidence_root)
        else:
            run([sys.executable, historical / "audit_saved_run.py", "--run-root", out,
                 "--out", out / "independent-recomputation.json"], "independent-audit", out, args.evidence_root)
    print("Finished requested stages. Inspect the saved verdict; never repeat/extend trials to obtain a pass.", flush=True)


if __name__ == "__main__":
    main()
