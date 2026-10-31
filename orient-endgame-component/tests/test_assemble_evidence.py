"""Fail-closed validation and byte-preserving assembly for release transport."""
from copy import deepcopy
import hashlib
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "tools"))
import assemble_evidence as assembly


def expected(data=b"original archive bytes"):
    base = "https://github.com/" + assembly.REPOSITORY + "/releases/download/v0.1.0/" + assembly.ASSET
    return {"filename": assembly.ASSET, "bytes": len(data), "sha256": hashlib.sha256(data).hexdigest(),
            "url": base, "checksum_url": base + ".sha256"}


def asset(name, data, identity=1):
    return {"id": identity, "name": name, "size": len(data), "state": "uploaded",
            "digest": "sha256:" + hashlib.sha256(data).hexdigest()}


def release(identity=429614337):
    return {"id": identity, "draft": True, "tag_name": "v0.1.0",
            "url": "https://api.github.com/repos/" + assembly.REPOSITORY + "/releases/" + str(identity)}


class FakeGithub:
    def __init__(self, data):
        self.data = data
        self.uploads = 0
        self.downloads = 0
        self.original = None
        self.parts = [asset(assembly.PART_PREFIX + "000", data)]

    def release(self, identity):
        value = release(identity); assembly.check_release(value, identity); return value

    def assets(self, identity):
        return self.parts + ([self.original] if self.original else [])

    def download(self, record, path):
        self.downloads += 1
        Path(path).write_bytes(self.data)

    def upload(self, identity, path):
        if Path(path).read_bytes() != self.data:
            raise AssertionError("archive bytes changed")
        self.uploads += 1
        self.original = asset(assembly.ASSET, self.data, 999)


class EvidenceAssembly(unittest.TestCase):
    def test_manifest_expected_archive_and_repository_are_pinned(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "MANIFEST.json"
            good = {"schema_version": 1, "kind": "skylance-public-evidence", "comparison_release": expected()}
            path.write_text(json.dumps(good))
            self.assertEqual(assembly.read_expected(path), expected())
            for changes in ({"bytes": True}, {"bytes": 0}, {"sha256": "bad"},
                            {"filename": "different.tar.gz"}, {"url": "https://example.invalid/archive"}):
                bad = deepcopy(good); bad["comparison_release"].update(changes)
                path.write_text(json.dumps(bad))
                with self.subTest(changes=changes), self.assertRaises(ValueError):
                    assembly.read_expected(path)

    def test_release_id_and_manual_main_repository_context(self):
        self.assertEqual(assembly.positive_id("429614337"), 429614337)
        for value in ("0", "-1", "01", "1;echo nope", "1.0", "", "١"):
            with self.subTest(value=value), self.assertRaises(ValueError):
                assembly.positive_id(value)
        good = {"GITHUB_REPOSITORY": assembly.REPOSITORY, "GITHUB_REF": "refs/heads/main",
                "GITHUB_EVENT_NAME": "workflow_dispatch", "GH_TOKEN": "fixture-token"}
        assembly.check_context(good)
        for name, value in (("GITHUB_REPOSITORY", "other/repository"), ("GITHUB_REF", "refs/heads/other"),
                            ("GITHUB_EVENT_NAME", "push"), ("GH_TOKEN", "")):
            with self.subTest(name=name), self.assertRaises(ValueError):
                assembly.check_context({**good, name: value})

    def test_real_size_requires_exact_eleven_parts_and_tail(self):
        plan = assembly.part_plan(175902653)
        self.assertEqual(len(plan), 11)
        self.assertEqual(list(plan), [assembly.PART_PREFIX + f"{n:03d}" for n in range(11)])
        self.assertEqual(list(plan.values()), [16777216] * 10 + [8130493])
        for size in (0, -1, True, 1.5):
            with self.subTest(size=size), self.assertRaises(ValueError):
                assembly.part_plan(size)

    def test_draft_release_identity_tag_and_repository_are_required(self):
        good = release(); assembly.check_release(good, good["id"])
        for change in ({"draft": False}, {"id": 2}, {"tag_name": "other"},
                       {"url": "https://api.github.com/repos/other/repo/releases/429614337"}):
            with self.subTest(change=change), self.assertRaises(ValueError):
                assembly.check_release({**good, **change}, good["id"])

    def test_inventory_rejects_missing_duplicate_unknown_or_bad_parts(self):
        data = b"abcdefgh"; record = expected(data); plan = assembly.part_plan(len(data))
        good = asset(assembly.PART_PREFIX + "000", data)
        bad_cases = ([], [good, good], [good, asset(assembly.PART_PREFIX + "001", b"x", 2)],
                     [{**good, "size": 1}], [{**good, "digest": None}], [{**good, "state": "starter"}],
                     [good, asset(assembly.ASSET + ".partial", b"x", 2)])
        for rows in bad_cases:
            with self.subTest(rows=rows), self.assertRaises(ValueError):
                assembly.inspect_assets(rows, record, plan)

    def test_existing_original_accepts_only_exact_uploaded_size_and_digest(self):
        data = b"already uploaded"; record = expected(data); plan = assembly.part_plan(len(data))
        original = asset(assembly.ASSET, data)
        parts, found = assembly.inspect_assets([original], record, plan)
        self.assertEqual(parts, {}); self.assertEqual(found, original)
        for changes in ({"size": 1}, {"digest": "sha256:" + "0" * 64}, {"state": "starter"}):
            with self.subTest(changes=changes), self.assertRaises(ValueError):
                assembly.inspect_assets([{**original, **changes}], record, plan)
        with self.assertRaisesRegex(ValueError, "unexpected matching"):
            assembly.inspect_assets([original, asset(assembly.PART_PREFIX + "999", b"x", 2)], record, plan)

    def test_part_and_combined_hashes_are_checked_without_extracting(self):
        data = b"not necessarily a tar payload"; record = expected(data)
        plan = assembly.part_plan(len(data), part_bytes=7)
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp); parts = {}
            for number, (name, size) in enumerate(plan.items()):
                payload = data[number * 7:number * 7 + size]
                path = root / name; path.write_bytes(payload)
                parts[name] = path, hashlib.sha256(payload).hexdigest()
            output = root / assembly.ASSET
            assembly.assemble_files(parts, record, output, plan)
            self.assertEqual(output.read_bytes(), data)
            with self.assertRaises(FileExistsError):
                assembly.assemble_files(parts, record, output, plan)
            altered = {**record, "sha256": "0" * 64}
            with self.assertRaisesRegex(ValueError, "combined original"):
                assembly.assemble_files(parts, altered, root / "wrong-combined", plan)
            first = next(iter(parts)); parts[first] = parts[first][0], "0" * 64
            with self.assertRaisesRegex(ValueError, "downloaded part digest"):
                assembly.assemble_files(parts, record, root / "wrong-part", plan)

    def test_end_to_end_transport_uploads_once_and_verifies_remote_original(self):
        data = b"original frozen archive"; github = FakeGithub(data)
        with tempfile.TemporaryDirectory() as tmp:
            result = assembly.execute(expected(data), 429614337, Path(tmp) / "work", github)
            self.assertEqual(result["status"], "assembled_and_uploaded")
            self.assertEqual((github.downloads, github.uploads), (1, 1))
            again = assembly.execute(expected(data), 429614337, Path(tmp) / "unused", github)
            self.assertEqual(again["status"], "already_present")
            self.assertFalse((Path(tmp) / "unused").exists())
            self.assertEqual((github.downloads, github.uploads), (1, 1))

    def test_gh_upload_checks_unique_draft_and_never_requests_clobber(self):
        github = assembly.Github(); calls = []
        with patch.object(github, "release", return_value=release()), \
             patch.object(github, "pages", return_value=[release()]), \
             patch.object(github, "command", side_effect=lambda argv: calls.append(argv)):
            github.upload(429614337, Path("/tmp/original.tar.gz"))
        self.assertEqual(calls, [["release", "upload", "v0.1.0", "/tmp/original.tar.gz", "--repo", "github.com/" + assembly.REPOSITORY]])
        self.assertNotIn("--clobber", calls[0])
        with patch.object(github, "release", return_value=release()), \
             patch.object(github, "pages", return_value=[release(), release(2)]), \
             patch.object(github, "command", side_effect=AssertionError("must not upload")):
            with self.assertRaisesRegex(ValueError, "uniquely identify"):
                github.upload(429614337, Path("/tmp/original.tar.gz"))


if __name__ == "__main__":
    unittest.main()
