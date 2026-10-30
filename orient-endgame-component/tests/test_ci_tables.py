"""CI's tiny real-table fixture subset stays pinned and is never called complete."""
from __future__ import annotations

import hashlib
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "tools"))
import ci_tables as ci


class CiTableFixtures(unittest.TestCase):
    def fixture(self):
        data = {name: name.encode() for name in ci.REGRESSION_FILES}
        records = {name: {"name": name, "size": len(payload),
                          "sha256": hashlib.sha256(payload).hexdigest()}
                   for name, payload in data.items()}
        return data, records

    def test_exactly_two_real_files_are_fetched_and_verified(self):
        data, records = self.fixture()
        calls = []
        with tempfile.TemporaryDirectory() as tmp, patch.object(ci, "catalogue", return_value=records):
            root = Path(tmp) / "tables"
            def fetch(record, destination):
                calls.append(record["name"])
                (destination / record["name"]).write_bytes(data[record["name"]])
            result = ci.prepare_regression_tables(root, downloader=fetch)
            self.assertEqual(calls, list(ci.REGRESSION_FILES))
            self.assertEqual(result["files"], calls)
            self.assertEqual(result["bytes"], sum(map(len, data.values())))
            self.assertIn("not a complete", result["scope"])
            self.assertFalse((root / "manifest.json").exists())

    def test_cache_is_rehashed_and_missing_or_corrupt_files_fail(self):
        data, records = self.fixture()
        with tempfile.TemporaryDirectory() as tmp, patch.object(ci, "catalogue", return_value=records):
            root = Path(tmp)
            for name, payload in data.items():
                (root / name).write_bytes(payload)
            ci.verify_regression_tables(root)
            target = root / ci.REGRESSION_FILES[0]
            target.write_bytes(b"x" * target.stat().st_size)
            with self.assertRaisesRegex(ValueError, "SHA-256"):
                ci.verify_regression_tables(root)
            target.unlink()
            with self.assertRaisesRegex(ValueError, "ordinary"):
                ci.verify_regression_tables(root)

    def test_symlink_directory_and_files_are_refused(self):
        data, records = self.fixture()
        with tempfile.TemporaryDirectory() as tmp, patch.object(ci, "catalogue", return_value=records):
            root = Path(tmp)
            for name, payload in data.items():
                (root / name).write_bytes(payload)
            alias = root / "alias"
            alias.symlink_to(root, target_is_directory=True)
            with self.assertRaisesRegex(ValueError, "directory"):
                ci.prepare_regression_tables(alias)
            table = root / ci.REGRESSION_FILES[0]
            table.unlink()
            table.symlink_to(root / ci.REGRESSION_FILES[1])
            with self.assertRaisesRegex(ValueError, "ordinary"):
                ci.verify_regression_tables(root)

    def test_real_fixture_subset_is_tiny_and_catalogue_bound(self):
        from tablebase_manifest import catalogue
        records = catalogue()
        self.assertEqual(sum(records[name]["size"] for name in ci.REGRESSION_FILES), 5664)
        self.assertEqual({name.rsplit(".", 1)[1] for name in ci.REGRESSION_FILES}, {"rtbw", "rtbz"})


if __name__ == "__main__":
    unittest.main()
