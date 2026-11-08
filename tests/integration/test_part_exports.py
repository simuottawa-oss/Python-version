"""Editable part saves stay separate from geometry-only mesh export."""
import copy
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import numpy as np

from PySide6.QtWidgets import QApplication, QMessageBox
from simuo.parts.part_assets import load_asset
from simuo.ui.parts.part_editor import PartEditor
from simuo.parts.part_export import export_sketch
from simuo.parts.sketch_geometry import Sketch


class PartExportTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="SimuO part exports ")
        self.addCleanup(self.temp.cleanup)
        self.folder = Path(self.temp.name)
        self.editor = PartEditor()
        self.editor.sketch = Sketch([[0,0],[.1,0],[.1,.2],[0,.2]], True, [None]*4, .01)
        self.editor.dirty = True
        self.addCleanup(self.editor.deleteLater)

    def test_file_menu_exports_both_formats_without_saving_or_changing_document(self):
        editor = self.editor
        before = copy.deepcopy(editor.sketch.geometry())
        menu = editor.menuBar().actions()[0].menu()
        self.assertIn("Save SimuO Part", [a.text() for a in menu.actions()])
        export_menu = next(a.menu() for a in menu.actions() if a.text() == "Export")
        for action, suffix in zip(export_menu.actions(), ("obj", "stl")):
            path = self.folder / ("mesh."+suffix)
            with patch("simuo.ui.parts.part_editor.QFileDialog.getSaveFileName", return_value=(str(path), "")):
                action.trigger()
            self.assertTrue(path.exists())
        self.assertEqual(editor.sketch.geometry(), before)
        self.assertTrue(editor.dirty)
        self.assertIsNone(editor.path)

    def test_obj_and_stl_preserve_concave_geometry_volume_and_winding(self):
        points = [[0,0],[.2,0],[.2,.1],[.1,.1],[.1,.2],[0,.2]]
        for outline in (points, list(reversed(points))):
            sketch = Sketch(outline, True, [None]*6, .03)
            obj = self.folder / "concave.obj"
            stl = self.folder / "concave.stl"
            export_sketch(obj, sketch, "obj")
            export_sketch(stl, sketch, "stl")
            obj_vertices = load_asset(obj).vertices.reshape(-1,3,6)[:,:,:3]
            stl_vertices = np.array([list(map(float,line.split()[1:])) for line in stl.read_text().splitlines() if line.strip().startswith("vertex ")]).reshape(-1,3,3)
            normals = np.array([list(map(float,line.split()[2:])) for line in stl.read_text().splitlines() if line.strip().startswith("facet normal ")])
            np.testing.assert_allclose(obj_vertices, stl_vertices, atol=1e-8)
            cross = np.cross(stl_vertices[:,1]-stl_vertices[:,0], stl_vertices[:,2]-stl_vertices[:,0])
            self.assertTrue(np.all(np.einsum('ij,ij->i', cross, normals) > 0))
            volume = np.einsum('ij,ij->i', stl_vertices[:,0], np.cross(stl_vertices[:,1], stl_vertices[:,2])).sum()/6
            self.assertAlmostEqual(volume, abs(sketch.signed_area)*sketch.thickness, places=9)

    def test_open_draft_can_save_native_but_cannot_export_mesh(self):
        self.editor.sketch = Sketch([[0,0],[.1,0]], False, [None], .01)
        path = self.folder / "draft.simuOPart"
        with patch("simuo.ui.parts.part_editor.QFileDialog.getSaveFileName", return_value=(str(path), "")):
            self.assertTrue(self.editor.save())
        self.assertFalse(json.loads(path.read_text())["geometry"]["closed"])
        with patch("simuo.ui.parts.part_editor.QMessageBox.warning") as warning, patch("simuo.ui.parts.part_editor.QFileDialog.getSaveFileName") as dialog:
            self.assertFalse(self.editor.export_mesh("stl"))
            warning.assert_called_once()
            dialog.assert_not_called()

    def test_canceled_and_failed_exports_keep_native_path_and_unsaved_changes(self):
        editor = self.editor
        editor.path = self.folder / "working.simuOPart"
        original = editor.path
        with patch("simuo.ui.parts.part_editor.QFileDialog.getSaveFileName", return_value=("", "")):
            self.assertFalse(editor.export_mesh("obj"))
        target = self.folder / "missing" / "mesh.stl"
        with patch("simuo.ui.parts.part_editor.QFileDialog.getSaveFileName", return_value=(str(target), "")), patch("simuo.ui.parts.part_editor.QMessageBox.warning") as warning:
            self.assertFalse(editor.export_mesh("stl"))
            warning.assert_called_once()
        self.assertEqual(editor.path, original)
        self.assertTrue(editor.dirty)

    def test_normalized_export_extension_checks_before_replacing(self):
        path = self.folder / "existing.obj"
        path.write_bytes(b"keep me")
        with patch("simuo.ui.parts.part_editor.QFileDialog.getSaveFileName", return_value=(str(path.with_suffix(".txt")), "")), patch("simuo.ui.parts.part_editor.QMessageBox.question", return_value=QMessageBox.Cancel):
            self.assertFalse(self.editor.export_mesh("obj"))
        self.assertEqual(path.read_bytes(), b"keep me")


if __name__ == "__main__":
    unittest.main()
