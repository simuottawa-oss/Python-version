"""Regression coverage for sketch-line and projected-solid snapping."""
from pathlib import Path
import tempfile
import unittest

import numpy as np


from PySide6.QtCore import QPointF, Qt
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication
from simuo.ui.parts.feature_editor import FeaturePartEditor
from simuo.ui.parts.part_editor import PartEditor
from simuo.parts.sketch_geometry import Sketch


class EdgeSnappingTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        self.editor = PartEditor()
        self.addCleanup(self.dispose)
        self.canvas = self.editor.canvas
        self.canvas.resize(800, 600)
        self.canvas.origin = QPointF(400, 300)
        self.canvas.zoom = 3000

    def dispose(self):
        self.editor.dirty = False
        self.editor.close()

    def test_diagonal_line_projection_precedes_grid_rounding_at_each_zoom(self):
        a, b = [.10173, .10219], [.40173, .50219]
        target = [.25173, .30219]
        for zoom in (500, 3000, 100000):
            with self.subTest(zoom=zoom):
                self.editor.sketch = Sketch([a, b], False, [None])
                self.canvas.zoom = zoom
                # (4, -3) is perpendicular to the line in world coordinates.
                actual = self.canvas.world(self.canvas.screen(target) + QPointF(4, 3))
                np.testing.assert_allclose(actual, target, atol=1e-12, rtol=0)
                self.assertEqual(self.canvas.snap_target[1], "Sketch line")

    def test_projection_slides_instead_of_locking_to_previous_edge_point(self):
        self.editor.sketch = Sketch([[.02, .03173], [.18, .03173]], False, [None])
        for x in (.06119, .07123, .09137):
            actual = self.canvas.world(self.canvas.screen([x, .03173]) + QPointF(0, 7))
            np.testing.assert_allclose(actual, [x, .03173], atol=1e-12, rtol=0)
            self.assertEqual(self.canvas.snap_target[1], "Sketch line")

    def test_edge_capture_radius_is_in_pixels_and_releases_to_grid(self):
        for zoom in (500, 3000, 100000):
            with self.subTest(zoom=zoom):
                self.editor.sketch = Sketch([[.1, .13173], [.5, .13173]], False, [None])
                self.canvas.zoom = zoom
                pixel = self.canvas.screen([.3, .13173])
                snapped = self.canvas.world(pixel + QPointF(0, 9))
                self.assertAlmostEqual(snapped[1], .13173)
                released = self.canvas.world(pixel + QPointF(0, 12))
                self.assertIsNone(self.canvas.snap_target)
                self.assertNotAlmostEqual(released[1], .13173)
                for coordinate in released:
                    self.assertAlmostEqual(coordinate / .001, round(coordinate / .001))

    def test_nearest_of_two_edges_wins(self):
        self.editor.sketch = Sketch([[.02, .03], [.18, .03], [.18, .035], [.02, .035]],
                                   False, [None]*3)
        actual = self.canvas.world(self.canvas.screen([.09, .0339]))
        np.testing.assert_allclose(actual, [.09, .035], atol=1e-12, rtol=0)

    def test_line_extension_is_not_a_snap_target(self):
        self.editor.sketch = Sketch([[.02, .03173], [.08, .03173]], False, [None])
        actual = self.canvas.world(self.canvas.screen([.12119, .03173]))
        self.assertIsNone(self.canvas.snap_target)
        self.assertAlmostEqual(actual[0], .121)

    def test_arc_chord_is_not_treated_as_a_straight_line(self):
        sketch = Sketch([[.02, .03]])
        sketch.add_arc([.07, .08], [.12, .03])
        self.editor.sketch = sketch
        self.canvas.arc_mode = True
        self.canvas.world(self.canvas.screen([.07, .03119]))
        self.assertIsNone(self.canvas.snap_target)


class ProjectedEdgeSnappingTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        self.editor = FeaturePartEditor()
        self.addCleanup(self.dispose)
        self.editor.new_sketch()
        self.editor.commit(Sketch([[.02173, .03219], [.12173, .03219],
                                   [.12173, .11219], [.02173, .11219]], True, [None]*4))
        self.editor.extrude_active(.04317)
        self.canvas = self.editor.canvas
        self.canvas.resize(800, 600)

    def dispose(self):
        self.editor.dirty = False
        self.editor.close()

    def new_sketch_on(self, plane):
        self.editor.select_plane(plane)
        self.editor.new_sketch()
        self.canvas.origin = QPointF(400, 300)
        self.canvas.zoom = 3000

    def projected_edge(self, start, end):
        """Check the expected boundary, then use the kernel's actual coordinates."""
        edges = self.editor.sketch_context_geometry()[1]
        edge = min(edges, key=lambda edge: min(
            np.linalg.norm(edge[0] - start) + np.linalg.norm(edge[1] - end),
            np.linalg.norm(edge[1] - start) + np.linalg.norm(edge[0] - end)))
        if np.linalg.norm(edge[1] - start) < np.linalg.norm(edge[0] - start):
            edge = edge[::-1]
        # The solid kernel may round inputs to float32; snapping must still
        # preserve its projected coordinates without additional grid rounding.
        np.testing.assert_allclose(edge, [start, end], atol=1e-8, rtol=0)
        return edge

    def test_corners_and_edge_interiors_snap_on_all_reference_planes(self):
        expected_edges = {
            "Front": ([.02173, .03219], [.12173, .03219]),
            "Right": ([-.04317, .03219], [0, .03219]),
            "Top": ([.02173, -.04317], [.12173, -.04317]),
        }
        for plane, (corner, end) in expected_edges.items():
            with self.subTest(plane=plane):
                self.new_sketch_on(plane)
                corner, end = self.projected_edge(corner, end)
                actual = self.canvas.world(self.canvas.screen(corner) + QPointF(-5, 4))
                np.testing.assert_allclose(actual, corner, atol=1e-12, rtol=0)
                self.assertEqual(self.canvas.snap_target[1], "Face corner")
                midpoint = (np.array(corner) + end) / 2
                actual = self.canvas.world(self.canvas.screen(midpoint) + QPointF(0, 6))
                np.testing.assert_allclose(actual, midpoint, atol=1e-12, rtol=0)
                self.assertEqual(self.canvas.snap_target[1], "Face edge")

    def test_triangulation_diagonal_is_not_exposed_as_a_face_edge(self):
        self.new_sketch_on("Front")
        self.canvas.world(self.canvas.screen([.07173, .07219]))
        self.assertIsNone(self.canvas.snap_target)

    def test_corner_capture_radius_is_independent_of_zoom(self):
        self.new_sketch_on("Front")
        _, corner = self.projected_edge([.02173, .11219], [.12173, .11219])
        for zoom in (500, 3000, 100000):
            with self.subTest(zoom=zoom):
                self.canvas.center_origin()
                self.canvas.zoom = zoom
                actual = self.canvas.world(self.canvas.screen(corner) + QPointF(8, -6))
                np.testing.assert_allclose(actual, corner, atol=1e-12, rtol=0)
                self.assertEqual(self.canvas.snap_target[1], "Face corner")

    def test_clicked_edge_point_survives_undo_redo_and_feature_file_roundtrip(self):
        self.new_sketch_on("Front")
        a, b = self.projected_edge([.02173, .11219], [.12173, .11219])
        target = (a + b) / 2
        before = self.editor.model.geometry()
        history_length = len(self.editor.history)
        QTest.mouseClick(self.canvas, Qt.LeftButton,
                         pos=(self.canvas.screen(target) + QPointF(0, -6)).toPoint())
        self.assertEqual(len(self.editor.sketch.points), 1)
        # QTest clicks use integer pixels: only the along-edge coordinate is rounded.
        np.testing.assert_allclose(self.editor.sketch.points[0], target,
                                   atol=.5/self.canvas.zoom, rtol=0)
        self.assertAlmostEqual(self.editor.sketch.points[0][1], target[1], places=12)
        self.assertEqual(len(self.editor.history), history_length + 1)
        after = self.editor.model.geometry()
        self.editor.undo()
        self.assertEqual(self.editor.model.geometry(), before)
        self.editor.redo()
        self.assertEqual(self.editor.model.geometry(), after)
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "edge-point.simuOPart"
            self.assertTrue(self.editor._save_to(path))
            self.assertTrue(self.editor.open_path(path))
            self.assertEqual(self.editor.model.geometry(), after)


if __name__ == "__main__":
    unittest.main()
