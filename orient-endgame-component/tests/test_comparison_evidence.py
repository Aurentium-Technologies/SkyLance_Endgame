"""Reject altered comparison protocols and unverified evidence dependencies."""
from copy import deepcopy
from pathlib import Path
import sys
import tempfile
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "tools"))
from package_comparison_evidence import numeric_payload
from verify_comparison_evidence import Evidence, NAMES, REPEATS, THRESHOLDS, load_auditor, validate_protocol


class ComparisonEvidenceGuards(unittest.TestCase):
    def freeze(self):
        return {"seed": 2026102906, "blocks": 30, "samples": 540,
                "repeats": dict(REPEATS), "thresholds": dict(THRESHOLDS),
                "binaries": dict.fromkeys(NAMES, {})}

    def test_original_protocol_is_required_without_relaxing_thresholds(self):
        good = self.freeze(); validate_protocol(good)
        for field, value in (("seed", 1), ("blocks", 31), ("samples", 0), ("repeats", {}), ("binaries", {})):
            with self.subTest(field=field), self.assertRaises(ValueError):
                validate_protocol({**good, field: value})
        for field, value in (("bootstrap_resamples", 1000), ("family", 1), ("wall_upper", 1.), ("p95_upper", 1.1)):
            changed = deepcopy(good); changed["thresholds"][field] = value
            with self.subTest(threshold=field), self.assertRaisesRegex(ValueError, "thresholds"):
                validate_protocol(changed)

    def test_relative_and_original_paths_resolve_only_verified_members(self):
        with tempfile.TemporaryDirectory() as temporary:
            # macOS temporary paths may use /var while the canonical root is
            # /private/var; compare canonical paths just as the verifier does.
            root = Path(temporary).resolve(); component = root / "orient-endgame-component"
            component.mkdir(); (component / "result.json").write_text("{}")
            evidence = Evidence(root, {"original_component_root": "/original/component",
                                       "files": [{"path": "orient-endgame-component/result.json"}]})
            self.assertEqual(evidence.resolve("/original/component/result.json"), component / "result.json")
            self.assertEqual(evidence.resolve("result.json"), component / "result.json")
            (component / "unlisted.json").write_text("{}")
            for path in ("unlisted.json", "/outside/result.json", "../result.json"):
                with self.subTest(path=path), self.assertRaises(ValueError):
                    evidence.resolve(path)

    def test_auditor_must_be_in_inventory_and_match_original_sha_before_loading(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary); relative = Path("orient-endgame-component/artifacts/investigations/tablebases-006/final_audit.py")
            path = root / relative; path.parent.mkdir(parents=True)
            path.write_text("raise AssertionError('unverified code was executed')\n")
            manifest = {"original_component_root": "/original/component", "files": []}
            with self.assertRaisesRegex(ValueError, "inventory"):
                load_auditor(Evidence(root, manifest))
            manifest["files"] = [{"path": relative.as_posix()}]
            with self.assertRaisesRegex(ValueError, "SHA-256"):
                load_auditor(Evidence(root, manifest))

    def test_numeric_payload_selection_excludes_tables_code_and_builds(self):
        for path in ("performance/run001/sample.latency.u64", "verification/reader.jsonl", "protocol/block-01.fen"):
            self.assertTrue(numeric_payload(Path(path)))
        for path in ("KQvK.rtbw", "KQvK.RTBZ", "opponent.cpp", "engine", "build/config.json", "target/runtime.json", "__pycache__/x.pyc"):
            with self.subTest(path=path):
                self.assertFalse(numeric_payload(Path(path)))


if __name__ == "__main__":
    unittest.main()
