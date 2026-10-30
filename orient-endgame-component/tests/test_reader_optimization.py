"""Guard performance adoption independently of the implementation."""
import json
import sys
from pathlib import Path
import tempfile
import unittest
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "tools"))
from experiment import artifact
from measure_reader_optimization import compare, verify_variant


def samples(ratio=.8):
    rows = []
    for pair in range(1, 6):
        for name, factor in (("baseline", 1), ("candidate", ratio)):
            scale = (pair + 6) / 10
            reader = {k: 100 * scale * factor for k in ("distinct_probe_ms", "distinct_probe_cpu_ms", "probe_latency_p95_us", "hot_probe_ms", "startup_ms")}
            search = {k: 100 * scale * factor for k in ("root_ms", "root_latency_p95_us", "search_ms", "distinct_lookup_ms")}
            rows.append(dict(pair=pair, variant=name, reader=reader, search=search))
    return rows


def acceptance_variant(root, cache_flags=None, command_flags=None):
    root = Path(root)
    cache_flags = cache_flags or {"ORIENT_FATHOM_PROFILE": "OFF", "ORIENT_TABLEBASE_PROFILING": "OFF"}
    if command_flags is None:
        command_flags = "-DORIENT_FATHOM_PROFILE=0 -DORIENT_TABLEBASE_PROFILING=0 -DORIENT_FATHOM_MATERIAL_KEY_CACHE=1"
    files = {name: root / name for name in ("reader", "search", "engine", "probe", "build_cache", "compile_commands")}
    for name in ("reader", "search", "engine", "probe"):
        files[name].write_bytes(("frozen " + name).encode())
    files["build_cache"].write_text("".join(f"{name}:BOOL={value}\n" for name, value in cache_flags.items()))
    files["compile_commands"].write_text(json.dumps([{"directory": str(root), "file": "tbprobe.c",
                                                     "command": "c++ " + command_flags + " -c tbprobe.c"}]))
    return {**{name: artifact(path) for name, path in files.items()}, "profiling_enabled": False}


class ReaderGates(unittest.TestCase):
    def test_target_and_adoption(self):
        r = compare(samples(), "candidate")
        self.assertAlmostEqual(r["reader_throughput"], 1.25)
        self.assertTrue(r["research_target_met"]); self.assertTrue(r["adopt"])

    def test_small_gain_can_pass_without_reaching_target(self):
        r = compare(samples(.94), "candidate")
        self.assertFalse(r["research_target_met"]); self.assertTrue(r["adopt"])

    def test_reader_gain_without_complete_root_gain_is_rejected(self):
        rows = samples()
        for r in rows:
            if r["variant"] == "candidate": r["search"]["root_ms"] /= .8
        self.assertFalse(compare(rows, "candidate")["adopt"])

    def test_regressions_reject_fast_reader(self):
        for group, key in (("reader", "probe_latency_p95_us"), ("reader", "hot_probe_ms"),
                           ("search", "root_latency_p95_us"), ("search", "search_ms"), ("search", "distinct_lookup_ms")):
            rows = samples()
            for r in rows:
                if r["variant"] == "candidate": r[group][key] *= 1.051 / .8
            with self.subTest(group=group, key=key): self.assertFalse(compare(rows, "candidate")["adopt"])

    def test_insufficient_gain_rejected(self):
        self.assertFalse(compare(samples(.99), "candidate")["adopt"])

    def test_explicit_profiling_off_build_is_accepted(self):
        with tempfile.TemporaryDirectory() as root:
            row = acceptance_variant(root)
            verify_variant(row)

    def test_profiling_on_cmake_cache_is_rejected(self):
        with tempfile.TemporaryDirectory() as root:
            for name in ("ORIENT_FATHOM_PROFILE", "ORIENT_TABLEBASE_PROFILING"):
                for enabled in ("ON", "TRUE", "YES", "1"):
                    flags = {"ORIENT_FATHOM_PROFILE": "OFF", "ORIENT_TABLEBASE_PROFILING": "OFF", name: enabled}
                    with self.subTest(name=name, value=enabled):
                        row = acceptance_variant(root, cache_flags=flags)
                        with self.assertRaisesRegex(ValueError, "instrumented acceptance CMake cache"):
                            verify_variant(row)

    def test_profiling_define_in_compile_command_is_rejected(self):
        with tempfile.TemporaryDirectory() as root:
            for flag in ("-DORIENT_FATHOM_PROFILE=1", "-DORIENT_TABLEBASE_PROFILING=1",
                         "-DORIENT_FATHOM_PROFILE"):
                with self.subTest(flag=flag):
                    row = acceptance_variant(root, command_flags=flag)
                    with self.assertRaisesRegex(ValueError, "instrumented acceptance compile command"):
                        verify_variant(row)

    def test_declared_artifact_tampering_after_initial_check_is_rejected(self):
        with tempfile.TemporaryDirectory() as root:
            for name in ("reader", "search", "engine", "probe", "build_cache", "compile_commands"):
                with self.subTest(artifact=name):
                    row = acceptance_variant(root)
                    verify_variant(row)
                    Path(row[name]["path"]).write_bytes(b"changed after declaration")
                    with self.assertRaisesRegex(ValueError, "SHA-256 mismatch"):
                        verify_variant(row)


if __name__ == "__main__": unittest.main()
