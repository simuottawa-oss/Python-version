"""Exact endpoint/origin snapping and unfilled open arc drawing."""
import copy
from pathlib import Path
import tempfile
import unittest

from PySide6.QtCore import Qt,QPointF
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication
from simuo.ui.parts.part_editor import PartEditor
from simuo.parts.sketch_geometry import Sketch


class SketchSnapTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        self.editor = PartEditor()
        self.canvas = self.editor.canvas
        self.canvas.resize(600,500)
        self.canvas.origin = QPointF(300,250)
        self.canvas.zoom = 3000
        self.addCleanup(self.close)

    def close(self):
        self.editor.dirty = False
        self.editor.close()

    def test_existing_endpoint_snaps_exactly_before_grid_at_multiple_zooms(self):
        point = [.03173,.04219]
        for zoom in (500,3000,100000):
            with self.subTest(zoom=zoom):
                self.editor.sketch = Sketch([point,[.08,.09]],False,[None])
                self.canvas.zoom = zoom
                snapped = self.canvas.world(self.canvas.screen(point)+QPointF(7,4))
                self.assertEqual(snapped,point)
                self.assertEqual(self.canvas.snap_target[1],"Endpoint")

    def test_snap_holds_until_release_radius_and_ignores_deleted_points(self):
        point = [.03173,.04219]
        self.editor.sketch = Sketch([point,[.08,.09]],False,[None])
        self.assertEqual(self.canvas.world(self.canvas.screen(point)+QPointF(5,0)),point)
        self.assertEqual(self.canvas.world(self.canvas.screen(point)+QPointF(19,0)),point)
        self.assertNotEqual(self.canvas.world(self.canvas.screen(point)+QPointF(26,0)),point)
        self.canvas.world(self.canvas.screen(point))
        self.editor.sketch = Sketch([[.08,.09]])
        self.assertNotEqual(self.canvas.world(self.canvas.screen(point)+QPointF(5,0)),point)

    def test_origin_snaps_on_first_point_and_center_command_preserves_geometry(self):
        QTest.mouseClick(self.canvas,Qt.LeftButton,pos=(self.canvas.origin+QPointF(12,7)).toPoint())
        self.assertEqual(self.editor.sketch.points,[[0.,0.]])
        geometry = copy.deepcopy(self.editor.sketch.geometry())
        self.canvas.origin = QPointF(-100,-100)
        self.editor.origin_action.trigger()
        self.assertEqual(self.canvas.origin,QPointF(self.canvas.width()/2,self.canvas.height()/2))
        self.assertEqual(self.editor.sketch.geometry(),geometry)

    def test_nearby_endpoint_can_take_over_lock_when_under_cursor(self):
        first,second = [.03,.04],[.036,.04]
        self.editor.sketch = Sketch([first,second],False,[None])
        self.assertEqual(self.canvas.world(self.canvas.screen(first)),first)
        self.assertEqual(self.canvas.world(self.canvas.screen(second)),second)

    def test_close_outline_uses_exact_off_grid_endpoint(self):
        first = [.01173,.01219]
        self.editor.sketch = Sketch([first,[.08,.01219],[.08,.09]],False,[None,None])
        self.canvas.zoom = 2500
        QTest.mouseClick(self.canvas,Qt.LeftButton,pos=(self.canvas.screen(first)+QPointF(9,7)).toPoint())
        self.assertTrue(self.editor.sketch.closed)
        self.assertEqual(len(self.editor.sketch.points),3)
        self.assertEqual(self.editor.sketch.points[0],first)

    def test_arc_end_can_close_to_exact_endpoint(self):
        first = [-.05,0]
        sketch = Sketch([first])
        sketch.add_arc([0,.05],[.05,0])
        self.editor.sketch = sketch
        self.canvas.arc_mode = True
        self.canvas.arc_through = [0,-.05]
        QTest.mouseClick(self.canvas,Qt.LeftButton,pos=(self.canvas.screen(first)+QPointF(8,6)).toPoint())
        self.assertTrue(self.editor.sketch.closed)
        self.assertEqual(len(self.editor.sketch.points),2)
        self.assertEqual(len(self.editor.sketch.edges),2)

    def test_open_arc_preview_has_no_chord_fill(self):
        sketch = Sketch([[-.05,0]])
        sketch.add_arc([0,.05],[.05,0])
        self.editor.sketch = sketch
        self.canvas.arc_mode = True
        self.canvas.arc_through = [0,-.05]
        self.canvas.cursor = [-.05,0]
        self.canvas.drawing = True
        image = self.canvas.grab().toImage()
        # Inside the open lower semicircle, away from edges/grid/axes, must be
        # the background rather than the endpoint dot's solid white brush.
        for point in ([-.023,-.017],[.023,-.017]):
            pixel = self.canvas.screen(point).toPoint()
            color = image.pixelColor(pixel)
            self.assertLess(max(color.red(),color.green(),color.blue()),100)
        self.assertTrue(image.save(str(Path(tempfile.gettempdir()) / 'simuo-unfilled-arc-preview.png')))

    def test_closed_profile_keeps_intentional_face_shading(self):
        self.editor.sketch = Sketch([[-.06,-.06],[.06,-.06],[.06,.06],[-.06,.06]],True,[None]*4)
        color = self.canvas.grab().toImage().pixelColor(self.canvas.screen([.023,.017]).toPoint())
        self.assertGreater(color.blue(),color.red())

    def test_drawn_diagonal_line_snaps_without_grid_rounding(self):
        a, b = [.01173, .01219], [.08173, .06219]
        self.editor.sketch = Sketch([a, b], False, [None])
        for t in (.3, .6):
            point = [a[i]+t*(b[i]-a[i]) for i in range(2)]
            snapped = self.canvas.world(self.canvas.screen(point)+QPointF(2, 3))
            self.assertAlmostEqual((snapped[0]-a[0])*(b[1]-a[1]), (snapped[1]-a[1])*(b[0]-a[0]), places=12)
            self.assertEqual(self.canvas.snap_target[1], "Sketch line")


if __name__=="__main__":
    unittest.main()
