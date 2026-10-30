"""Source selection and immutable snapshot regressions for acceptance reruns."""
from pathlib import Path
import json
import sys
import tempfile
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "tools"))
from reproduce_acceptance import freeze_source, remap_root, verify_snapshot


class FrozenAcceptanceSource(unittest.TestCase):
    def source(self, root):
        source = root / "current"
        (source / "src").mkdir(parents=True)
        (source / "CMakeLists.txt").write_text("project(current)\n")
        (source / "src/search.cpp").write_text("// selected current source\n")
        return source

    def test_freezes_selected_current_source_and_detects_later_tampering(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory); source = self.source(root); out = root / "run"
            snapshot = freeze_source(source, out, "candidate")
            manifest = json.loads((out / "candidate-source.json").read_text())
            self.assertEqual((snapshot / "src/search.cpp").read_text(), "// selected current source\n")
            (source / "src/search.cpp").write_text("// later work\n")
            self.assertEqual(freeze_source(source, out, "candidate"), snapshot)
            (snapshot / "src/search.cpp").write_text("// altered frozen bytes\n")
            with self.assertRaisesRegex(ValueError, "frozen source changed"):
                verify_snapshot(snapshot, manifest)

    def test_snapshot_rejects_unlisted_files_and_different_candidate(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory); source = self.source(root); out = root / "run"
            snapshot = freeze_source(source, out, "candidate")
            manifest = json.loads((out / "candidate-source.json").read_text())
            (snapshot / "unlisted").write_text("not frozen")
            with self.assertRaisesRegex(ValueError, "unlisted files"):
                verify_snapshot(snapshot, manifest)
            with self.assertRaisesRegex(ValueError, "different source or role"):
                freeze_source(root / "different", out, "candidate")

    def test_portable_path_remapping_does_not_change_hashes_or_unrelated_paths(self):
        value = {"nested": [{"path": "/old/component/src/search.cpp", "sha256": "abc"}],
                 "other": "/old/component-suffix/keep", "description": "old run"}
        remapped = remap_root(value, "/old/component", "/new/component")
        self.assertEqual(remapped["nested"], [{"path": "/new/component/src/search.cpp", "sha256": "abc"}])
        self.assertEqual(remapped["other"], value["other"])
        self.assertEqual(value["nested"][0]["path"], "/old/component/src/search.cpp")


if __name__ == "__main__":
    unittest.main()
