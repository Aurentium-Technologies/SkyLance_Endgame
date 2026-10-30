"""Checkpoint reproduction must work for both full and focused source trees."""
from pathlib import Path
import shlex
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "tools"))
import checkpoint


class CheckpointReproduction(unittest.TestCase):
    def test_component_without_presets_has_executable_cmake_commands(self):
        with tempfile.TemporaryDirectory() as tmp, patch.object(checkpoint, "ROOT", Path(tmp)):
            commands = checkpoint.build_reproduction("release")
            self.assertEqual(shlex.split(commands[0]), ["cmake", "-S", ".", "-B", "build/release",
                                                       "-DCMAKE_BUILD_TYPE=Release"])
            self.assertEqual(shlex.split(commands[1]), ["cmake", "--build", "build/release"])

    def test_reproduction_preserves_recorded_build_type_and_feature_options(self):
        with tempfile.TemporaryDirectory() as tmp, patch.object(checkpoint, "ROOT", Path(tmp)):
            build = Path(tmp) / "build" / "review release"
            build.mkdir(parents=True)
            (build / "CMakeCache.txt").write_text("CMAKE_BUILD_TYPE:STRING=Debug\n"
                                                "ORIENT_NATIVE:BOOL=OFF\n"
                                                "ORIENT_FATHOM_DYNAMIC_CATALOG:BOOL=ON\n"
                                                "CMAKE_HOME_DIRECTORY:INTERNAL=/old/source\n")
            commands = checkpoint.build_reproduction("review release")
            configure = shlex.split(commands[0])
            self.assertIn("build/review release", configure)
            self.assertIn("-DCMAKE_BUILD_TYPE=Debug", configure)
            self.assertIn("-DORIENT_NATIVE=OFF", configure)
            self.assertIn("-DORIENT_FATHOM_DYNAMIC_CATALOG=ON", configure)
            self.assertNotIn("/old/source", commands[0])

    def test_legacy_source_tree_keeps_existing_preset_reproduction(self):
        with tempfile.TemporaryDirectory() as tmp, patch.object(checkpoint, "ROOT", Path(tmp)):
            (Path(tmp) / "CMakePresets.json").write_text("{}")
            self.assertEqual(checkpoint.build_reproduction("native"),
                             ["cmake --preset native", "cmake --build --preset native"])


if __name__ == "__main__":
    unittest.main()
