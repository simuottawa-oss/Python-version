"""Scene deletion picks instances, updates rendering, and preserves source files."""
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import Mock, patch


from PySide6.QtCore import QTimer
from PySide6.QtWidgets import QApplication, QDialog, QDialogButtonBox, QListWidget, QWidget
from simuo.physics.viewport.renderer import OpenGLViewport
from simuo.project.scene import SceneObject
from tests.support import create_scene_window


from tests.integration.viewport_stub import ViewportStub as Viewport


class SceneDeletionTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        viewport = patch("simuo.ui.scene_window.OpenGLViewport", Viewport)
        viewport.start()
        self.addCleanup(viewport.stop)
        self.window = create_scene_window()
        self.addCleanup(self.window.deleteLater)
        self.addCleanup(self.window.temporaryParts.cleanup)
        self.folder = tempfile.TemporaryDirectory()
        self.addCleanup(self.folder.cleanup)
        self.source = Path(self.folder.name) / "shared.simuOPart"
        self.source.write_text("original part")

    def add(self, name="Repeated name"):
        obj = SceneObject(name)
        obj.meshPath = self.source
        self.window.scene.addObject(obj)
        self.window.viewport.renderObjects.append(obj)
        return obj

    def test_side_button_deletes_chosen_instance_and_save_omits_it(self):
        axis = self.add("Axis")
        first, second = self.add(), self.add()
        def choose():
            picker = self.app.activeModalWidget()
            picker.findChild(QListWidget).setCurrentRow(1)
            buttons = picker.findChild(QDialogButtonBox)
            next(b for b in buttons.buttons() if b.text() == "Delete").click()
        QTimer.singleShot(0, choose)
        self.window.deletePartAction.trigger()
        self.assertEqual(self.window.scene.objects, [axis, first])
        self.assertEqual(self.window.viewport.renderObjects, [axis, first])
        self.assertNotIn(second, self.window.scene.objects)
        self.assertTrue(self.window.scene.dirty)
        self.assertEqual(self.source.read_text(), "original part")
        path = Path(self.folder.name) / "scene.simuO"
        self.assertTrue(self.window.saveFile(destination=path))
        self.assertEqual(len(json.loads(path.read_text())["objects"]), 1)

    def test_cancel_and_empty_scene_do_not_change_scene(self):
        obj = self.add()
        QTimer.singleShot(0, lambda: self.app.activeModalWidget().reject())
        self.window.deletePartAction.trigger()
        self.assertEqual(self.window.scene.objects, [obj])
        self.assertFalse(self.window.scene.dirty)
        self.window.scene.objects.clear()
        with patch("simuo.ui.scene_window.QMessageBox.information") as message:
            self.window.deletePartAction.trigger()
        message.assert_called_once()
        self.assertFalse(self.window.scene.dirty)

    def test_temporary_part_stays_available_to_undo_deletion(self):
        temporary = self.window.temporaryParts.create(self.source)
        first, second = self.add(), self.add()
        first.meshPath = second.meshPath = temporary
        self.window.deleteScenePart(first)
        self.assertTrue(temporary.exists())
        self.assertTrue(self.window.temporaryParts.contains(temporary))
        self.window.deleteScenePart(second)
        self.assertEqual(self.window.active_temporary_parts(), [])
        self.window.editor_state.undo_stack.undo()
        self.assertTrue(temporary.exists())
        self.assertEqual(self.window.active_temporary_parts(), [temporary])
        self.assertTrue(self.source.exists())

    def test_renderer_frees_only_the_selected_objects_buffers(self):
        first, second = object(), object()
        render_first = {"SceneObject": first, "vao": 11, "vbo": 12}
        render_second = {"SceneObject": second, "vao": 21, "vbo": 22}
        viewport = Mock(renderObjects=[render_first, render_second])
        with patch("simuo.physics.viewport.renderer.glDeleteVertexArrays") as arrays, patch("simuo.physics.viewport.renderer.glDeleteBuffers") as buffers:
            OpenGLViewport.removeObject(viewport, second)
        self.assertEqual(viewport.renderObjects, [render_first])
        arrays.assert_called_once_with(1, [21])
        buffers.assert_called_once_with(1, [22])
        viewport.makeCurrent.assert_called_once()
        viewport.doneCurrent.assert_called_once()


if __name__ == "__main__":
    unittest.main()
