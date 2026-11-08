"""Circle drawing, cancellation, radius editing and solid persistence."""
import math
from pathlib import Path
import tempfile
import unittest


import numpy as np
from PySide6.QtCore import Qt
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication
from simuo.ui.parts.feature_editor import FeaturePartEditor
from simuo.parts.feature_document import open_feature_document
from simuo.ui.parts.part_editor import PartEditor
from simuo.parts.sketch_geometry import Sketch, prism_vertices


class CircleGeometryTests(unittest.TestCase):
    def test_circle_mesh_roundtrip_and_radius_edit_preserve_center(self):
        circle = Sketch.circle([.02, -.03], .05)
        self.assertTrue(circle.is_circle)
        self.assertEqual(Sketch.from_geometry(circle.geometry()).geometry(), circle.geometry())
        self.assertAlmostEqual(circle.signed_area, math.pi*.05**2, delta=1.1e-5)
        self.assertTrue(np.isfinite(prism_vertices(circle)).all())
        circle.set_dimension(0, .075)
        circle.set_dimension(1, .03)
        for index in (0, 1):
            center, radius, sweep = circle.arc_parameters(index)
            np.testing.assert_allclose(center, [.02, -.03], atol=1e-12)
            self.assertAlmostEqual(radius, .03)
            self.assertAlmostEqual(sweep, math.pi)
        circle.validate()

    def test_invalid_radii_are_rejected(self):
        for radius in (0, -1, float("nan"), float("inf"), 1e-8):
            with self.subTest(radius=radius), self.assertRaises(ValueError):
                Sketch.circle([0, 0], radius)


class CircleEditorTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def editor(self, kind=PartEditor):
        editor = kind()
        editor.canvas.resize(700, 600)
        editor.canvas.fit()
        def close():
            editor.dirty = False
            editor.close()
        self.addCleanup(close)
        return editor

    def click(self, editor, point):
        QTest.mouseClick(editor.canvas, Qt.LeftButton,
                         pos=editor.canvas.screen(point).toPoint())

    def draw(self, editor):
        editor.circle_action.trigger()
        self.click(editor, [0, 0])
        self.assertFalse(editor.sketch.points)
        self.click(editor, [.05, 0])
        self.assertTrue(editor.sketch.is_circle)

    def test_two_click_circle_preview_radius_undo_and_redo(self):
        editor = self.editor()
        editor.circle_action.trigger()
        self.click(editor, [0, 0])
        QTest.mouseMove(editor.canvas, editor.canvas.screen([.05, 0]).toPoint())
        self.assertFalse(editor.canvas.grab().isNull())
        self.assertFalse(editor.dirty)
        self.click(editor, [.05, 0])
        self.assertTrue(editor.sketch.is_circle)
        self.assertFalse(editor.canvas.drawing)
        editor.select_line(0)
        editor.length.setValue(75)
        editor.apply_dimension()
        self.assertAlmostEqual(editor.sketch.arc_parameters(1)[1], .075)
        editor.undo()
        self.assertAlmostEqual(editor.sketch.arc_parameters(0)[1], .05)
        editor.undo()
        self.assertFalse(editor.sketch.points)
        editor.redo()
        self.assertTrue(editor.sketch.is_circle)

    def test_cancel_and_switch_tools_discard_pending_center(self):
        editor = self.editor()
        for tool in (editor.line_action, editor.arc_action, None):
            editor.circle_action.trigger()
            self.click(editor, [0, 0])
            if tool:
                tool.trigger()
            else:
                QTest.keyClick(editor.canvas, Qt.Key_Escape)
            self.assertIsNone(editor.canvas.circle_center)
            self.assertFalse(editor.canvas.circle_mode)
            self.assertFalse(editor.sketch.points)
            self.assertFalse(editor.dirty)

    def test_zero_radius_can_be_retried_and_existing_outline_is_preserved(self):
        editor = self.editor()
        errors = []
        editor.canvas.error.disconnect()
        editor.canvas.error.connect(errors.append)
        editor.circle_action.trigger()
        self.click(editor, [0, 0])
        self.click(editor, [0, 0])
        self.assertTrue(errors)
        self.assertFalse(editor.sketch.points)
        self.click(editor, [.05, 0])
        geometry = editor.sketch.geometry()
        editor.circle_action.trigger()
        self.click(editor, [.1, .1])
        self.assertEqual(editor.sketch.geometry(), geometry)
        self.assertIn("empty sketch", errors[-1])

    def test_feature_circle_extrudes_saves_and_starts_a_separate_sketch(self):
        editor = self.editor(FeaturePartEditor)
        self.draw(editor)
        editor.select_line(0)
        editor.length.setValue(60)
        editor.apply_dimension()
        editor.extrude_active(.01)
        self.assertTrue(editor.model.has_solid)
        self.assertAlmostEqual(editor.model.volume, abs(editor.sketch.signed_area)*.01, places=9)
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "circle.simuOPart"
            self.assertTrue(editor._save_to(path))
            _, model = open_feature_document(path)
            self.assertTrue(Sketch.from_geometry(model.features[0]["sketch"]).is_circle)
            self.assertAlmostEqual(model.volume, editor.model.volume)
        editor.circle_action.trigger()
        self.assertTrue(editor.canvas.circle_mode)
        self.assertEqual(len(editor.model.features), 2)
        self.assertFalse(editor.sketch.points)
        self.assertTrue(editor.model.has_solid)


if __name__ == "__main__":
    unittest.main()
