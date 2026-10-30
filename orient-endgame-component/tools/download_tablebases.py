#!/usr/bin/env python3
"""Download and verify the pinned complete three-to-five-piece Syzygy set."""
from __future__ import annotations

import argparse
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
from http.client import HTTPException
import json
import os
from pathlib import Path
import time
from urllib.request import Request, urlopen

from tablebase_manifest import CATALOGUE, catalogue, sha256, verify_tablebase_manifest


def download_one(item, root, opener=urlopen, retries=4):
    """Resume only a matching HTTP range; publish after a full SHA-256 check."""
    root = Path(root)
    target = root / item["name"]
    partial = target.with_name(target.name + ".part")
    if target.is_symlink() or partial.is_symlink():
        raise ValueError("Refusing symlink download target")
    if target.is_file() and target.stat().st_size == item["size"] and sha256(target) == item["sha256"]:
        return False
    for attempt in range(retries):
        try:
            offset = partial.stat().st_size if partial.exists() else 0
            if offset >= item["size"]:
                if offset == item["size"] and sha256(partial) == item["sha256"]:
                    os.replace(partial, target)
                    return True
                partial.unlink()
                offset = 0
            headers = {"User-Agent": "Orient-tablebase-setup/1.0"}
            if offset:
                headers["Range"] = f"bytes={offset}-"
            with opener(Request(item["source_url"], headers=headers), timeout=60) as response:
                status = getattr(response, "status", 200)
                if offset and status == 206:
                    content_range = response.headers.get("Content-Range", "")
                    if not content_range.startswith(f"bytes {offset}-") or not content_range.endswith(f"/{item['size']}"):
                        raise ValueError("Unexpected Content-Range")
                    mode = "ab"
                elif status == 200:
                    mode = "wb"
                else:
                    raise ValueError("Unexpected HTTP response status")
                with partial.open(mode) as stream:
                    received = stream.tell()
                    while block := response.read(1024 * 1024):
                        received += len(block)
                        if received > item["size"]:
                            raise ValueError("Download exceeds published file size")
                        stream.write(block)
                    stream.flush()
                    os.fsync(stream.fileno())
            if partial.stat().st_size != item["size"]:
                raise ValueError("Incomplete tablebase transfer")
            if sha256(partial) != item["sha256"]:
                partial.unlink()
                raise ValueError("Published SHA-256 mismatch")
            os.replace(partial, target)
            return True
        except (OSError, ValueError, HTTPException):
            if attempt + 1 == retries:
                raise
            time.sleep(min(8, 2 ** attempt))
    raise RuntimeError("unreachable")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--destination", type=Path,
                        default=Path(__file__).resolve().parents[1] / "external/tablebases/syzygy/3-4-5")
    parser.add_argument("--workers", type=int, choices=range(1, 5), default=3)
    parser.add_argument("--verify-only", action="store_true")
    args = parser.parse_args()
    if args.destination.is_symlink():
        raise ValueError("Destination must not be a symlink")
    args.destination.mkdir(parents=True, exist_ok=True)
    root = args.destination.resolve()
    if args.verify_only:
        print(json.dumps(verify_tablebase_manifest(root / "manifest.json"), sort_keys=True))
        return
    items = sorted(catalogue().values(), key=lambda row: (len(row["name"].split(".")[0]), row["size"], row["name"]))
    completed = 0
    with ThreadPoolExecutor(max_workers=args.workers) as pool:
        futures = {pool.submit(download_one, item, root): item for item in items}
        for future in as_completed(futures):
            item = futures[future]
            future.result()
            completed += 1
            if completed % 10 == 0 or completed == len(items):
                print(f"Verified {completed}/{len(items)}: {item['name']}", flush=True)
    source = json.loads(CATALOGUE.read_text(encoding="utf-8"))
    records = [dict(item, published_checksum={"algorithm": "sha256", "value": item["sha256"]})
               for item in sorted(items, key=lambda row: row["name"])]
    manifest = {"schema_version": 1, "kind": "syzygy", "max_pieces": 5,
                "complete": True, "root": ".", "created_utc": datetime.now(timezone.utc).isoformat(),
                "total_bytes": sum(row["size"] for row in items), "files": records,
                "published_catalogues": source["sources"], "catalogue_sha256": sha256(CATALOGUE)}
    temporary = root / "manifest.json.tmp"
    if temporary.is_symlink():
        raise ValueError("Refusing symlink manifest target")
    with temporary.open("w", encoding="utf-8") as stream:
        json.dump(manifest, stream, indent=2, sort_keys=True)
        stream.write("\n")
        stream.flush()
        os.fsync(stream.fileno())
    os.replace(temporary, root / "manifest.json")
    print(json.dumps(verify_tablebase_manifest(root / "manifest.json"), sort_keys=True), flush=True)


if __name__ == "__main__":
    main()
