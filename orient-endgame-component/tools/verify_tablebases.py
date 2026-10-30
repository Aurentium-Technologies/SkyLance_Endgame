#!/usr/bin/env python3
"""Compare the Orient fork/adapter with pinned, untouched upstream Fathom."""
import argparse
import hashlib
import json
from pathlib import Path
import subprocess

from experiment import compute_lease
from tablebase_manifest import verify_tablebase_manifest


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--build", type=Path, default=Path("build/native"))
    parser.add_argument("--tables", type=Path, default=Path("external/tablebases/syzygy/3-4-5"))
    parser.add_argument("--out", type=Path, default=Path("artifacts/investigations/tablebases-001/comparison"))
    args = parser.parse_args()
    args.out.mkdir(parents=True, exist_ok=False)
    dataset = verify_tablebase_manifest(args.tables / "manifest.json")
    pin = json.loads(Path("third_party/fathom/UPSTREAM.json").read_text())
    for relative, expected in pin["upstream_files"].items():
        if digest(Path("external/fathom-upstream") / relative) != expected:
            raise RuntimeError("reference source is not unchanged: " + relative)
    catalogue = json.loads(Path("tools/syzygy345.json").read_text())
    classes = sorted({item["name"].split(".")[0] for item in catalogue["files"]})
    material = args.out / "materials.txt"
    material.write_text("\n".join(classes) + "\n")
    fixtures = args.out / "positions.fen"
    benchmark = (args.build / "orient-tablebase-bench").resolve(strict=True)
    binaries = {name: (args.build / name).resolve(strict=True)
                for name in ("orient-tablebase-reference", "orient-tablebase-probe")}
    outputs = {}
    with compute_lease("tablebase-upstream-differential-001"):
        subprocess.run([str(benchmark), "generate", str(material), str(fixtures), "10005"], check=True)
        extras = []
        for fen in fixtures.read_text().splitlines()[:1000]:
            fields = fen.split(); fields[4] = "98"; extras.append(" ".join(fields))
            fields[4] = "99"; extras.append(" ".join(fields))
        extras.extend([
            "4k3/8/8/3pP3/8/8/8/4K3 w - d6 0 1",
            "8/1P6/k7/8/1K6/8/8/8 w - - 0 1",
            "7k/6Q1/6K1/8/8/8/8/8 b - - 0 1",
            "7k/5Q2/6K1/8/8/8/8/8 b - - 0 1",
            "4k3/8/8/8/8/8/8/4K2R w K - 0 1",
        ])
        special = args.out / "special.fen"
        special.write_text("\n".join(extras) + "\n")
        for group, source in (("material", fixtures), ("special", special)):
            baseline = None
            for binary, cache in (("orient-tablebase-reference", 0), ("orient-tablebase-probe", 0),
                                  ("orient-tablebase-probe", 1), ("orient-tablebase-probe", 4),
                                  ("orient-tablebase-probe", 16)):
                key = f"{group}-{binary}-{cache}"
                output = args.out / (key + ".jsonl")
                error = args.out / (key + ".stderr")
                with output.open("w") as out, error.open("w") as err:
                    subprocess.run([str(binaries[binary]), dataset["root"], str(cache), str(source)],
                                   stdout=out, stderr=err, timeout=600, check=True)
                rows = [json.loads(line) for line in output.read_text().splitlines()]
                if len(rows) != len(source.read_text().splitlines()):
                    raise RuntimeError("missing probe outputs")
                if group == "material" and any(r["status"] != 0 or r["root_status"] != 0 for r in rows):
                    raise RuntimeError("complete collection did not cover a legal material fixture")
                if baseline is None:
                    baseline = rows
                elif rows != baseline:
                    differing = next(i for i, (a, b) in enumerate(zip(rows, baseline)) if a != b)
                    raise RuntimeError(f"differential mismatch in {key}, row {differing + 1}")
                outputs[key] = {"rows": len(rows), "sha256": digest(output), "path": str(output.resolve())}
                print(f"verified {key}: {len(rows)} matching outcomes/move sets", flush=True)
    result = {"schema_version": 1, "upstream_commit": pin["commit"], "dataset": dataset,
              "seed": 20261027, "material_classes": len(classes), "material_positions": 10005,
              "special_positions": len(extras), "cache_mib": [0, 1, 4, 16],
              "fixtures_sha256": digest(fixtures), "special_fixtures_sha256": digest(special),
              "binaries": {key: {"path": str(value), "sha256": digest(value)} for key, value in binaries.items()},
              "outputs": outputs, "exact_matches": True,
              "purpose": "validation only; not training labels or playing-strength evidence"}
    (args.out / "result.json").write_text(json.dumps(result, indent=2) + "\n")
    print("All upstream/fork/cache comparisons match exactly")


if __name__ == "__main__":
    main()
