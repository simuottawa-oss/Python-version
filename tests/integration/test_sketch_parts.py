"""Sketch constraints, face meshing, editable files and scene/physics import."""
import copy
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import numpy as np

from tests import ROOT
from simuo.parts.sketch_geometry import Sketch, prism_vertices, cross
from simuo.parts.part_document import new_document, save_document, open_document
from simuo.parts.part_assets import load_asset
from simuo.parts.part_format import load_part
from simuo.physics.physics_world import PhysicsWorld
from simuo.project.scene import Scene, SceneObject


def rectangle():
    return Sketch([[0,0],[.1,0],[.1,.05],[0,.05]],True,[None]*4,.01)


class SketchTests(unittest.TestCase):
    def test_lines_close_into_face(self):
        sketch = Sketch()
        for point in [[0,0],[.1,0],[.1,.05],[0,.05]]:
            sketch.add_point(point)
        self.assertFalse(sketch.closed)
        self.assertEqual(len(sketch.edges),3)
        sketch.close()
        self.assertEqual(len(sketch.edges),4)
        self.assertAlmostEqual(sketch.signed_area,.005)
        self.assertEqual(len(sketch.triangles()),2)

    def test_driving_length_resizes_rectangle_and_preserves_axes(self):
        sketch = rectangle()
        sketch.set_dimension(0,.2)
        self.assertAlmostEqual(sketch.length(0),.2)
        self.assertAlmostEqual(sketch.length(2),.2)
        self.assertAlmostEqual(sketch.length(1),.05)
        np.testing.assert_allclose(sketch.points[0],[0,0],atol=1e-10)
        sketch.set_dimension(1,.08)
        self.assertAlmostEqual(sketch.length(0),.2)
        self.assertAlmostEqual(sketch.length(1),.08)
        self.assertAlmostEqual(sketch.length(3),.08)

    def test_conflicting_dimension_is_transactional(self):
        sketch = rectangle()
        sketch.set_dimension(0,.1)
        previous = sketch.geometry()
        with self.assertRaises(ValueError):
            sketch.set_dimension(2,.2)
        self.assertEqual(sketch.geometry(),previous)

    def test_concave_face_and_prism_volume(self):
        sketch = Sketch([[0,0],[.2,0],[.2,.05],[.05,.05],[.05,.2],[0,.2]],True,[None]*6,.01)
        for candidate in [sketch,Sketch(list(reversed(sketch.points)),True,[None]*6,.01)]:
            triangles = candidate.triangles()
            area = sum(abs(cross(*(candidate.points[i] for i in face)))/2 for face in triangles)
            self.assertAlmostEqual(area,.0175)
            mesh = prism_vertices(candidate).reshape(-1,3,6)
            volume = sum(np.dot(t[0,:3],np.cross(t[1,:3],t[2,:3]))/6 for t in mesh)
            self.assertAlmostEqual(volume,.000175,places=8)
            np.testing.assert_allclose(np.linalg.norm(mesh[:,:,3:],axis=2),1,atol=1e-6)

    def test_crossed_and_zero_area_faces_rejected(self):
        for points in [[[0,0],[.1,.1],[0,.1],[.1,0]],[[0,0],[.1,0],[.2,0]]]:
            with self.assertRaises(ValueError):
                Sketch(points,True,[None]*len(points)).validate()

    def test_collinear_segment_still_renders(self):
        sketch = Sketch([[0,0],[.05,0],[.1,0],[.1,.1],[0,.1]],True,[None]*5)
        self.assertEqual(len(sketch.triangles()),2)
        self.assertTrue(np.isfinite(prism_vertices(sketch)).all())

    def test_open_draft_roundtrips_but_cannot_import(self):
        sketch = Sketch()
        sketch.add_point([0,0])
        sketch.add_point([.1,0])
        sketch.set_dimension(0,.15)
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder)/"draft.simuOPart"
            save_document(path,new_document(),sketch)
            _,loaded = open_document(path)
            self.assertEqual(loaded.geometry(),sketch.geometry())
            with self.assertRaisesRegex(ValueError,"unfinished sketch"):
                load_asset(path)

    def test_closed_save_reopen_mesh_mass_and_physics(self):
        sketch = rectangle()
        sketch.set_dimension(0,.2)
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder)/"plate.simuOPart"
            save_document(path,new_document(),sketch)
            data,loaded = open_document(path)
            self.assertEqual(data["version"],2)
            self.assertEqual(loaded.geometry(),sketch.geometry())
            asset = load_asset(path)
            self.assertEqual(asset.vertices.size//6,36)
            self.assertAlmostEqual(asset.part.volume,.0001)
            self.assertAlmostEqual(asset.part.mass,.1)
            scene = Scene()
            scene.addObject(SceneObject(meshPath=path))
            world = PhysicsWorld(scene)
            try:
                self.assertAlmostEqual(world.masses[0],.1)
                world.step(480)
                self.assertGreater(world.scene.objects[0].position[1],.004)
                self.assertTrue(world.bullet.getContactPoints(bodyA=world.bodies[0],physicsClientId=world.client))
            finally:
                world.close()

    def test_box_opens_as_editable_rectangle(self):
        _,sketch = open_document(ROOT/"Assets/aluminum_cube.simuOPart")
        self.assertTrue(sketch.closed)
        self.assertAlmostEqual(sketch.length(0),.2)
        self.assertAlmostEqual(sketch.thickness,.2)


class SketchEditorTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        from PySide6.QtWidgets import QApplication
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        from simuo.ui.parts.part_editor import PartEditor
        self.editor = PartEditor()
        self.addCleanup(self.dispose)

    def dispose(self):
        self.editor.dirty = False
        self.editor.close()

    def test_dimension_controls_undo_and_redo(self):
        self.editor.commit(rectangle())
        self.editor.select_line(0)
        self.editor.length.setValue(200)
        self.editor.apply_dimension()
        self.assertAlmostEqual(self.editor.sketch.length(0),.2)
        self.editor.undo()
        self.assertAlmostEqual(self.editor.sketch.length(0),.1)
        self.editor.redo()
        self.assertAlmostEqual(self.editor.sketch.length(0),.2)

    def test_save_cancel_and_error_preserve_editor(self):
        self.editor.commit(rectangle())
        with patch("simuo.ui.parts.part_editor.QFileDialog.getSaveFileName",return_value=("","")):
            self.assertFalse(self.editor.save())
        self.assertTrue(self.editor.dirty)
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder)/"part.simuOPart"
            self.assertTrue(self.editor._save_to(path))
            self.assertFalse(self.editor.dirty)
            self.assertTrue(self.editor.open_path(path))
            self.assertTrue(self.editor.sketch.closed)
            with patch("simuo.parts.part_document.atomic_write",side_effect=OSError("disk full")),patch("simuo.ui.parts.part_editor.QMessageBox.warning"):
                self.assertFalse(self.editor._save_to(path))
            self.assertTrue(load_part(path).sketch.closed)

    def test_new_lines_have_no_automatic_dimension_annotations(self):
        self.editor.commit(rectangle())
        self.editor.canvas.grab()
        self.assertEqual(self.editor.sketch.dimensions, [None]*4)
        self.assertEqual(self.editor.canvas.labels, [])
        for row in range(4):
            self.assertEqual(self.editor.lines.item(row, 1).text(), "—")
        self.editor.select_line(2)
        self.assertEqual(self.editor.dimension_button.text(), "Add dimension")
        self.assertFalse(self.editor.remove_dimension_button.isEnabled())

    def test_manual_dimension_on_later_edge_has_correct_label_selection(self):
        self.editor.commit(rectangle())
        self.editor.select_line(2)
        self.editor.length.setValue(150)
        self.editor.dimension_button.click()
        self.editor.canvas.grab()
        self.assertEqual([i for i, _ in self.editor.canvas.labels], [2])
        index, point = self.editor.canvas.labels[0]
        self.assertEqual(self.editor.canvas.hit(point), index)
        self.assertEqual(self.editor.dimension_button.text(), "Update dimension")
        self.assertTrue(self.editor.remove_dimension_button.isEnabled())
        self.assertAlmostEqual(self.editor.sketch.dimensions[2], .15)
        self.assertEqual(self.editor.sketch.dimensions[:2], [None, None])

    def test_remove_dimension_hides_label_without_resizing_and_supports_undo(self):
        self.editor.commit(rectangle())
        self.editor.select_line(1)
        self.editor.length.setValue(75)
        self.editor.apply_dimension()
        points = copy.deepcopy(self.editor.sketch.points)
        self.editor.remove_dimension_button.click()
        self.editor.canvas.grab()
        self.assertEqual(self.editor.canvas.labels, [])
        self.assertEqual(self.editor.sketch.points, points)
        self.assertIsNone(self.editor.sketch.dimensions[1])
        self.editor.undo()
        self.editor.canvas.grab()
        self.assertEqual([i for i, _ in self.editor.canvas.labels], [1])
        self.editor.redo()
        self.editor.canvas.grab()
        self.assertEqual(self.editor.canvas.labels, [])

    def test_cancel_manual_dimension_does_not_constrain_or_dirty_part(self):
        self.editor.commit(rectangle())
        self.editor.dirty = False
        before = self.editor.sketch.geometry()
        with patch("simuo.ui.parts.part_editor.QInputDialog.getDouble", return_value=(200, False)):
            self.editor.dimension_dialog(0)
        self.assertEqual(self.editor.sketch.geometry(), before)
        self.assertFalse(self.editor.dirty)

    def test_only_explicit_dimensions_persist_after_save_and_reopen(self):
        self.editor.commit(rectangle())
        self.editor.select_line(3)
        self.editor.length.setValue(80)
        self.editor.apply_dimension()
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder)/"manual dimensions.simuOPart"
            self.assertTrue(self.editor._save_to(path))
            data = json.loads(path.read_text())
            self.assertEqual(data["geometry"]["dimensions"], [None, None, None, .08])
            self.assertTrue(self.editor.open_path(path))
            self.editor.canvas.grab()
            self.assertEqual([i for i, _ in self.editor.canvas.labels], [3])
            self.assertEqual(self.editor.lines.item(0, 1).text(), "—")

    def test_failed_open_keeps_current_sketch(self):
        self.editor.commit(rectangle())
        previous = self.editor.sketch.geometry()
        with patch("simuo.ui.parts.part_editor.QMessageBox.warning"):
            self.assertFalse(self.editor.open_path(ROOT/"Assets/cube.simuOPart"))
        self.assertEqual(self.editor.sketch.geometry(),previous)


if __name__=="__main__":
    unittest.main()
