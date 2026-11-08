"""Segment/feature deletion preserves remaining geometry and supports undo."""
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from PySide6.QtCore import Qt
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QMessageBox
from simuo.parts.sketch_geometry import Sketch
from simuo.ui.parts.feature_editor import FeaturePartEditor


def rectangle():
    return Sketch([[0,0],[.1,0],[.1,.1],[0,.1]], True, [.1,None,.1,None], .01)


class SegmentDeletionTests(unittest.TestCase):
    def test_closed_outline_opens_at_deleted_edge_and_preserves_dimensions(self):
        original = rectangle()
        remaining, = original.without_segment(1)
        self.assertEqual(remaining.points, [[.1,.1],[0,.1],[0,0],[.1,0]])
        self.assertEqual(remaining.dimensions, [.1,None,.1])
        self.assertFalse(remaining.closed)
        self.assertTrue(original.closed)

    def test_open_middle_edge_splits_without_inventing_a_connection(self):
        sketch = Sketch([[0,0],[.1,0],[.1,.1],[.2,.1]], False, [.1,None,.1])
        first, second = sketch.without_segment(1)
        self.assertEqual(first.points, sketch.points[:2])
        self.assertEqual(second.points, sketch.points[2:])
        self.assertEqual(first.dimensions, [.1])
        self.assertEqual(second.dimensions, [.1])

    def test_endpoint_and_last_segment_deletion(self):
        sketch = Sketch([[0,0],[.1,0],[.1,.1]], False, [.1,None])
        self.assertEqual(sketch.without_segment(0)[0].points, [[.1,0],[.1,.1]])
        line = Sketch([[0,0],[.1,0]], False, [None])
        self.assertEqual(line.without_segment(0)[0].edges, [])

    def test_surviving_arc_keeps_curvature_and_radius_dimension(self):
        sketch = Sketch([[-.05,0]])
        sketch.add_arc([0,.05],[.05,0])
        sketch.set_dimension(0,.05)
        sketch.close()
        remaining, = sketch.without_segment(1)
        self.assertTrue(remaining.is_arc(0))
        self.assertAlmostEqual(remaining.dimension_value(0), .05)
        self.assertEqual(remaining.dimensions, [.05])


class FeatureDeletionTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        self.editor = FeaturePartEditor()
        self.addCleanup(self.dispose)

    def dispose(self):
        self.editor.dirty = False
        self.editor.close()

    def base(self):
        self.editor.new_sketch()
        self.editor.commit(rectangle())
        self.editor.extrude_active(.02)
        return self.editor.active_id

    def select(self, index, extrusion=False):
        item = self.editor.tree.topLevelItem(1).child(index)
        if extrusion:
            item = item.child(0)
        self.editor.tree.setCurrentItem(item)
        self.editor.tree_clicked(item)

    def dependent_boss(self):
        base = self.base()
        face = next(i for i, f in enumerate(self.editor.model.faces) if f["normal"][2] > .9)
        self.editor.select_face(face)
        self.editor.new_sketch()
        self.editor.commit(Sketch([[-.01,-.01],[.01,-.01],[.01,.01],[-.01,.01]], True, [None]*4))
        self.editor.extrude_active(.01)
        return base

    def test_backspace_removes_selected_line_and_undo_restores_closed_outline(self):
        self.editor.new_sketch()
        self.editor.commit(rectangle())
        self.editor.show()
        self.editor.select_line(2)
        self.editor.canvas.setFocus()
        self.app.processEvents()
        QTest.keyClick(self.editor.canvas, Qt.Key_Backspace)
        self.assertEqual(len(self.editor.sketch.edges), 3)
        self.assertFalse(self.editor.sketch.closed)
        self.editor.undo()
        self.assertTrue(self.editor.sketch.closed)
        self.assertEqual(len(self.editor.sketch.edges), 4)
        self.editor.redo()
        self.assertEqual(len(self.editor.sketch.edges), 3)

    def test_middle_line_becomes_two_draft_sketches_and_roundtrips(self):
        self.editor.new_sketch()
        self.editor.commit(Sketch([[0,0],[.1,0],[.1,.1],[.2,.1]], False, [None]*3))
        before = self.editor.model.geometry()
        self.editor.select_line(1)
        self.editor.delete_selected_segment()
        self.assertEqual(len(self.editor.model.features), 2)
        self.assertEqual([len(f["sketch"]["dimensions"]) for f in self.editor.model.features], [1,1])
        after = self.editor.model.geometry()
        self.editor.undo()
        self.assertEqual(self.editor.model.geometry(), before)
        self.editor.redo()
        self.assertEqual(self.editor.model.geometry(), after)
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "split.simuOPart"
            self.assertTrue(self.editor._save_to(path))
            self.assertTrue(self.editor.open_path(path))
            self.assertEqual(len(self.editor.model.features), 2)

    def test_backspace_in_line_table_deletes_selected_segment(self):
        self.editor.new_sketch()
        self.editor.commit(rectangle())
        self.editor.show()
        self.editor.lines.selectRow(1)
        self.editor.lines.setFocus()
        self.app.processEvents()
        QTest.keyClick(self.editor.lines, Qt.Key_Backspace)
        self.assertEqual(len(self.editor.sketch.edges), 3)

    def test_delete_extrusion_keeps_sketch_and_can_undo(self):
        self.base()
        before = self.editor.model.geometry()
        self.select(0, extrusion=True)
        with patch("simuo.ui.parts.feature_editor.QMessageBox.question", return_value=QMessageBox.Yes):
            self.editor.feature_actions["Delete Extrusion…"].trigger()
        self.assertEqual(len(self.editor.model.features), 1)
        self.assertIsNone(self.editor.model.features[0]["depth"])
        self.assertFalse(self.editor.model.has_solid)
        self.assertTrue(self.editor.sketch.closed)
        self.editor.undo()
        self.assertEqual(self.editor.model.geometry(), before)

    def test_delete_sketch_cascades_dependents_only_after_confirmation(self):
        self.dependent_boss()
        before = self.editor.model.geometry()
        self.select(0)
        self.editor.dirty = False
        with patch("simuo.ui.parts.feature_editor.QMessageBox.question", return_value=QMessageBox.Cancel) as question:
            self.editor.delete_sketch()
            self.assertIn("depend", question.call_args.args[2])
        self.assertEqual(self.editor.model.geometry(), before)
        self.assertFalse(self.editor.dirty)
        with patch("simuo.ui.parts.feature_editor.QMessageBox.question", return_value=QMessageBox.Yes):
            self.editor.delete_sketch()
        self.assertEqual(self.editor.model.features, [])
        self.assertTrue(self.editor.dirty)
        self.editor.undo()
        self.assertEqual(self.editor.model.geometry(), before)

    def test_deleting_line_from_extrusion_is_cancelable_then_removes_dependents(self):
        self.dependent_boss()
        self.select(0)
        self.editor.edit_sketch()
        self.editor.select_line(0)
        before = self.editor.model.geometry()
        with patch("simuo.ui.parts.feature_editor.QMessageBox.question", return_value=QMessageBox.Cancel):
            self.editor.delete_selected_segment()
        self.assertEqual(self.editor.model.geometry(), before)
        with patch("simuo.ui.parts.feature_editor.QMessageBox.question", return_value=QMessageBox.Yes):
            self.editor.delete_selected_segment()
        self.assertEqual(len(self.editor.model.features), 1)
        self.assertIsNone(self.editor.active_feature["depth"])
        self.assertEqual(len(self.editor.sketch.edges), 3)

    def test_delete_extrusion_keeps_its_sketch_and_unrelated_plane_draft(self):
        root = self.dependent_boss()
        self.editor.selected_support = {"type":"plane", "name":"Right"}
        self.editor.new_sketch()
        unrelated = self.editor.active_id
        self.select(0, extrusion=True)
        with patch("simuo.ui.parts.feature_editor.QMessageBox.question", return_value=QMessageBox.Yes):
            self.editor.delete_extrusion()
        self.assertEqual([f["id"] for f in self.editor.model.features], [root, unrelated])
        self.assertTrue(self.editor.model.features[0]["sketch"]["closed"])
        self.assertIsNone(self.editor.model.features[0]["depth"])

    def test_backspace_in_tree_deletes_only_extrusion_node(self):
        self.base()
        self.editor.show()
        self.select(0, extrusion=True)
        self.editor.tree.setFocus()
        self.app.processEvents()
        with patch("simuo.ui.parts.feature_editor.QMessageBox.question", return_value=QMessageBox.Yes):
            QTest.keyClick(self.editor.tree, Qt.Key_Backspace)
        self.assertEqual(len(self.editor.model.features), 1)
        self.assertIsNone(self.editor.model.features[0]["depth"])

    def test_backspace_in_name_field_edits_text_without_deleting_geometry(self):
        self.base()
        before = self.editor.model.geometry()
        self.editor.show()
        self.editor.name.setText("Part AB")
        self.editor.name.setFocus()
        self.editor.name.setCursorPosition(len("Part AB"))
        self.app.processEvents()
        QTest.keyClick(self.editor.name, Qt.Key_Backspace)
        self.assertEqual(self.editor.name.text(), "Part A")
        self.assertEqual(self.editor.model.geometry(), before)


if __name__ == "__main__":
    unittest.main()
