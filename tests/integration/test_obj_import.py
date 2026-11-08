"""OBJ import/save workflow with Qt widgets and a stubbed GPU viewport."""
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from PySide6.QtWidgets import QApplication, QWidget, QMessageBox
from PySide6.QtGui import QCloseEvent
from tests.support import create_scene_window
from simuo.project.scene import SceneObject
from simuo.project.temporary_parts import TemporaryParts

OBJ = 'v 0 0 0\nv 1 0 0\nv 0 1 0\nf 1 2 3\n'


from tests.integration.viewport_stub import ViewportStub as Viewport


class ObjImportTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        self.folder = tempfile.TemporaryDirectory(prefix='simuo obj qa ')
        self.addCleanup(self.folder.cleanup)
        self.root = Path(self.folder.name)
        self.source = self.root / 'source.OBJ'
        self.source.write_text(OBJ)
        self.viewportPatch = patch('simuo.ui.scene_window.OpenGLViewport', Viewport)
        self.viewportPatch.start()
        self.addCleanup(self.viewportPatch.stop)
        self.window = create_scene_window()
        self.addCleanup(self.dispose)

    def dispose(self):
        self.window.temporaryParts.cleanup()
        with patch('simuo.ui.scene_window.QMessageBox.question', return_value=QMessageBox.Discard):
            self.window.close()

    def import_obj(self, answer=QMessageBox.Yes):
        with patch('simuo.ui.scene_window.QFileDialog.getOpenFileName', return_value=(str(self.source), '')), \
             patch('simuo.ui.scene_window.QMessageBox.question', return_value=answer):
            self.window.importFile()

    def test_import_snapshots_obj_and_lists_temporary_part(self):
        self.import_obj()
        obj = self.window.scene.objects[0]
        self.assertEqual(obj.meshPath.suffix, '.simuOPart')
        self.assertEqual(obj.meshPath.read_text(), OBJ)
        self.assertEqual(obj.asset.vertices.size, 18)
        self.assertEqual(self.window.temporaryPartsList.count(), 1)
        self.source.unlink()
        self.assertEqual(SceneObject(meshPath=obj.meshPath).asset.vertices.size, 18)

    def test_cancel_conversion_does_not_import(self):
        self.import_obj(QMessageBox.Cancel)
        self.assertEqual(self.window.scene.objects, [])
        self.assertFalse(self.window.temporaryParts.sources)

    def test_same_name_imports_get_distinct_files(self):
        self.import_obj()
        self.import_obj()
        paths = [obj.meshPath for obj in self.window.scene.objects]
        self.assertEqual(len(set(paths)), 2)
        self.assertEqual(self.window.temporaryPartsList.count(), 2)

    def test_invalid_obj_preserves_scene_and_removes_failed_file(self):
        self.source.write_text('not an OBJ')
        with patch('simuo.ui.scene_window.QMessageBox.warning') as warning:
            self.import_obj()
        warning.assert_called_once()
        self.assertEqual(self.window.scene.objects, [])
        self.assertFalse(self.window.temporaryParts.sources)
        self.assertEqual(list(self.window.temporaryParts.directory.iterdir()), [])

    def test_scene_save_prompts_for_part_and_reopens_without_temp(self):
        self.import_obj()
        temporary = self.window.scene.objects[0].meshPath
        scene = self.root / 'scene.simuO'
        part = self.root / 'saved part.simuOPart'
        with patch('simuo.ui.scene_window.QFileDialog.getSaveFileName', side_effect=[(str(scene), ''), (str(part), '')]) as dialog:
            self.assertTrue(self.window.saveFile())
            self.assertEqual(dialog.call_count, 2)
        self.assertFalse(temporary.exists())
        self.assertEqual(part.read_text(), OBJ)
        self.assertEqual(self.window.scene.objects[0].meshPath, part.resolve())
        self.assertEqual(self.window.temporaryPartsList.count(), 0)
        stored = json.loads(scene.read_text())
        self.assertEqual(stored['objects'][0]['meshPath'], 'saved part.simuOPart')
        self.window.loadFile(scene, uploadToGPU=False)
        self.assertEqual(self.window.scene.objects[0].meshPath, part.resolve())
        with patch('simuo.ui.scene_window.QFileDialog.getSaveFileName') as dialog:
            self.assertTrue(self.window.saveFile())
            dialog.assert_not_called()

    def test_cancel_second_part_writes_nothing(self):
        self.import_obj()
        self.import_obj()
        scene = self.root / 'scene.simuO'
        part = self.root / 'one.simuOPart'
        with patch('simuo.ui.scene_window.QFileDialog.getSaveFileName', side_effect=[(str(scene), ''), (str(part), ''), ('', '')]):
            self.assertFalse(self.window.saveFile())
        self.assertFalse(scene.exists())
        self.assertFalse(part.exists())
        self.assertIsNone(self.window.projectPath)
        self.assertEqual(len(self.window.temporaryParts.sources), 2)

    def test_cancel_save_as_keeps_existing_project_path(self):
        self.window.projectPath = self.root / 'old.simuO'
        self.import_obj()
        with patch('simuo.ui.scene_window.QFileDialog.getSaveFileName', side_effect=[(str(self.root / 'new.simuO'), ''), ('', '')]):
            self.assertFalse(self.window.saveAsFile())
        self.assertEqual(self.window.projectPath, self.root / 'old.simuO')

    def test_failed_part_write_keeps_temp_and_old_project(self):
        self.import_obj()
        temporary = self.window.scene.objects[0].meshPath
        scene = self.root / 'new.simuO'
        with patch('simuo.ui.scene_window.QFileDialog.getSaveFileName', return_value=(str(self.root / 'part.simuOPart'), '')), \
             patch('simuo.ui.scene_window.atomic_write', side_effect=OSError('disk full')), \
             patch('simuo.ui.scene_window.QMessageBox.warning') as warning:
            self.assertFalse(self.window.saveFile(destination=scene))
        warning.assert_called_once()
        self.assertTrue(temporary.exists())
        self.assertIsNone(self.window.projectPath)
        self.assertFalse(scene.exists())

    def test_shared_part_is_saved_and_prompted_once(self):
        self.import_obj()
        shared = SceneObject(meshPath=self.window.scene.objects[0].meshPath)
        self.window.scene.addObject(shared)
        target = self.root / 'shared.simuOPart'
        with patch('simuo.ui.scene_window.QFileDialog.getSaveFileName', return_value=(str(target), '')) as dialog:
            self.assertTrue(self.window.saveFile(destination=self.root / 'scene.simuO'))
            dialog.assert_called_once()
        self.assertEqual([obj.meshPath for obj in self.window.scene.objects], [target.resolve(), target.resolve()])

    def test_close_cancel_preserves_parts_and_discard_cleans_directory(self):
        self.import_obj()
        directory = self.window.temporaryParts.directory
        event = QCloseEvent()
        with patch('simuo.ui.scene_window.QMessageBox.question', return_value=QMessageBox.Cancel):
            self.window.closeEvent(event)
        self.assertFalse(event.isAccepted())
        self.assertTrue(directory.exists())
        with patch('simuo.ui.scene_window.QMessageBox.question', return_value=QMessageBox.Discard):
            self.window.closeEvent(event)
        self.assertTrue(event.isAccepted())
        self.assertFalse(directory.exists())

    def test_new_scene_cancelled_save_keeps_objects(self):
        self.import_obj()
        with patch('simuo.ui.scene_window.QMessageBox.question', return_value=QMessageBox.Save), \
             patch('simuo.ui.scene_window.QFileDialog.getSaveFileName', return_value=('', '')):
            self.window.newProject()
        self.assertEqual(len(self.window.scene.objects), 1)
        self.assertEqual(len(self.window.temporaryParts.sources), 1)

    def test_cannot_save_part_into_temporary_directory(self):
        self.import_obj()
        target = self.window.temporaryParts.directory / 'still temporary.simuOPart'
        with patch('simuo.ui.scene_window.QFileDialog.getSaveFileName', return_value=(str(target), '')), \
             patch('simuo.ui.scene_window.QMessageBox.warning') as warning:
            self.assertFalse(self.window.saveFile(destination=self.root / 'scene.simuO'))
        warning.assert_called_once()
        self.assertFalse(target.exists())


if __name__ == '__main__':
    unittest.main()
