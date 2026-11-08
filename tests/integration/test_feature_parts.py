"""Feature solids, support planes/faces, persistence, picking and editor state."""
import copy
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

import numpy as np

from tests import ROOT
from simuo.parts.feature_geometry import FeatureModel,PLANES,support_frame,to_world
from simuo.parts.feature_document import new_feature_document,save_feature_document,open_feature_document
from simuo.parts.sketch_geometry import Sketch
from simuo.parts.part_assets import load_asset
from simuo.parts.part_format import load_part
from simuo.project.scene import Scene,SceneObject
from simuo.physics.physics_world import PhysicsWorld
from simuo.parts.part_export import export_vertices


def rectangle(x=.1,y=.08):
    return Sketch([[-x/2,-y/2],[x/2,-y/2],[x/2,y/2],[-x/2,y/2]],True,[None]*4)


def base_model(plane="Front",depth=.03,symmetric=False):
    model = FeatureModel()
    feature = model.new_sketch({"type":"plane","name":plane})
    feature["sketch"],feature["depth"],feature["symmetric"] = rectangle().geometry(),depth,symmetric
    return model.build()


def boss_model():
    model = base_model()
    index = next(i for i,f in enumerate(model.faces) if f["normal"][2]>.9)
    feature = model.new_sketch(model.face_support(index))
    feature["sketch"],feature["depth"] = rectangle(.04,.02).geometry(),.02
    return model.build()


class FeatureGeometryTests(unittest.TestCase):
    def test_reference_planes_have_correct_world_orientations(self):
        for plane,expected in [("Front",[.1,.08,.03]),("Right",[.03,.08,.1]),("Top",[.1,.03,.08])]:
            with self.subTest(plane=plane):
                model = base_model(plane)
                np.testing.assert_allclose(model.size,expected,rtol=1e-6)
                self.assertEqual(len(model.faces),6)
                self.assertAlmostEqual(model.volume,.00024,places=9)

    def test_joined_face_extrusion_is_manifold_and_has_exact_union_volume(self):
        model = boss_model()
        self.assertAlmostEqual(model.volume,.000256,places=9)
        self.assertEqual(len(model.features),2)
        np.testing.assert_allclose(model.size,[.1,.08,.05],rtol=1e-6)
        triangles = model.vertices.reshape(-1,3,6)[:,:,:3]
        counts = {}
        for triangle in triangles:
            for a,b in ((0,1),(1,2),(2,0)):
                edge = tuple(sorted((tuple(triangle[a]),tuple(triangle[b]))))
                counts[edge] = counts.get(edge,0)+1
        self.assertTrue(all(count==2 for count in counts.values()))

    def test_overlapping_additions_do_not_double_count_volume(self):
        model = base_model()
        feature = model.new_sketch({"type":"plane","name":"Front"})
        feature["sketch"],feature["depth"] = rectangle().geometry(),.05
        model.build()
        self.assertAlmostEqual(model.volume,.0004,places=9)

    def test_reverse_and_symmetric_extrusions(self):
        reverse = base_model(depth=-.03).vertices.reshape(-1,6)[:,:3]
        self.assertAlmostEqual(reverse[:,2].min(),-.03,places=7)
        self.assertAlmostEqual(reverse[:,2].max(),0,places=7)
        for depth in (.03,-.03):
            symmetric = base_model(depth=depth,symmetric=True).vertices.reshape(-1,6)[:,:3]
            np.testing.assert_allclose([symmetric[:,2].min(),symmetric[:,2].max()],[-.015,.015],atol=1e-8)

    def test_face_sketch_on_side_of_solid(self):
        model = base_model()
        index = next(i for i,f in enumerate(model.faces) if f["normal"][0]>.9)
        feature = model.new_sketch(model.face_support(index))
        feature["sketch"],feature["depth"] = rectangle(.01,.02).geometry(),.02
        model.build()
        self.assertAlmostEqual(model.volume,.000244,places=9)
        self.assertAlmostEqual(float(model.size[0]),.12,places=6)

    def test_whole_planar_face_can_be_extruded_directly(self):
        model = base_model()
        index = next(i for i,f in enumerate(model.faces) if f["normal"][2]>.9)
        sketch = model.face_sketch(index)
        feature = model.new_sketch(model.face_support(index))
        feature["sketch"],feature["depth"] = sketch.geometry(),.02
        model.build()
        self.assertAlmostEqual(model.volume,.0004,places=9)

    def test_pull_face_after_multiple_extrusions_keeps_exact_support_precision(self):
        model = boss_model()
        index = next(i for i,f in enumerate(model.faces) if f["normal"][2]>.9 and abs(f["frame"]["origin"][2]-.05)<1e-9)
        sketch,support = model.face_sketch(index),model.face_support(index)
        feature = model.new_sketch(support)
        feature["sketch"],feature["depth"] = sketch.geometry(),.01
        model.build()
        self.assertAlmostEqual(model.volume,.000264,places=9)

    def test_pulling_a_face_with_holes_requires_a_sketch(self):
        model = boss_model()
        # The original top cap now surrounds the boss and has an inner loop.
        face = next(i for i,f in enumerate(model.faces) if f["normal"][2]>.9 and abs(f["frame"]["origin"][2]-.03)<1e-7)
        with self.assertRaisesRegex(ValueError,"holes"):
            model.face_sketch(face)

    def test_disconnected_addition_and_moved_support_are_rejected(self):
        model = base_model()
        index = next(i for i,f in enumerate(model.faces) if f["normal"][2]>.9)
        feature = model.new_sketch(model.face_support(index))
        sketch = rectangle(.02,.02)
        sketch.points = [[x+1,y] for x,y in sketch.points]
        feature["sketch"],feature["depth"] = sketch.geometry(),.01
        with self.assertRaisesRegex(ValueError,"join"):
            model.build()
        model = boss_model()
        model.features[0]["depth"] = .04
        with self.assertRaisesRegex(ValueError,"supporting face"):
            model.build()

    def test_invalid_frames_and_duplicate_draft_ids_rejected(self):
        model = FeatureModel()
        first = model.new_sketch({"type":"plane","name":"Front"})
        model.features.append(copy.deepcopy(first))
        with self.assertRaisesRegex(ValueError,"unique"):
            model.build()
        with self.assertRaises(ValueError):
            support_frame({"type":"face","parent":"x","label":"Face","frame":{"origin":[0,0,0],"u":[1,0,0],"v":[1,0,0]}})

    def test_missing_geometry_dependency_has_actionable_error(self):
        model = base_model()
        with patch.dict(sys.modules,{"manifold3d":None}),self.assertRaisesRegex(ValueError,"project requirements"):
            model.build()

    def test_roundtrip_retains_all_supports_sketches_and_scene_physics(self):
        data,_ = new_feature_document()
        model = boss_model()
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder)/"features.simuOPart"
            save_feature_document(path,data,model)
            loaded_data,loaded = open_feature_document(path)
            self.assertEqual(loaded_data["version"],3)
            self.assertEqual(loaded.geometry(),model.geometry())
            asset = load_asset(path)
            self.assertAlmostEqual(asset.part.mass,.256,places=6)
            scene = Scene()
            scene.addObject(SceneObject(meshPath=path))
            world = PhysicsWorld(scene,floor=False)
            try:
                self.assertAlmostEqual(world.masses[0],.256,places=6)
                world.step(48)
                self.assertLess(world.scene.objects[0].position[1],1)
            finally:
                world.close()

    def test_drafts_save_but_cannot_be_imported_without_extrusion(self):
        data,model = new_feature_document()
        model.new_sketch({"type":"plane","name":"Top"})
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder)/"draft.simuOPart"
            save_feature_document(path,data,model)
            self.assertEqual(open_feature_document(path)[1].features[0]["support"]["name"],"Top")
            with self.assertRaisesRegex(ValueError,"no solid"):
                load_asset(path)

    def test_export_contains_the_whole_joined_body(self):
        model = boss_model()
        with tempfile.TemporaryDirectory() as folder:
            for kind in ("obj","stl"):
                path = Path(folder)/("part."+kind)
                export_vertices(path,model.vertices,kind)
                text = path.read_text()
                if kind=="obj":
                    self.assertEqual(load_asset(path).vertices.size,model.vertices.size)
                else:
                    self.assertEqual(text.count("facet normal"),model.vertices.size//18)

    def test_existing_box_and_v2_sketch_migrate_without_resizing(self):
        for name,expected in [("aluminum_cube",[.2,.2,.2]),("sketch_plate",[.1,.06,.01])]:
            with self.subTest(name=name):
                _,model = open_feature_document(ROOT/f"Assets/{name}.simuOPart")
                np.testing.assert_allclose(model.size,expected,rtol=1e-6)
                original = load_part(ROOT/f"Assets/{name}.simuOPart")
                self.assertAlmostEqual(model.volume,original.volume,places=9)


class FeatureEditorTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        from PySide6.QtWidgets import QApplication
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        from simuo.ui.parts.feature_editor import FeaturePartEditor
        self.editor = FeaturePartEditor()
        self.addCleanup(self.close)

    def close(self):
        self.editor.dirty = False
        self.editor.close()

    def test_tree_planes_default_3d_and_dimensioned_extrusion(self):
        editor = self.editor
        self.assertIs(editor.stack.currentWidget(),editor.viewport)
        planes = editor.tree.topLevelItem(0)
        self.assertEqual([planes.child(i).text(0) for i in range(3)],["Front Plane","Right Plane","Top Plane"])
        editor.tree_clicked(planes.child(2))
        editor.new_sketch()
        self.assertIs(editor.stack.currentWidget(),editor.canvas)
        self.assertEqual(editor.active_feature["support"]["name"],"Top")
        editor.commit(rectangle())
        editor.select_line(0)
        editor.length.setValue(150)
        editor.apply_dimension()
        editor.finish_sketch()
        editor.extrude_active(.02)
        np.testing.assert_allclose(editor.model.size,[.15,.02,.08],rtol=1e-6)

    def test_face_selection_and_feature_undo_redo(self):
        editor = self.editor
        editor.new_sketch()
        editor.commit(rectangle())
        editor.extrude_active(.03)
        base_volume = editor.model.volume
        index = next(i for i,f in enumerate(editor.model.faces) if f["normal"][2]>.9)
        editor.select_face(index)
        editor.new_sketch()
        self.assertEqual(editor.active_feature["support"]["type"],"face")
        editor.commit(rectangle(.02,.02))
        editor.extrude_active(.02)
        self.assertGreater(editor.model.volume,base_volume)
        editor.undo()
        self.assertAlmostEqual(editor.model.volume,base_volume)
        editor.redo()
        self.assertGreater(editor.model.volume,base_volume)

    def test_selected_face_extrudes_without_drawing_another_sketch(self):
        editor = self.editor
        editor.new_sketch()
        editor.commit(rectangle())
        editor.extrude_active(.03)
        base_volume = editor.model.volume
        index = next(i for i,f in enumerate(editor.model.faces) if f["normal"][0]>.9)
        editor.select_face(index)
        editor.extrude_face(index,.02)
        self.assertAlmostEqual(float(editor.model.size[0]),.12,places=6)
        self.assertEqual(editor.active_feature["support"]["type"],"face")
        editor.undo()
        self.assertAlmostEqual(editor.model.volume,base_volume)
        editor.redo()
        self.assertGreater(editor.model.volume,base_volume)

    def test_selecting_sketch_feature_clears_direct_face_pull_target(self):
        editor = self.editor
        editor.new_sketch()
        editor.commit(rectangle())
        editor.extrude_active(.03)
        index = next(i for i,f in enumerate(editor.model.faces) if f["normal"][0]>.9)
        editor.select_face(index)
        item = editor.tree.topLevelItem(1).child(0)
        editor.tree_clicked(item)
        self.assertEqual(editor.viewport.selected_face,-1)
        self.assertEqual(editor.selected_support,{"type":"plane","name":"Front"})

    def test_picking_returns_nearest_visible_face(self):
        editor = self.editor
        editor.model = base_model()
        editor.refresh()
        editor.viewport.resize(700,500)
        editor.viewport.fit()
        index = next(i for i,f in enumerate(editor.model.faces) if f["normal"][2]>.9)
        point = editor.model.faces[index]["frame"]["origin"]
        projected = editor.viewport.project(point)[0]
        self.assertEqual(editor.viewport.pick(projected),index)

    def test_failed_save_and_open_preserve_model(self):
        editor = self.editor
        editor.new_sketch()
        editor.commit(rectangle())
        editor.extrude_active(.03)
        previous = editor.model.geometry()
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder)/"part.simuOPart"
            self.assertTrue(editor._save_to(path))
            with patch("simuo.parts.feature_document.atomic_write",side_effect=OSError("disk full")),patch("simuo.ui.parts.feature_editor.QMessageBox.warning"):
                self.assertFalse(editor._save_to(path))
            with patch("simuo.ui.parts.feature_editor.QMessageBox.warning"):
                self.assertFalse(editor.open_path(Path(folder)/"missing.simuOPart"))
        self.assertEqual(editor.model.geometry(),previous)


if __name__=="__main__":
    unittest.main()
