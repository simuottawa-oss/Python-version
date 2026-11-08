"""Free endpoint dragging with explicit constraints, cancel and single-step undo."""
import copy
import math
from pathlib import Path
import tempfile
import unittest

from PySide6.QtCore import Qt
from PySide6.QtGui import QMouseEvent
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication
from simuo.parts.sketch_geometry import Sketch
from simuo.ui.parts.feature_editor import FeaturePartEditor


class PointGeometryTests(unittest.TestCase):
    def test_free_endpoint_moves_without_grid_or_inferred_axis_constraints(self):
        sketch = Sketch([[0,0],[.1,0],[.1,.1]], False, [None,None])
        sketch.move_point(1, [.123456,.023456])
        self.assertEqual(sketch.points, [[0,0],[.123456,.023456],[.1,.1]])

    def test_origin_point_is_free_when_not_explicitly_constrained(self):
        sketch = Sketch([[0,0],[.1,0]], False, [None])
        sketch.move_point(0, [-.02,.03])
        self.assertEqual(sketch.points, [[-.02,.03],[.1,0]])

    def test_horizontal_and_vertical_constraints_limit_drag_direction(self):
        for kind, target, expected in (("horizontal", [.14,.05], [.14,0]), ("vertical", [.06,.14], [0,.14])):
            sketch = Sketch([[0,0],[.1,0]], False, [None])
            sketch.add_constraint(kind, [0])
            sketch.move_point(1, target)
            self.assertAlmostEqual(sketch.points[1][0], expected[0])
            self.assertAlmostEqual(sketch.points[1][1], expected[1])
            self.assertEqual(sketch.points[0], [0,0])

    def test_length_constraint_allows_rotation_and_preserves_other_endpoint(self):
        sketch = Sketch([[0,0],[.1,0]], False, [.1])
        sketch.move_point(1, [.1,.1])
        self.assertAlmostEqual(sketch.length(0), .1)
        self.assertAlmostEqual(sketch.points[1][0], math.sqrt(.005))
        self.assertAlmostEqual(sketch.points[1][1], math.sqrt(.005))
        self.assertEqual(sketch.points[0], [0,0])

    def test_length_and_horizontal_fully_constrain_the_endpoint(self):
        sketch = Sketch([[0,0],[.1,0]], False, [.1])
        sketch.add_constraint("horizontal", [0])
        sketch.move_point(1, [.15,.02])
        self.assertAlmostEqual(sketch.points[1][0], .1)
        self.assertAlmostEqual(sketch.points[1][1], 0)

    def test_equal_relation_preserved_while_dragging(self):
        sketch = Sketch([[0,0],[.1,0],[.1,.1]], False, [None,None])
        sketch.add_constraint("equal", [0,1])
        sketch.move_point(2, [.2,.2])
        self.assertAlmostEqual(sketch.length(0), sketch.length(1))
        self.assertEqual(sketch.points[:2], [[0,0],[.1,0]])

    def test_arc_radius_preserved_and_impossible_position_is_transactional(self):
        sketch = Sketch([[-.05,0]])
        sketch.add_arc([0,.05],[.05,0])
        sketch.set_dimension(0,.075)
        sketch.move_point(1, [.04,.02])
        self.assertAlmostEqual(sketch.dimension_value(0), .075)
        before = sketch.geometry()
        with self.assertRaises(ValueError):
            sketch.move_point(1, [.5,0])
        self.assertEqual(sketch.geometry(), before)

    def test_crossing_closed_outline_does_not_change_original(self):
        sketch = Sketch([[0,0],[.1,0],[.1,.1],[0,.1]], True, [None]*4)
        before = sketch.geometry()
        with self.assertRaises(ValueError):
            sketch.move_point(1, [-.05,.05])
        self.assertEqual(sketch.geometry(), before)

    def test_single_unconnected_point_can_move(self):
        sketch = Sketch([[0,0]])
        sketch.move_point(0, [.02,.03])
        self.assertEqual(sketch.points, [[.02,.03]])


class PointDragEditorTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        self.editor = FeaturePartEditor()
        self.editor.new_sketch()
        self.editor.commit(Sketch([[0,0],[.1,0],[.1,.1]], False, [None,None]))
        self.editor.select_mode()
        self.editor.canvas.fit()
        self.editor.show()
        self.app.processEvents()
        self.addCleanup(self.close)

    def close(self):
        self.editor.dirty = False
        self.editor.close()

    def move(self, point):
        position = self.editor.canvas.screen(point)
        event = QMouseEvent(QMouseEvent.MouseMove, position, position, Qt.NoButton, Qt.LeftButton, Qt.NoModifier)
        self.app.sendEvent(self.editor.canvas, event)

    def press(self, index):
        QTest.mousePress(self.editor.canvas, Qt.LeftButton, pos=self.editor.canvas.screen(self.editor.sketch.points[index]).toPoint())

    def test_preview_single_undo_and_saved_feature_coordinates(self):
        editor = self.editor
        before = editor.model.geometry()
        history = len(editor.history)
        self.press(1)
        self.move([.12,.02])
        self.move([.13,.03])
        self.assertEqual(editor.model.geometry(), before)
        self.assertEqual(len(editor.history), history)
        QTest.mouseRelease(editor.canvas, Qt.LeftButton)
        self.assertEqual(len(editor.history), history+1)
        self.assertAlmostEqual(editor.sketch.points[1][0], .13)
        self.assertAlmostEqual(editor.sketch.points[1][1], .03)
        after = editor.model.geometry()
        editor.undo()
        self.assertEqual(editor.model.geometry(), before)
        editor.redo()
        self.assertEqual(editor.model.geometry(), after)
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder)/"moved.simuOPart"
            self.assertTrue(editor._save_to(path))
            self.assertTrue(editor.open_path(path))
            self.assertEqual(editor.model.geometry(), after)

    def test_escape_cancels_preview_without_dirtying_saved_state(self):
        before = self.editor.model.geometry()
        original = copy.deepcopy(self.editor.sketch.geometry())
        self.editor.dirty = False
        self.press(1)
        self.move([.12,.02])
        QTest.keyClick(self.editor.canvas, Qt.Key_Escape)
        QTest.mouseRelease(self.editor.canvas, Qt.LeftButton)
        self.assertEqual(self.editor.sketch.geometry(), original)
        self.assertEqual(self.editor.model.geometry(), before)
        self.assertFalse(self.editor.dirty)

    def test_click_without_drag_does_not_add_an_undo_step(self):
        history = len(self.editor.history)
        self.editor.dirty = False
        self.press(1)
        QTest.mouseRelease(self.editor.canvas, Qt.LeftButton)
        self.assertEqual(len(self.editor.history), history)
        self.assertFalse(self.editor.dirty)


if __name__ == "__main__":
    unittest.main()
