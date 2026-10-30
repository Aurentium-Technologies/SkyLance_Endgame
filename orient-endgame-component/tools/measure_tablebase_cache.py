#!/usr/bin/env python3
"""Fixed paired local cache experiment. Its positions/results are not training data."""
import argparse
import hashlib
import json
import math
from pathlib import Path
import subprocess

from experiment import compute_lease


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--build", type=Path, default=Path("build/native"))
    parser.add_argument("--tables", type=Path, default=Path("external/tablebases/syzygy/3-4-5"))
    parser.add_argument("--out", type=Path, default=Path("artifacts/investigations/tablebases-001/cache"))
    args = parser.parse_args()
    args.out.mkdir(parents=True, exist_ok=False)
    tool = (args.build / "orient-tablebase-bench").resolve(strict=True)
    catalogue = json.loads(Path("tools/syzygy345.json").read_text())
    classes = sorted({item["name"].split(".")[0] for item in catalogue["files"]})
    material = args.out / "materials.txt"
    material.write_text("\n".join(classes) + "\n")
    all_fens = args.out / "positions.fen"
    six_material = args.out / "search-materials.txt"
    six_classes = [name + "P" for name in classes if len(name) - 1 == 5]
    six_material.write_text("\n".join(six_classes) + "\n")
    generated_search = args.out / "search-all.fen"
    search_fens = args.out / "search.fen"
    with compute_lease("tablebase-paired-cache-001"):
        subprocess.run([str(tool), "generate", str(material), str(all_fens), "10005"], check=True)
        subprocess.run([str(tool), "generate", str(six_material), str(generated_search), str(len(six_classes))], check=True)
        available = generated_search.read_text().splitlines()
        chosen = [available[i * len(available) // 48] for i in range(48)]
        search_fens.write_text("\n".join(chosen) + "\n")
        def run(cache):
            completed = subprocess.run([str(tool), "run", str(args.tables.resolve()), str(cache),
                                        str(all_fens), str(search_fens), "4"],
                                       capture_output=True, text=True, timeout=300, check=True)
            return json.loads(completed.stdout)
        warmup = run(0)
        trials = []
        for pair in range(5):
            order = (0, 4, 16)[pair % 3:] + (0, 4, 16)[:pair % 3]
            for cache in order:
                result = run(cache)
                result["pair"] = pair + 1
                trials.append(result)
                (args.out / f"trial-{pair + 1}-{cache}.json").write_text(json.dumps(result, indent=2) + "\n")
                print(f"pair={pair + 1} cache={cache} search_ms={result['search_ms']:.3f}", flush=True)
    lookup_hashes = {r["lookup_hash"] for r in trials}
    search_hashes = {r["search_hash"] for r in trials}
    if len(lookup_hashes) != 1 or len(search_hashes) != 1:
        raise RuntimeError("cache changed a compared outcome, move, score or node count")
    candidates = []
    for cache in (4, 16):
        speeds, distinct_ratios = [], []
        for pair in range(1, 6):
            baseline = next(r for r in trials if r["pair"] == pair and r["cache_mib"] == 0)
            candidate = next(r for r in trials if r["pair"] == pair and r["cache_mib"] == cache)
            speeds.append(baseline["search_ms"] / candidate["search_ms"])
            distinct_ratios.append(candidate["distinct_lookup_ms"] / baseline["distinct_lookup_ms"])
            if candidate["cache_bytes"] > cache * 1024 * 1024:
                raise RuntimeError("cache exceeds advertised memory budget")
        speed = math.exp(sum(map(math.log, speeds)) / 5)
        distinct = math.exp(sum(map(math.log, distinct_ratios)) / 5)
        candidates.append({"cache_mib": cache, "search_speedup_geomean": speed,
                           "distinct_lookup_time_ratio_geomean": distinct,
                           "passes": speed >= 1.05 and distinct <= 1.05})
    selected = next((c["cache_mib"] for c in candidates if c["passes"]), 0)
    result = {"schema_version": 1, "seed": 20261027, "pairs": 5, "depth": 4,
              "positions": 10005, "material_classes": len(classes), "search_positions": len(chosen),
              "binary": {"path": str(tool), "sha256": digest(tool)},
              "fixtures_sha256": digest(all_fens), "search_fixtures_sha256": digest(search_fens),
              "table_manifest_sha256": digest(args.tables / "manifest.json"),
              "warmup": warmup, "trials": trials, "candidates": candidates,
              "selected_cache_mib": selected,
              "cache_state": "OS cache prewarmed; new reader/value cache per trial; no privileged cache flush"}
    (args.out / "result.json").write_text(json.dumps(result, indent=2) + "\n")
    print(json.dumps({"selected_cache_mib": selected, "candidates": candidates}, indent=2))


if __name__ == "__main__":
    main()
