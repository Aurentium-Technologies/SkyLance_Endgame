#!/usr/bin/env python3
"""Fetch only the two pinned KQvK files needed by reader memory regressions.

This fixture subset is not a complete Syzygy collection. It deliberately does
not generate the complete-set manifest expected by the full-data tests.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

from download_tablebases import download_one
from tablebase_manifest import CATALOGUE, catalogue, sha256


REGRESSION_FILES = ("KQvK.rtbw", "KQvK.rtbz")


def verify_regression_tables(destination):
    root = Path(destination)
    if root.is_symlink():
        raise ValueError("Regression table directory must not be a symlink")
    root = root.resolve(strict=True)
    expected = catalogue()
    for name in REGRESSION_FILES:
        table, record = root / name, expected[name]
        if table.is_symlink() or not table.is_file():
            raise ValueError("Expected ordinary pinned regression table: " + name)
        if table.stat().st_size != record["size"] or sha256(table) != record["sha256"]:
            raise ValueError("Regression table size or SHA-256 differs: " + name)
    return {"scope": "KQvK reader regression fixtures; not a complete table set",
            "files": list(REGRESSION_FILES),
            "bytes": sum(expected[name]["size"] for name in REGRESSION_FILES),
            "catalogue_sha256": sha256(CATALOGUE)}


def prepare_regression_tables(destination, downloader=download_one):
    root = Path(destination)
    if root.is_symlink():
        raise ValueError("Regression table directory must not be a symlink")
    root.mkdir(parents=True, exist_ok=True)
    records = catalogue()
    for name in REGRESSION_FILES:
        downloader(records[name], root)
    return verify_regression_tables(root)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--destination", type=Path, default=Path(__file__).resolve().parents[1]
                        / "external/tablebases/ci-regressions")
    parser.add_argument("--verify-only", action="store_true")
    args = parser.parse_args()
    result = (verify_regression_tables(args.destination) if args.verify_only
              else prepare_regression_tables(args.destination))
    print(json.dumps(result, sort_keys=True))


if __name__ == "__main__":
    main()
