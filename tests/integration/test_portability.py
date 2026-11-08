"""Portable scene references and Windows-compatible atomic file cleanup."""
import json
import os
import subprocess
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

from tests import ROOT
from simuo.project.project_paths import resolve_mesh_path, stored_mesh_path
from simuo.resources.paths import resource_path
from simuo.project.temporary_parts import atomic_write


class PortabilityTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="SimuO portable path ")
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.project = self.root / "scene folder" / "scene.simuO"
        self.project.parent.mkdir()
        self.mesh = self.root / "models" / "cube.simuOPart"
        self.mesh.parent.mkdir()
        self.mesh.write_text("mesh placeholder", encoding="utf-8")

    def test_native_absolute_mesh_takes_priority_over_bundled_name(self):
        # This also tests actual drive-letter paths when run on Windows.
        self.assertEqual(resolve_mesh_path(str(self.mesh), self.project), self.mesh.resolve())

    def test_relative_paths_roundtrip_with_spaces_and_backslashes(self):
        reference = stored_mesh_path(self.mesh, self.project)
        self.assertNotIn("\\", reference)
        for value in (reference, reference.replace("/", "\\")):
            self.assertEqual(resolve_mesh_path(value, self.project), self.mesh.resolve())

    def test_stale_windows_drive_and_unc_paths_recover_bundled_mesh(self):
        for value in (r"Z:\old installation\cube.simuOPart", r"\\missing-server\share\cube.simuOPart"):
            self.assertEqual(resolve_mesh_path(value, self.project), (ROOT / "Assets/cube.simuOPart").resolve())

    def test_cross_drive_save_falls_back_to_absolute_reference(self):
        with patch("simuo.project.project_paths.os.path.relpath", side_effect=ValueError("different drives")):
            reference = stored_mesh_path(self.mesh, self.project)
        self.assertEqual(Path(reference), self.mesh.resolve())

    def test_packaged_resources_use_bundle_directory(self):
        with patch.object(sys, "frozen", True, create=True), patch.object(sys, "_MEIPASS", str(self.root), create=True):
            self.assertEqual(resource_path("Images", "logo.png"), self.root / "Images/logo.png")

    def test_failed_write_closes_file_before_cleanup_and_preserves_original(self):
        target = self.root / "scene.simuO"
        target.write_bytes(b"previous scene")
        streams = []
        original_factory = tempfile.NamedTemporaryFile
        original_unlink = Path.unlink

        def factory(*args, **kwargs):
            stream = original_factory(*args, **kwargs)
            streams.append(stream)
            return stream

        def unlink(path, *args, **kwargs):
            self.assertTrue(all(stream.closed for stream in streams), "Deleting an open file fails on Windows")
            return original_unlink(path, *args, **kwargs)

        with patch("simuo.project.temporary_parts.tempfile.NamedTemporaryFile", side_effect=factory), patch("simuo.project.temporary_parts.os.fsync", side_effect=OSError("disk full")), patch.object(Path, "unlink", unlink):
            with self.assertRaisesRegex(OSError, "disk full"):
                atomic_write(target, b"new scene")
        self.assertEqual(target.read_bytes(), b"previous scene")
        self.assertEqual(list(self.root.glob(".scene.simuO.*")), [])

    def test_repository_scenes_reference_existing_relative_parts(self):
        """Require shipped scenes to work directly after relocation, without recovery paths."""
        projects = list((ROOT / "Assets").glob("*.simuO"))
        projects += list((ROOT / "tests/fixtures").glob("*.simuO"))
        self.assertTrue(projects)
        for project in projects:
            for item in json.loads(project.read_text(encoding="utf-8"))["objects"]:
                reference = item["meshPath"]
                with self.subTest(project=project.name, reference=reference):
                    self.assertFalse(Path(reference).is_absolute())
                    target = (project.parent / reference).resolve()
                    self.assertTrue(target.is_file(), str(target))
                    self.assertEqual(resolve_mesh_path(reference, project), target)

    def test_launchers_work_outside_repository_without_pythonpath(self):
        """Exercise source/launcher imports from a different directory with spaces.

        Returns:
            None. Checks process exit status and command-line help output.
        """
        commands = [[sys.executable, str(ROOT / "src/main.py"), "--help"]]
        if os.name == "nt":
            commands.append(["cmd", "/d", "/c", str(ROOT / "Testing/Tools/run.bat"), "--help"])
        else:
            commands.append([str(ROOT / "Testing/Tools/run.sh"), "--help"])
        environment = os.environ.copy()
        environment.pop("PYTHONPATH", None)
        environment["SIMUO_PYTHON"] = sys.executable
        environment["PYTHONDONTWRITEBYTECODE"] = "1"
        for command in commands:
            with self.subTest(command=command):
                result = subprocess.run(
                    command, cwd=self.root, env=environment,
                    capture_output=True, text=True, timeout=30,
                )
                self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
                self.assertIn("--part-editor", result.stdout)

    @unittest.skipUnless(os.name == "nt", "Native Windows drive semantics")
    def test_windows_case_insensitive_native_reference(self):
        self.assertEqual(resolve_mesh_path(str(self.mesh).upper(), self.project), self.mesh.resolve())


if __name__ == "__main__":
    unittest.main()
