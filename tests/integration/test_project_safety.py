"""File-operation regressions using real Qt dialogs with scripted responses."""
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from PySide6.QtCore import QTimer
from PySide6.QtGui import QCloseEvent
from PySide6.QtWidgets import QApplication, QWidget, QMessageBox, QDoubleSpinBox, QDialogButtonBox
from tests import ROOT
from simuo.project.scene import SceneObject
from tests.support import create_scene_window


from tests.integration.viewport_stub import ViewportStub as Viewport


class ProjectSafetyTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="simuo-safety-")
        self.addCleanup(self.temp.cleanup)
        self.folder = Path(self.temp.name)
        viewport = patch("simuo.ui.scene_window.OpenGLViewport", Viewport)
        viewport.start()
        self.addCleanup(viewport.stop)
        self.window = create_scene_window()
        self.obj = SceneObject(meshPath=ROOT / "Assets/cube.simuOPart")
        self.window.scene.addObject(self.obj)
        self.window.viewport.addNewObject(self.obj)
        self.window.scene.dirty = True
        self.original = self.folder / "original.simuO"
        self.window.projectPath = self.original
        self.window.setWindowTitle("Original title")
        self.empty = self.folder / "empty.simuO"
        self.empty.write_text(json.dumps({"version": 1, "objects": []}))
        self.addCleanup(self.window.deleteLater)
        self.addCleanup(self.window.temporaryParts.cleanup)

    def perform(self, operation):
        if operation == "open":
            with patch("simuo.ui.scene_window.QFileDialog.getOpenFileName", return_value=(str(self.empty), "")):
                self.window.openFile()
        elif operation == "new":
            self.window.newProject()
        else:
            event = QCloseEvent()
            self.window.closeEvent(event)
            return event.isAccepted()

    def assert_preserved(self):
        self.assertEqual(self.window.scene.objects, [self.obj])
        self.assertEqual(self.window.viewport.renderObjects, [self.obj])
        self.assertEqual(self.window.projectPath, self.original)
        self.assertTrue(self.window.scene.dirty)

    def test_cancel_protects_open_new_and_close(self):
        for operation in ("open", "new", "close"):
            with self.subTest(operation=operation), patch("simuo.ui.scene_window.QMessageBox.question", return_value=QMessageBox.Cancel) as prompt:
                result = self.perform(operation)
                prompt.assert_called_once()
                self.assert_preserved()
                if operation == "close":
                    self.assertFalse(result)

    def test_failed_save_prevents_open_new_and_close(self):
        for operation in ("open", "new", "close"):
            with self.subTest(operation=operation), patch("simuo.ui.scene_window.QMessageBox.question", return_value=QMessageBox.Save), patch("simuo.ui.scene_window.atomic_write", side_effect=PermissionError("Read-only folder")), patch("simuo.ui.scene_window.QMessageBox.warning") as warning:
                result = self.perform(operation)
                warning.assert_called_once()
                self.assert_preserved()
                if operation == "close":
                    self.assertFalse(result)

    def test_cancelled_save_dialog_prevents_open_new_and_close(self):
        self.window.projectPath = None
        for operation in ("open", "new", "close"):
            with self.subTest(operation=operation), patch("simuo.ui.scene_window.QMessageBox.question", return_value=QMessageBox.Save), patch("simuo.ui.scene_window.QFileDialog.getSaveFileName", return_value=("", "")):
                result = self.perform(operation)
                self.assertEqual(self.window.scene.objects, [self.obj])
                self.assertIsNone(self.window.projectPath)
                self.assertTrue(self.window.scene.dirty)
                if operation == "close":
                    self.assertFalse(result)

    def test_failed_save_as_preserves_file_path_title_and_scene(self):
        self.original.write_text("original contents")
        invalid = self.folder / "missing-parent" / "scene.simuO"
        with patch("simuo.ui.scene_window.QFileDialog.getSaveFileName", return_value=(str(invalid), "")), patch("simuo.ui.scene_window.QMessageBox.warning") as warning:
            self.assertFalse(self.window.saveAsFile())
            warning.assert_called_once()
        self.assert_preserved()
        self.assertEqual(self.window.windowTitle(), "Original title")
        self.assertEqual(self.original.read_text(), "original contents")
        self.assertFalse(invalid.exists())

    def test_successful_save_before_open_preserves_work_on_disk(self):
        self.obj.position = [1, 2, 3]
        with patch("simuo.ui.scene_window.QMessageBox.question", return_value=QMessageBox.Save):
            self.perform("open")
        self.assertEqual(json.loads(self.original.read_text())["objects"][0]["position"], [1, 2, 3])
        self.assertEqual(self.window.scene.objects, [])
        self.assertEqual(self.window.projectPath, self.empty)
        self.assertFalse(self.window.scene.dirty)

    def test_failed_atomic_replace_preserves_previous_saved_file(self):
        previous = b'{"version": 1, "objects": []}'
        self.original.write_bytes(previous)
        with patch("simuo.project.temporary_parts.os.replace", side_effect=PermissionError("File is read-only")), patch("simuo.ui.scene_window.QMessageBox.warning") as warning:
            self.assertFalse(self.window.saveFile())
            warning.assert_called_once()
        self.assertEqual(self.original.read_bytes(), previous)
        self.assertEqual(list(self.folder.glob(".original.simuO.*")), [])
        self.assert_preserved()

    def test_discard_opens_without_saving(self):
        with patch("simuo.ui.scene_window.QMessageBox.question", return_value=QMessageBox.Discard):
            self.perform("open")
        self.assertEqual(self.window.scene.objects, [])
        self.assertFalse(self.original.exists())

    def test_saved_scene_does_not_prompt_on_close(self):
        self.assertTrue(self.window.saveFile())
        with patch("simuo.ui.scene_window.QMessageBox.question") as prompt:
            self.assertTrue(self.perform("close"))
            prompt.assert_not_called()

    def test_unsaved_scene_prompts_even_without_dirty_flag(self):
        self.window.projectPath = None
        self.window.scene.dirty = False
        with patch("simuo.ui.scene_window.QMessageBox.question", return_value=QMessageBox.Cancel) as prompt:
            self.assertFalse(self.perform("close"))
            prompt.assert_called_once()

    def test_transform_dialogs_mark_saved_scene_dirty(self):
        for method in (self.window.openPositionDialog, self.window.openSetRotationDialog):
            with self.subTest(method=method.__name__):
                self.window.scene.dirty = False
                def accept():
                    dialog = self.app.activeModalWidget()
                    dialog.findChildren(QDoubleSpinBox)[0].setValue(25)
                    dialog.findChild(QDialogButtonBox).accepted.emit()
                QTimer.singleShot(0, accept)
                method(self.obj)
                self.assertTrue(self.window.scene.dirty)


if __name__ == "__main__":
    unittest.main()
