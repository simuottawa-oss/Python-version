"""Failure-path checks for the environment diagnostics (standard library only)."""

import contextlib
import importlib.util
import io
from pathlib import Path
import stat
import subprocess
import sys
import tempfile
import types
import unittest
from unittest.mock import patch, Mock

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))

spec = importlib.util.spec_from_file_location("setup_checker", ROOT / "tools/check_setup.py")
checker = importlib.util.module_from_spec(spec)
spec.loader.exec_module(checker)


class PluginChecks(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.directory = Path(self.temp.name)
        self.plugin = self.directory / "platforms/libqcocoa.dylib"
        self.plugin.parent.mkdir()
        library_info = types.SimpleNamespace(PluginsPath=0, path=lambda _: str(self.directory))
        qt_core = types.SimpleNamespace(QLibraryInfo=library_info)
        self.enterContext(patch.dict(sys.modules, {"PySide6.QtCore": qt_core}))
        self.enterContext(patch.object(checker.sys, "platform", "darwin"))
        self.enterContext(patch.dict(checker.os.environ, {"QT_QPA_PLATFORM_PLUGIN_PATH": ""}))

    def test_missing_plugin_reports_the_expected_location(self):
        plugin, problem = checker.macos_qt_plugin_status()
        self.assertEqual(plugin, self.plugin)
        self.assertIn("missing", problem)

    def test_visible_plugin_is_accepted_without_modification(self):
        self.plugin.write_bytes(b"plugin fixture")
        before = self.plugin.stat()
        self.assertEqual(checker.macos_qt_plugin_status(), (self.plugin, None))
        self.assertEqual(self.plugin.read_bytes(), b"plugin fixture")
        self.assertEqual(self.plugin.stat().st_mtime_ns, before.st_mtime_ns)

    def test_hidden_plugin_is_reported_without_repair(self):
        info = types.SimpleNamespace(st_mode=stat.S_IFREG, st_flags=stat.UF_HIDDEN)
        with patch.object(Path, "stat", return_value=info):
            plugin, problem = checker.macos_qt_plugin_status()
        self.assertEqual(plugin, self.plugin)
        self.assertIn("hidden", problem)

    def test_explicit_plugin_directory_is_supported(self):
        plugin = self.directory / "override/libqcocoa.dylib"
        plugin.parent.mkdir()
        plugin.write_bytes(b"plugin fixture")
        with patch.dict(checker.os.environ, {"QT_QPA_PLATFORM_PLUGIN_PATH": str(plugin.parent)}):
            self.assertEqual(checker.macos_qt_plugin_status(), (plugin, None))

    def test_windows_skips_the_macos_check(self):
        with patch.object(checker.sys, "platform", "win32"):
            self.assertEqual(checker.macos_qt_plugin_status(), (None, None))

    def test_unreadable_plugin_is_reported(self):
        self.plugin.write_bytes(b"plugin fixture")
        with patch.object(checker.os, "access", return_value=False):
            self.assertIn("not readable", checker.macos_qt_plugin_status()[1])


class CheckerFailures(unittest.TestCase):
    def setUp(self):
        self.output = io.StringIO()
        self.enterContext(contextlib.redirect_stdout(self.output))

    def test_python_startup_timeout_has_recovery_instructions(self):
        error = subprocess.TimeoutExpired("python", 15)
        with patch.object(checker, "run_python", side_effect=error):
            self.assertEqual(checker.bootstrap([]), 1)
        self.assertIn("outside iCloud", self.output.getvalue())

    def test_python_outside_the_pinned_dependency_range_is_rejected(self):
        for version in ((3, 9), (3, 15)):
            with self.subTest(version=version), patch.object(checker.sys, "version_info", version), patch.object(checker, "check_dependencies") as dependencies:
                self.assertEqual(checker.main([]), 1)
                dependencies.assert_not_called()
        self.assertIn("CPython 3.10–3.14", self.output.getvalue())

    def test_other_python_versions_in_the_dependency_range_are_allowed(self):
        for version in ((3, 10), (3, 11), (3, 13), (3, 14)):
            with self.subTest(version=version), patch.object(checker.sys, "version_info", version), patch.object(checker.sys, "prefix", "test-venv"), patch.object(checker, "check_dependencies", return_value=True), patch.object(checker, "check_plugin", return_value=True):
                self.assertEqual(checker.main([]), 0)

    def test_python_startup_error_does_not_launch_the_checker(self):
        result = subprocess.CompletedProcess([], 1, "", "init_import_site: timeout")
        with patch.object(checker, "run_python", return_value=result), patch.object(checker.os, "execv") as execute:
            self.assertEqual(checker.bootstrap([]), 1)
        execute.assert_not_called()
        self.assertIn("init_import_site", self.output.getvalue())

    def test_missing_dependencies_are_reported_before_importing(self):
        with patch.object(checker.importlib.metadata, "version", side_effect=checker.importlib.metadata.PackageNotFoundError), patch.object(checker, "run_python") as run:
            self.assertFalse(checker.check_dependencies())
        run.assert_not_called()
        self.assertIn("pip install", self.output.getvalue())

    def test_wrong_pinned_version_is_reported(self):
        with patch.object(checker.importlib.metadata, "version", return_value="0.0"), patch.object(checker, "run_python") as run:
            self.assertFalse(checker.check_dependencies())
        run.assert_not_called()
        self.assertIn("specifies 6.11.2", self.output.getvalue())

    def test_dependency_import_crash_is_reported(self):
        result = subprocess.CompletedProcess([], -6, "Importing PySide6", "native import failed")
        with patch.object(checker.importlib.metadata, "version", return_value="6.11.2"), patch.object(checker, "run_python", return_value=result):
            self.assertFalse(checker.check_dependencies())
        self.assertIn("native import failed", self.output.getvalue())

    def test_graphics_process_crash_is_reported(self):
        result = subprocess.CompletedProcess([], -6, "", "platform plugin failed")
        with patch.object(checker.sys, "prefix", "test-venv"), patch.object(checker, "check_dependencies", return_value=True), patch.object(checker, "check_plugin", return_value=True), patch.object(checker, "run_python", return_value=result):
            self.assertEqual(checker.main(["--graphics"]), 1)
        self.assertIn("platform plugin failed", self.output.getvalue())

    def test_plugin_diagnosis_is_read_only(self):
        plugin = Mock()
        with patch.object(checker, "macos_qt_plugin_status", return_value=(plugin, "hidden")), patch.object(checker.os, "chflags", create=True) as change:
            self.assertFalse(checker.check_plugin())
        change.assert_not_called()
        self.assertIn("WARN:", self.output.getvalue())
        self.assertIn("--graphics", self.output.getvalue())

    def test_plugin_warning_does_not_block_actual_graphics_probe(self):
        result = subprocess.CompletedProcess([], 0, "Native Qt startup passed", "")
        with patch.object(checker.sys, "prefix", "test-venv"), patch.object(checker, "check_dependencies", return_value=True), patch.object(checker, "check_plugin", return_value=False), patch.object(checker, "run_python", return_value=result) as run:
            self.assertEqual(checker.main(["--graphics"]), 0)
        run.assert_called_once()
        self.assertIn("Native Qt startup passed", self.output.getvalue())

    def test_metadata_warnings_do_not_claim_graphics_were_tested(self):
        with patch.object(checker.sys, "prefix", "test-venv"), patch.object(checker, "check_dependencies", return_value=True), patch.object(checker, "check_plugin", return_value=False):
            self.assertEqual(checker.main([]), 0)
        self.assertIn("Qt startup and rendering have not been tested", self.output.getvalue())
        self.assertNotIn("Setup and graphics checks passed", self.output.getvalue())

    def test_removed_repair_option_is_rejected(self):
        with contextlib.redirect_stderr(self.output), self.assertRaises(SystemExit) as exit_code:
            checker.main(["--repair-qt-plugin"])
        self.assertEqual(exit_code.exception.code, 2)


if __name__ == "__main__":
    unittest.main()
