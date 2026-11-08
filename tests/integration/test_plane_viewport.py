"""Reference-plane picking, face precedence, and curved sketch display."""
import unittest

import numpy as np
from PySide6.QtCore import Qt,QPointF
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication
from simuo.parts.feature_geometry import FeatureModel,PLANES,support_frame,to_world
from simuo.ui.parts.feature_editor import FeaturePartEditor
from simuo.ui.parts.part_viewport import PartViewport,sketch_world_points
from simuo.parts.sketch_geometry import Sketch


def rectangle():
    return Sketch([[-.05,-.04],[.05,-.04],[.05,.04],[-.05,.04]],True,[None]*4,.01)


def base_model():
    model=FeatureModel()
    feature=model.new_sketch({'type':'plane','name':'Front'})
    feature['sketch']=rectangle().geometry()
    feature['depth']=.03
    model.build()
    return model


def visible_plane_point(view,name):
    extent=view.plane_extent
    for u in (-.85,-.6,-.3,.3,.6,.85):
        for v in (-.85,-.6,-.3,.3,.6,.85):
            point=to_world([[u*extent,v*extent]],PLANES[name])[0]
            projection=view.project(point)
            if projection and view.rect().contains(projection[0].toPoint()) and view.pick_plane(projection[0])==name:
                return projection[0]
    raise AssertionError(f'No selectable visible patch found for {name}')


class PlaneViewportTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app=QApplication.instance() or QApplication([])

    def setUp(self):
        self.view=PartViewport()
        self.view.resize(800,600)
        self.addCleanup(self.view.close)

    def test_all_three_reference_planes_can_be_picked(self):
        for name in PLANES:
            with self.subTest(name=name):
                point=visible_plane_point(self.view,name)
                self.assertEqual(self.view.pick_plane(point),name)
        self.assertIsNone(self.view.pick_plane(QPointF(-10000,-10000)))

    def test_mouse_click_selects_plane_and_emits_name(self):
        names=[]
        self.view.plane_selected.connect(names.append)
        point=visible_plane_point(self.view,'Top')
        QTest.mouseClick(self.view,Qt.LeftButton,pos=point.toPoint())
        self.assertEqual(names,['Top'])
        self.assertEqual(self.view.support,{'type':'plane','name':'Top'})

    def test_orbit_drag_does_not_change_selection(self):
        names=[]
        self.view.plane_selected.connect(names.append)
        point=visible_plane_point(self.view,'Right').toPoint()
        QTest.mousePress(self.view,Qt.LeftButton,pos=point)
        QTest.mouseMove(self.view,point+QPointF(30,10).toPoint())
        QTest.mouseRelease(self.view,Qt.LeftButton,pos=point+QPointF(30,10).toPoint())
        self.assertEqual(names,[])

    def test_solid_face_takes_priority_over_reference_plane(self):
        self.view.model=base_model()
        self.view.fit()
        index=next(i for i,face in enumerate(self.view.model.faces) if face['normal'][2]>.9)
        point=self.view.project(self.view.model.faces[index]['frame']['origin'])[0]
        faces,planes=[],[]
        self.view.face_selected.connect(faces.append)
        self.view.plane_selected.connect(planes.append)
        QTest.mouseClick(self.view,Qt.LeftButton,pos=point.toPoint())
        self.assertEqual(faces,[index])
        self.assertEqual(planes,[])

    def test_plane_patches_remain_projectable_at_small_scales(self):
        self.view.distance=.0001
        extent=self.view.plane_extent
        self.assertLess(extent,.0001)
        for frame in PLANES.values():
            corners=to_world([[-extent,-extent],[extent,-extent],[extent,extent],[-extent,extent]],frame)
            self.assertIsNotNone(self.view._path(corners))

    def test_curved_draft_is_transformed_and_framed_on_each_plane(self):
        sketch=Sketch([[-.05,0]])
        sketch.add_arc([0,.05],[.05,0])
        for name in PLANES:
            with self.subTest(name=name):
                model=FeatureModel()
                feature=model.new_sketch({'type':'plane','name':name})
                feature['sketch']=sketch.geometry()
                model.build()
                points=sketch_world_points(feature)
                self.assertEqual(len(points),37)
                np.testing.assert_allclose(points,to_world(sketch.outline_points,support_frame(feature['support'])))
                self.view.model=model
                self.view.fit()
                bounds=np.ptp(points,axis=0)
                self.assertEqual(np.count_nonzero(bounds>1e-6),2)
                np.testing.assert_allclose(self.view.target,(points.max(axis=0)+points.min(axis=0))/2)
                self.assertFalse(self.view.grab().isNull())

    def test_plane_selection_routes_to_tree_and_new_sketch_support(self):
        editor=FeaturePartEditor()
        try:
            editor.viewport.resize(800,600)
            editor.viewport.fit()
            point=visible_plane_point(editor.viewport,'Right')
            QTest.mouseClick(editor.viewport,Qt.LeftButton,pos=point.toPoint())
            self.assertEqual(editor.selected_support,{'type':'plane','name':'Right'})
            self.assertEqual(editor.tree.currentItem().data(0,Qt.UserRole),('plane','Right'))
            editor.new_sketch()
            self.assertEqual(editor.active_feature['support'],{'type':'plane','name':'Right'})
            self.assertIs(editor.stack.currentWidget(),editor.canvas)
        finally:
            editor.dirty=False
            editor.close()

if __name__=='__main__':
    unittest.main()
