"""Editable circular arc geometry, radius dimensions, files and editor controls."""
import copy
import json
import math
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import numpy as np
from simuo.parts.sketch_geometry import Sketch,prism_vertices
from simuo.parts.part_document import new_document,save_document,open_document
from simuo.parts.part_assets import load_asset
from simuo.parts.part_export import export_sketch
from simuo.project.scene import Scene,SceneObject
from simuo.physics.physics_world import PhysicsWorld


def semicircle(radius=.05):
    sketch=Sketch()
    sketch.add_point([-radius,0])
    sketch.add_arc([0,radius],[radius,0])
    return sketch


class ArcTests(unittest.TestCase):
    def test_three_points_create_exact_editable_radius_not_arc_length(self):
        sketch=semicircle()
        center,radius,sweep=sketch.arc_parameters(0)
        np.testing.assert_allclose(center,[0,0],atol=1e-12)
        self.assertAlmostEqual(radius,.05)
        self.assertAlmostEqual(abs(sweep),math.pi)
        self.assertAlmostEqual(sketch.length(0),math.pi*.05)
        self.assertAlmostEqual(sketch.dimension_value(0),.05)
        self.assertEqual(sketch.dimensions,[None])
        self.assertEqual(len(sketch.points),2)

    def test_clockwise_counterclockwise_and_major_arcs_include_through_point(self):
        for through,expected in [([0,.05],-math.pi),([0,-.05],math.pi),([.1,0],1.5*math.pi)]:
            with self.subTest(through=through):
                sketch=Sketch([[-.05,0]])
                end=[0,-.05] if through==[.1,0] else [.05,0]
                sketch.add_arc(through,end)
                center,radius,sweep=sketch.arc_parameters(0)
                # The major-arc case's three chosen points define another circle;
                # independently verify passage and that the longer sweep is used.
                self.assertAlmostEqual(math.dist(center,through),radius)
                if through==[.1,0]:
                    self.assertGreater(abs(sweep),math.pi)
                else:
                    self.assertAlmostEqual(sweep,expected)
                for point in sketch.segment_points(0):
                    self.assertAlmostEqual(math.dist(center,point),radius)

    def test_radius_dimension_preserves_endpoints_and_rejects_impossible_radius(self):
        sketch=semicircle()
        before=copy.deepcopy(sketch.points)
        sketch.set_dimension(0,.075)
        self.assertEqual(sketch.points,before)
        self.assertAlmostEqual(sketch.dimension_value(0),.075)
        snapshot=sketch.geometry()
        with self.assertRaisesRegex(ValueError,'Radius must be at least'):
            sketch.set_dimension(0,.04)
        self.assertEqual(sketch.geometry(),snapshot)

    def test_invalid_arc_points_do_not_change_sketch(self):
        sketch=Sketch([[0,0]])
        snapshot=sketch.geometry()
        for through,end in [([.05,0],[.1,0]),([0,0],[.1,0]),([0,.1],[0,0])]:
            with self.subTest(through=through),self.assertRaises(ValueError):
                sketch.add_arc(through,end)
            self.assertEqual(sketch.geometry(),snapshot)

    def test_closed_arc_line_outline_has_expected_area_and_outward_closed_mesh(self):
        sketch=semicircle()
        sketch.close()
        self.assertAlmostEqual(abs(sketch.signed_area),math.pi*.05**2/2,delta=6e-6)
        mesh=prism_vertices(sketch).reshape(-1,3,6)
        volume=sum(np.dot(t[0,:3],np.cross(t[1,:3],t[2,:3]))/6 for t in mesh)
        self.assertAlmostEqual(volume,abs(sketch.signed_area)*sketch.thickness,places=9)
        np.testing.assert_allclose(np.linalg.norm(mesh[:,:,3:],axis=2),1,atol=1e-6)
        edges={}
        for triangle in mesh:
            pts=[tuple(v[:3]) for v in triangle]
            for a,b in zip(pts,pts[1:]+pts[:1]):
                edge=tuple(sorted((a,b)))
                edges[edge]=edges.get(edge,0)+1
        self.assertTrue(all(count==2 for count in edges.values()))

    def test_two_arcs_close_to_full_circle(self):
        sketch=semicircle()
        sketch.add_arc([0,-.05],sketch.points[0],close=True)
        self.assertTrue(sketch.closed)
        self.assertEqual(len(sketch.edges),2)
        self.assertAlmostEqual(abs(sketch.signed_area),math.pi*.05**2,delta=1.1e-5)
        self.assertTrue(np.isfinite(prism_vertices(sketch)).all())

    def test_small_radius_mesh_keeps_curved_cap_and_volume(self):
        sketch=semicircle(radius=2e-5)
        sketch.close()
        self.assertEqual(len(sketch.triangles()),len(sketch.outline_points)-2)
        mesh=prism_vertices(sketch).reshape(-1,3,6)
        volume=sum(np.dot(t[0,:3],np.cross(t[1,:3],t[2,:3]))/6 for t in mesh)
        self.assertAlmostEqual(volume/(abs(sketch.signed_area)*sketch.thickness),1,places=5)

    def test_crossing_a_curve_is_rejected_transactionally(self):
        sketch=semicircle()
        previous=sketch.geometry()
        with self.assertRaisesRegex(ValueError,'cross or overlap'):
            sketch.add_point([-.05,.025])
        self.assertEqual(sketch.geometry(),previous)

    def test_major_arc_radius_edit_keeps_its_branch(self):
        sketch=Sketch([[-.05,0]])
        sketch.add_arc([.1,0],[0,-.05])
        _,radius,sweep=sketch.arc_parameters(0)
        sketch.set_dimension(0,radius*1.2)
        self.assertAlmostEqual(sketch.dimension_value(0),radius*1.2)
        self.assertGreater(abs(sketch.arc_parameters(0)[2]),math.pi)
        self.assertEqual(math.copysign(1,sketch.arc_parameters(0)[2]),math.copysign(1,sweep))

    def test_legacy_line_only_geometry_is_unchanged(self):
        original={'type':'sketch','points':[[0,0],[.1,0],[.1,.1]],'closed':False,'dimensions':[None,None],'thickness':.01}
        loaded=Sketch.from_geometry(original)
        self.assertEqual(loaded.geometry(),original)
        self.assertFalse(loaded.is_arc(0))

    def test_line_dimension_keeps_existing_arc_radius(self):
        sketch=semicircle()
        sketch.set_dimension(0,.075)
        sketch.add_point([.05,-.05])
        sketch.set_dimension(1,.07)
        self.assertAlmostEqual(sketch.dimension_value(0),.075)
        self.assertAlmostEqual(sketch.length(1),.07)
        sketch.validate()

    def test_malformed_arc_metadata_is_rejected(self):
        geometry=semicircle().geometry()
        for arcs in [None,[None,None],[{'bulge':0}],[{'bulge':True}],[{'bulge':float('nan')}],[{'radius':1}]]:
            with self.subTest(arcs=arcs),self.assertRaises(ValueError):
                Sketch.from_geometry(dict(geometry,arcs=arcs))

    def test_save_reload_export_and_physics_preserve_curved_shape(self):
        sketch=semicircle()
        sketch.set_dimension(0,.06)
        sketch.close()
        with tempfile.TemporaryDirectory(prefix='simuo arc qa ') as folder:
            folder=Path(folder)
            path=folder/'curved part.simuOPart'
            save_document(path,new_document(),sketch)
            _,loaded=open_document(path)
            self.assertEqual(loaded.geometry(),sketch.geometry())
            asset=load_asset(path)
            self.assertGreater(asset.vertices.size//6,36)
            self.assertAlmostEqual(asset.part.volume,abs(sketch.signed_area)*sketch.thickness)
            self.assertGreater(asset.part.size[1],0)
            for kind in ('obj','stl'):
                output=folder/f'arc.{kind}'
                export_sketch(output,loaded,kind)
                self.assertGreater(output.stat().st_size,100)
            scene=Scene()
            scene.addObject(SceneObject(meshPath=path))
            world=PhysicsWorld(scene)
            try:
                world.step(10)
                self.assertGreater(world.masses[0],0)
                self.assertTrue(np.isfinite(world.scene.objects[0].position).all())
            finally:
                world.close()

    def test_feature_extrusion_uses_curved_contour(self):
        from simuo.parts.feature_geometry import FeatureModel
        sketch=semicircle()
        sketch.close()
        model=FeatureModel()
        feature=model.new_sketch({'type':'plane','name':'Front'})
        feature['sketch']=sketch.geometry()
        feature['depth']=.01
        model.build()
        self.assertTrue(model.has_solid)
        self.assertAlmostEqual(model.volume,abs(sketch.signed_area)*.01,places=9)
        self.assertGreater(model.vertices.size//6,36)


class ArcEditorTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        from PySide6.QtWidgets import QApplication
        cls.app=QApplication.instance() or QApplication([])

    def setUp(self):
        from simuo.ui.parts.part_editor import PartEditor
        self.editor=PartEditor()
        self.addCleanup(self.dispose)

    def dispose(self):
        self.editor.dirty=False
        self.editor.close()

    def test_mouse_arc_radius_controls_undo_redo_and_manual_label(self):
        from PySide6.QtCore import Qt
        from PySide6.QtTest import QTest
        self.editor.canvas.resize(700,600)
        self.editor.canvas.fit()
        self.editor.arc_action.trigger()
        for point in [[-.05,0],[0,.05],[.05,0]]:
            QTest.mouseClick(self.editor.canvas,Qt.LeftButton,pos=self.editor.canvas.screen(point).toPoint())
        sketch=self.editor.sketch
        self.assertTrue(sketch.is_arc(0))
        self.assertAlmostEqual(sketch.dimension_value(0),.05,places=3)
        self.assertEqual(sketch.dimensions,[None])
        self.editor.select_line(0)
        self.assertIn('radius',self.editor.dimension_label.text())
        self.assertAlmostEqual(self.editor.length.value(),50,delta=1)
        self.editor.length.setValue(75)
        self.editor.dimension_button.click()
        self.assertAlmostEqual(self.editor.sketch.dimension_value(0),.075)
        self.assertTrue(self.editor.lines.item(0,1).text().startswith('R '))
        self.editor.undo()
        self.assertIsNone(self.editor.sketch.dimensions[0])
        self.editor.redo()
        self.assertAlmostEqual(self.editor.sketch.dimension_value(0),.075)
        self.editor.clear_dimension()
        self.assertIsNone(self.editor.sketch.dimensions[0])
        self.assertAlmostEqual(self.editor.sketch.dimension_value(0),.075)

    def test_esc_cancels_pending_arc_without_adding_segment(self):
        from PySide6.QtCore import Qt
        from PySide6.QtTest import QTest
        self.editor.arc_action.trigger()
        for point in [[0,0],[.05,.05]]:
            QTest.mouseClick(self.editor.canvas,Qt.LeftButton,pos=self.editor.canvas.screen(point).toPoint())
        self.assertIsNotNone(self.editor.canvas.arc_through)
        QTest.keyClick(self.editor.canvas,Qt.Key_Escape)
        self.assertIsNone(self.editor.canvas.arc_through)
        self.assertFalse(self.editor.canvas.drawing)
        self.assertFalse(self.editor.arc_action.isChecked())
        self.assertEqual(len(self.editor.sketch.edges),0)

    def test_zoomed_arc_hit_uses_the_curve_rather_than_mesh_chords(self):
        self.editor.commit(semicircle())
        self.editor.canvas.zoom=1e7
        angle=math.radians(17.5)
        point=[.05*math.cos(angle),.05*math.sin(angle)]
        self.assertEqual(self.editor.canvas.hit(self.editor.canvas.screen(point)),0)

    def test_feature_editor_arc_tool_radius_extrusion_and_file_roundtrip(self):
        from simuo.ui.parts.feature_editor import FeaturePartEditor
        from PySide6.QtCore import Qt
        from PySide6.QtTest import QTest
        editor=FeaturePartEditor()
        try:
            editor.canvas.resize(700,600)
            editor.arc_action.trigger()
            editor.canvas.fit()
            self.assertIsNotNone(editor.active_feature)
            self.assertTrue(editor.canvas.arc_mode)
            for point in [[-.05,0],[0,.05],[.05,0]]:
                QTest.mouseClick(editor.canvas,Qt.LeftButton,pos=editor.canvas.screen(point).toPoint())
            editor.select_line(0)
            editor.length.setValue(75)
            editor.apply_dimension()
            editor.close_face()
            editor.extrude_active(.01)
            self.assertTrue(editor.model.has_solid)
            self.assertAlmostEqual(editor.sketch.dimension_value(0),.075)
            with tempfile.TemporaryDirectory() as folder:
                path=Path(folder)/'arc feature.simuOPart'
                self.assertTrue(editor._save_to(path))
                self.assertTrue(editor.open_path(path))
                self.assertTrue(load_asset(path).part.features.has_solid)
                saved=Sketch.from_geometry(editor.model.features[0]['sketch'])
                self.assertAlmostEqual(saved.dimension_value(0),.075)
        finally:
            editor.dirty=False
            editor.close()

    def test_arc_curve_and_radius_label_are_selectable(self):
        self.editor.commit(semicircle())
        self.editor.select_mode()
        sketch=self.editor.sketch
        midpoint=sketch.segment_points(0)[18]
        self.assertEqual(self.editor.canvas.hit(self.editor.canvas.screen(midpoint)),0)
        self.editor.select_line(0)
        self.editor.length.setValue(60)
        self.editor.apply_dimension()
        self.editor.canvas.grab()
        self.assertEqual(len(self.editor.canvas.labels),1)
        index,label=self.editor.canvas.labels[0]
        self.assertEqual(index,0)
        self.assertEqual(self.editor.canvas.hit(label),0)


if __name__=='__main__':
    unittest.main()
