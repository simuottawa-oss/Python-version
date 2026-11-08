"""Earlier extrusions remain visible and framed during sketch editing."""
import unittest

import numpy as np

from PySide6.QtCore import QPointF, Qt
from PySide6.QtGui import QColor, QImage, QPainter
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication
from simuo.ui.parts.feature_editor import FeaturePartEditor
from simuo.parts.sketch_geometry import Sketch


class SketchContextTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        self.editor = FeaturePartEditor()
        self.addCleanup(self.dispose)
        self.editor.new_sketch()
        self.editor.commit(Sketch([[0, 0], [.1, 0], [.1, .08], [0, .08]], True, [None]*4))
        self.editor.extrude_active(.03)

    def dispose(self):
        self.editor.dirty = False
        self.editor.close()

    def test_reference_plane_sketches_show_projected_solid_and_frame_it(self):
        for name, size in (("Front", [.1, .08]), ("Right", [.03, .08]), ("Top", [.1, .03])):
            with self.subTest(plane=name):
                self.editor.selected_support = {"type": "plane", "name": name}
                self.editor.new_sketch()
                points = np.asarray(self.editor.sketch_context_points())
                np.testing.assert_allclose(np.ptp(points, axis=0), size, atol=1e-8)
                self.editor.canvas.resize(800, 600)
                self.editor.canvas.fit()
                for point in points:
                    self.assertTrue(self.editor.canvas.rect().contains(self.editor.canvas.screen(point).toPoint()))

    def test_face_sketch_context_is_shaded_behind_drawing(self):
        index = next(i for i, face in enumerate(self.editor.model.faces) if face["normal"][2] > .9)
        self.editor.select_face(index)
        self.editor.new_sketch()
        self.editor.canvas.resize(800, 600)
        self.editor.canvas.fit()
        image = QImage(800, 600, QImage.Format_ARGB32)
        image.fill(QColor("#2e2e33"))
        painter = QPainter(image)
        self.editor.paint_sketch_context(painter, self.editor.canvas)
        painter.end()
        center = self.editor.canvas.screen([0, 0]).toPoint()
        self.assertEqual(image.pixelColor(center), QColor("#454c54"))

    def test_editing_first_sketch_excludes_own_extrusion_and_later_solid(self):
        self.editor.new_sketch()
        self.assertTrue(self.editor.sketch_context_points())
        first = self.editor.tree.topLevelItem(1).child(0)
        self.editor.tree_clicked(first)
        self.editor.edit_sketch()
        self.assertEqual(self.editor.sketch_context_points(), [])

    def test_context_is_rebuilt_after_undo_and_redo(self):
        self.editor.new_sketch()
        before = np.asarray(self.editor.sketch_context_points())
        self.editor.undo()
        self.assertEqual(self.editor.sketch_context_points(), [])
        self.editor.redo()
        np.testing.assert_allclose(self.editor.sketch_context_points(), before)

    def test_context_uses_solid_before_active_extrusion(self):
        self.editor.new_sketch()
        second_id = self.editor.active_id
        self.editor.commit(Sketch([[.1, 0], [.15, 0], [.15, .08], [.1, .08]], True, [None]*4))
        self.editor.extrude_active(.03)
        self.editor.new_sketch()
        np.testing.assert_allclose(np.ptp(self.editor.sketch_context_points(), axis=0), [.15, .08], atol=1e-8)
        self.editor.active_id = second_id
        self.editor.edit_sketch()
        np.testing.assert_allclose(np.ptp(self.editor.sketch_context_points(), axis=0), [.1, .08], atol=1e-8)

    def face_sketch(self):
        index = next(i for i, face in enumerate(self.editor.model.faces) if face["normal"][2] > .9)
        self.editor.select_face(index)
        self.editor.new_sketch()
        self.editor.canvas.resize(800, 600)
        self.editor.canvas.fit()

    def test_clicks_near_face_corners_create_exact_triangle(self):
        self.face_sketch()
        canvas = self.editor.canvas
        corners = []
        for edge in self.editor.sketch_context_geometry()[1]:
            for point in edge:
                if not any(np.allclose(point, other) for other in corners):
                    corners.append(point.tolist())
        self.assertEqual(len(corners), 4)
        for point in corners[:3] + corners[:1]:
            position = canvas.screen(point) + QPointF(6, 4)
            QTest.mouseClick(canvas, Qt.LeftButton, pos=position.toPoint())
        self.assertTrue(self.editor.sketch.closed)
        np.testing.assert_allclose(self.editor.sketch.points, corners[:3], atol=1e-12)

    def test_face_edge_snap_slides_and_corners_take_priority(self):
        self.face_sketch()
        canvas = self.editor.canvas
        a, b = self.editor.sketch_context_geometry()[1][0]
        direction = b-a
        normal = np.array([-direction[1], direction[0]]) / np.linalg.norm(direction)
        for t in (.3, .6):
            point = a+t*direction
            snapped = canvas.world(canvas.screen(point + normal*5/canvas.zoom))
            np.testing.assert_allclose(snapped, point, atol=1e-12)
            self.assertEqual(canvas.snap_target[1], "Face edge")
        snapped = canvas.world(canvas.screen(a)+QPointF(6, 4))
        np.testing.assert_allclose(snapped, a, atol=1e-12)
        self.assertEqual(canvas.snap_target[1], "Face corner")

    def test_snap_corner_lock_releases_when_switching_to_earlier_sketch(self):
        self.face_sketch()
        canvas = self.editor.canvas
        point = self.editor.sketch_context_geometry()[1][0][0]
        canvas.world(canvas.screen(point))
        self.editor.tree_clicked(self.editor.tree.topLevelItem(1).child(0))
        self.editor.edit_sketch()
        canvas.world(canvas.screen(point))
        self.assertTrue(canvas.snap_target is None or canvas.snap_target[1] != "Face corner")


if __name__ == "__main__":
    unittest.main()
