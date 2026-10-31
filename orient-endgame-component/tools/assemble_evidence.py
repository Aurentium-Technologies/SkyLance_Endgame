#!/usr/bin/env python3
"""Reassemble the original 006 archive from temporary assets on its draft release.

This manual GitHub Actions transport fallback never extracts the payload, runs
anything inside it, overwrites an original asset, publishes a release, or deletes
remote assets. The checked-out public evidence manifest is the byte authority.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import time


REPOSITORY = "Aurentium-Technologies/SkyLance_Endgame"
TAG = "v0.1.0"
ASSET = "skylance-evidence-006.tar.gz"
PART_PREFIX = ASSET + ".part-"
PART_BYTES = 16 * 1024 * 1024
API = "/repos/" + REPOSITORY


def need(condition, message):
    if not condition:
        raise ValueError(message)


def unique(pairs):
    result = {}
    for key, value in pairs:
        need(key not in result, "duplicate JSON key")
        result[key] = value
    return result


def strict_json(text):
    def reject(value):
        raise ValueError("non-finite JSON constant: " + value)
    return json.loads(text, object_pairs_hook=unique, parse_constant=reject)


def positive_id(value):
    need(isinstance(value, str) and re.fullmatch(r"[1-9][0-9]{0,19}", value) is not None,
         "release ID must be a positive decimal integer")
    return int(value)


def check_context(environment):
    need(environment.get("GITHUB_REPOSITORY") == REPOSITORY, "unexpected workflow repository")
    need(environment.get("GITHUB_REF") == "refs/heads/main", "assembly is restricted to main")
    need(environment.get("GITHUB_EVENT_NAME") == "workflow_dispatch", "manual workflow dispatch required")
    need(bool(environment.get("GH_TOKEN")), "GH_TOKEN is required")


def read_expected(path):
    path = Path(path)
    need(not path.is_symlink() and path.is_file(), "manifest must be an ordinary checked-out file")
    manifest = strict_json(path.read_text(encoding="utf-8"))
    need(isinstance(manifest, dict) and type(manifest.get("schema_version")) is int
         and manifest["schema_version"] == 1 and manifest.get("kind") == "skylance-public-evidence",
         "unexpected public evidence manifest")
    record = manifest.get("comparison_release")
    need(isinstance(record, dict) and record.get("filename") == ASSET, "unexpected original archive name")
    need(type(record.get("bytes")) is int and record["bytes"] > 0, "invalid expected original size")
    need(isinstance(record.get("sha256"), str) and re.fullmatch(r"[0-9a-f]{64}", record["sha256"]) is not None,
         "invalid expected original SHA-256")
    base = "https://github.com/" + REPOSITORY + "/releases/download/" + TAG + "/" + ASSET
    need(record.get("url") == base and record.get("checksum_url") == base + ".sha256",
         "manifest release destination differs")
    return record


def part_plan(size, part_bytes=PART_BYTES):
    need(type(size) is int and size > 0 and type(part_bytes) is int and part_bytes > 0,
         "invalid archive/part size")
    count = (size + part_bytes - 1) // part_bytes
    need(count <= 1000, "too many transport parts")
    return {PART_PREFIX + f"{index:03d}": min(part_bytes, size - index * part_bytes)
            for index in range(count)}


def check_release(release, release_id):
    need(isinstance(release, dict) and type(release.get("id")) is int and release["id"] == release_id,
         "unexpected release identity")
    need(release.get("draft") is True and release.get("tag_name") == TAG,
         "release must still be the v0.1.0 draft")
    need(release.get("url") == "https://api.github.com" + API + "/releases/" + str(release_id),
         "release belongs to a different repository")


def asset_digest(asset):
    value = asset.get("digest")
    need(isinstance(value, str) and re.fullmatch(r"sha256:[0-9a-f]{64}", value) is not None,
         "release asset has no authoritative SHA-256")
    return value[7:]


def check_asset(asset, name, size, expected_digest=None):
    need(asset.get("name") == name and type(asset.get("id")) is int and asset["id"] > 0,
         "unexpected release asset identity")
    need(asset.get("state") == "uploaded", "release asset is not uploaded: " + name)
    need(type(asset.get("size")) is int and asset["size"] == size, "release asset size differs: " + name)
    value = asset_digest(asset)
    if expected_digest is not None:
        need(value == expected_digest, "existing original asset SHA-256 differs")
    return value


def inspect_assets(assets, expected, plan):
    need(isinstance(assets, list), "invalid release asset inventory")
    parts, original, seen_ids = {}, None, set()
    for asset in assets:
        need(isinstance(asset, dict) and isinstance(asset.get("name"), str), "invalid release asset record")
        name = asset["name"]
        if name == ASSET:
            need(original is None, "duplicate original archive assets")
            check_asset(asset, ASSET, expected["bytes"], expected["sha256"])
            original = asset
        elif name.startswith(ASSET + ".part"):
            need(name in plan, "unexpected matching transport asset: " + name)
            need(name not in parts, "duplicate transport part: " + name)
            check_asset(asset, name, plan[name])
            parts[name] = asset
        else:
            continue
        need(asset["id"] not in seen_ids, "duplicate release asset IDs")
        seen_ids.add(asset["id"])
    if original is None:
        need(set(parts) == set(plan), "missing transport parts; original archive was not uploaded")
    return parts, original


def file_digest(path):
    value = hashlib.sha256()
    with Path(path).open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            value.update(block)
    return value.hexdigest()


def assemble_files(parts, expected, output, plan):
    """Verify every downloaded part, then stream the unchanged concatenation."""
    need(set(parts) == set(plan), "local transport part inventory differs")
    combined = hashlib.sha256()
    total = 0
    with Path(output).open("xb") as result:
        for name, size in plan.items():
            path, wanted = parts[name]
            path = Path(path)
            need(not path.is_symlink() and path.is_file() and path.stat().st_size == size,
                 "downloaded part size differs: " + name)
            need(file_digest(path) == wanted, "downloaded part digest differs: " + name)
            with path.open("rb") as stream:
                for block in iter(lambda: stream.read(1024 * 1024), b""):
                    result.write(block); combined.update(block); total += len(block)
        result.flush(); os.fsync(result.fileno())
    need(total == expected["bytes"] and combined.hexdigest() == expected["sha256"],
         "combined original archive size/SHA-256 differs from the checked-out manifest")
    return Path(output)


class Github:
    def __init__(self):
        self.environment = dict(os.environ)
        self.environment.pop("GH_DEBUG", None)
        self.environment["GH_HOST"] = "github.com"

    def command(self, arguments, output=None):
        result = subprocess.run(["gh", *arguments], env=self.environment, stdout=output or subprocess.PIPE,
                                stderr=subprocess.PIPE, check=False)
        if result.returncode:
            # Never echo commands, token values, signed download URLs or raw
            # debug output into workflow logs.
            raise RuntimeError("GitHub CLI request failed with exit code " + str(result.returncode))
        return result.stdout

    def api(self, endpoint):
        return strict_json(self.command(["api", "--hostname", "github.com", "--method", "GET", endpoint]))

    def pages(self, endpoint):
        result = []
        for page in range(1, 101):
            rows = self.api(endpoint + "?per_page=100&page=" + str(page))
            need(isinstance(rows, list), "invalid paginated GitHub response")
            result.extend(rows)
            if len(rows) < 100:
                return result
        raise ValueError("release inventory exceeds the bounded pagination limit")

    def release(self, release_id):
        release = self.api(API + "/releases/" + str(release_id))
        check_release(release, release_id)
        return release

    def assets(self, release_id):
        return self.pages(API + "/releases/" + str(release_id) + "/assets")

    def download(self, asset, destination):
        with Path(destination).open("xb") as stream:
            self.command(["api", "--hostname", "github.com", "--method", "GET",
                          "-H", "Accept: application/octet-stream",
                          API + "/releases/assets/" + str(asset["id"])], output=stream)

    def upload(self, release_id, archive):
        # gh release upload locates drafts by tag. Ensure that tag identifies
        # this exact draft before using the CLI; the caller rechecks its ID
        # afterward. No --clobber flag is ever passed.
        self.release(release_id)
        matches = [row for row in self.pages(API + "/releases") if row.get("tag_name") == TAG]
        need(len(matches) == 1 and matches[0].get("id") == release_id and matches[0].get("draft") is True,
             "tag does not uniquely identify the selected draft release")
        self.command(["release", "upload", TAG, str(archive), "--repo", "github.com/" + REPOSITORY])


def execute(expected, release_id, work_dir, github):
    plan = part_plan(expected["bytes"])
    github.release(release_id)
    parts, original = inspect_assets(github.assets(release_id), expected, plan)
    if original is not None:
        return {"status": "already_present", "asset_id": original["id"], "parts_verified": 0}
    work_dir = Path(work_dir)
    work_dir.mkdir(parents=True, exist_ok=False)
    downloaded = {}
    for name, size in plan.items():
        path = work_dir / name
        github.download(parts[name], path)
        downloaded[name] = path, check_asset(parts[name], name, size)
    archive = assemble_files(downloaded, expected, work_dir / ASSET, plan)
    # Recheck the draft and inventory immediately before the only remote write.
    github.release(release_id)
    _, original = inspect_assets(github.assets(release_id), expected, plan)
    if original is None:
        github.upload(release_id, archive)
    for attempt in range(20):
        github.release(release_id)
        _, original = inspect_assets(github.assets(release_id), expected, plan)
        if original is not None:
            return {"status": "assembled_and_uploaded", "asset_id": original["id"],
                    "parts_verified": len(parts)}
        if attempt != 19:
            time.sleep(3)
    raise ValueError("uploaded original asset was not confirmed on the selected draft")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--release-id", required=True)
    parser.add_argument("--manifest", required=True, type=Path)
    parser.add_argument("--work-dir", required=True, type=Path)
    args = parser.parse_args()
    try:
        check_context(os.environ)
        release_id = positive_id(args.release_id)
        expected = read_expected(args.manifest)
        result = execute(expected, release_id, args.work_dir, Github())
        print(json.dumps({**result, "repository": REPOSITORY, "release_id": release_id,
                          "tag": TAG, "draft": True, "filename": ASSET,
                          "bytes": expected["bytes"], "sha256": expected["sha256"]}, sort_keys=True))
    except (OSError, ValueError, TypeError, KeyError, RuntimeError) as error:
        print("Evidence assembly failed: " + str(error), file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
