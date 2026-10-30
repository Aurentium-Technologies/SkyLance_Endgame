"""Network-free transfer, resume, integrity and manifest-boundary regressions."""
from __future__ import annotations

import hashlib
import io
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "tools"))
import download_tablebases as download
import tablebase_manifest as manifest


class Response(io.BytesIO):
    def __init__(self, data, status=200, headers=None):
        super().__init__(data)
        self.status = status
        self.headers = headers or {}


class DownloadTests(unittest.TestCase):
    def item(self, data):
        return {"name": "KQvK.rtbw", "size": len(data),
                "sha256": hashlib.sha256(data).hexdigest(),
                "source_url": "https://example.invalid/KQvK.rtbw"}

    def test_fresh_download_verified_then_reused(self):
        data = b"verified table" * 100
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            item = self.item(data)
            self.assertTrue(download.download_one(item, root, lambda *a, **k: Response(data)))
            self.assertEqual((root / item["name"]).read_bytes(), data)
            self.assertFalse((root / (item["name"] + ".part")).exists())
            self.assertFalse(download.download_one(item, root, lambda *a, **k: self.fail("redownload")))

    def test_range_resume_and_ignored_range(self):
        data = b"abcdefghijklmnop"
        for status in (200, 206):
            with self.subTest(status=status), tempfile.TemporaryDirectory() as directory:
                root = Path(directory)
                item = self.item(data)
                (root / (item["name"] + ".part")).write_bytes(data[:5])
                def response(request, **kwargs):
                    self.assertEqual(request.headers["Range"], "bytes=5-")
                    return Response(data[5:] if status == 206 else data, status,
                                    {"Content-Range": f"bytes 5-15/{len(data)}"})
                self.assertTrue(download.download_one(item, root, response))
                self.assertEqual((root / item["name"]).read_bytes(), data)

    def test_bad_checksum_and_range_never_published(self):
        data = b"abcdefgh"
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            item = self.item(data)
            with self.assertRaisesRegex(ValueError, "SHA-256"):
                download.download_one(item, root, lambda *a, **k: Response(b"badbytes"), retries=1)
            self.assertFalse((root / item["name"]).exists())
            partial = root / (item["name"] + ".part")
            partial.write_bytes(data[:3])
            with self.assertRaisesRegex(ValueError, "Content-Range"):
                download.download_one(item, root, lambda *a, **k: Response(data[3:], 206,
                    {"Content-Range": "bytes 2-7/8"}), retries=1)
            self.assertFalse((root / item["name"]).exists())

    def test_invalid_existing_target_replaced_only_when_verified(self):
        data = b"verified replacement"
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            item = self.item(data)
            target = root / item["name"]
            target.write_bytes(b"old invalid bytes")
            with self.assertRaisesRegex(ValueError, "Incomplete"):
                download.download_one(item, root, lambda *a, **k: Response(b"short"), retries=1)
            self.assertEqual(target.read_bytes(), b"old invalid bytes")
            download.download_one(item, root, lambda *a, **k: Response(data))
            self.assertEqual(target.read_bytes(), data)

    def test_symlink_target_refused(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            target = root / "outside"
            target.write_bytes(b"untouched")
            (root / "KQvK.rtbw").symlink_to(target)
            with self.assertRaisesRegex(ValueError, "symlink"):
                download.download_one(self.item(b"other"), root)
            self.assertEqual(target.read_bytes(), b"untouched")


class ManifestTests(unittest.TestCase):
    def fixture(self, root):
        data = b"fixture table"
        item = DownloadTests().item(data)
        (root / item["name"]).write_bytes(data)
        record = {"schema_version": 1, "kind": "syzygy", "max_pieces": 5,
                  "complete": True, "root": ".", "total_bytes": len(data),
                  "files": [dict(item, published_checksum={"algorithm": "sha256", "value": item["sha256"]})]}
        path = root / "manifest.json"
        path.write_text(json.dumps(record))
        return path, item, record

    def test_complete_set_publisher_hash_and_symlink_boundaries(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            path, item, record = self.fixture(root)
            with patch.object(manifest, "catalogue", return_value={item["name"]: item}):
                result = manifest.verify_tablebase_manifest(path)
                self.assertEqual(result["file_count"], 1)
                self.assertEqual(result["manifest"]["sha256"], manifest.sha256(path))
                (root / item["name"]).write_bytes(b"wrong")
                with self.assertRaisesRegex(ValueError, "checksum"):
                    manifest.verify_tablebase_manifest(path)
                (root / item["name"]).unlink()
                (root / "elsewhere").write_bytes(b"fixture table")
                (root / item["name"]).symlink_to(root / "elsewhere")
                with self.assertRaisesRegex(ValueError, "ordinary"):
                    manifest.verify_tablebase_manifest(path)
            # A one-file set must never masquerade as the real complete collection.
            with self.assertRaisesRegex(ValueError, "290-file"):
                manifest.verify_tablebase_manifest(path)

    def test_catalogue_is_complete_and_publisher_pinned(self):
        records = manifest.catalogue()
        self.assertEqual(len(records), 290)
        self.assertEqual(sum(item["size"] for item in records.values()), 983957920)
        self.assertEqual(sum(name.endswith(".rtbw") for name in records), 145)
        self.assertEqual(sum(name.endswith(".rtbz") for name in records), 145)
        self.assertTrue(all("tablebase.lichess.ovh" in item["source_url"] for item in records.values()))


if __name__ == "__main__":
    unittest.main()
