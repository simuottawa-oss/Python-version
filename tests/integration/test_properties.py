"""Property editing, scene persistence, and Bullet integration."""
import json
from dataclasses import replace
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from PySide6.QtWidgets import QApplication, QDialog, QListWidget, QMessageBox, QWidget
from tests import ROOT
from simuo.project.scene import Scene, SceneObject
from tests.support import create_scene_window
from simuo.physics.physics_world import PhysicsWorld
from simuo.ui.properties_dialog import PropertiesDialog


from tests.integration.viewport_stub import ViewportStub as Viewport


class PropertiesTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix='simuo properties ')
        self.addCleanup(self.temp.cleanup)
        self.folder = Path(self.temp.name)
        self.patcher = patch('simuo.ui.scene_window.OpenGLViewport', Viewport)
        self.patcher.start()
        self.addCleanup(self.patcher.stop)
        self.window = create_scene_window()
        self.addCleanup(self.dispose)
        self.obj = SceneObject(meshPath=ROOT/'Assets/aluminum_cube.simuOPart')
        self.window.scene.addObject(self.obj)

    def dispose(self):
        with patch('simuo.ui.scene_window.QMessageBox.question', return_value=QMessageBox.Discard):
            self.window.close()

    def edit(self, accept=True):
        def interact(dialog):
            dialog.bounce.setValue(.8)
            for control, value in zip(dialog.velocity, [1.25, -2.5, 3.75]):
                control.setValue(value)
            return QDialog.Accepted if accept else QDialog.Rejected
        with patch.object(PropertiesDialog, 'exec', new=interact):
            self.window.propertiesAction.trigger()

    def test_accept_edits_only_selected_instance_and_marks_dirty(self):
        original = self.obj.part
        self.edit()
        self.assertEqual(self.obj.restitution, .8)
        self.assertEqual(self.obj.velocity, [1.25, -2.5, 3.75])
        self.assertTrue(self.window.scene.dirty)
        self.assertIs(self.obj.part, original)
        self.assertEqual(original.restitution, .45)

    def test_cancel_leaves_object_and_dirty_state_unchanged(self):
        self.edit(accept=False)
        self.assertEqual(self.obj.restitution, .45)
        self.assertEqual(self.obj.velocity, [.35, 0, .15])
        self.assertFalse(self.window.scene.dirty)

    def test_unchanged_dialog_preserves_precision_and_clean_state(self):
        self.obj.setPhysicsProperties(.123456789123, [1e-10, -1.123456789, 3])
        with patch.object(PropertiesDialog, 'exec', return_value=QDialog.Accepted):
            self.window.propertiesAction.trigger()
        self.assertEqual(self.obj.restitution, .123456789123)
        self.assertEqual(self.obj.velocity, [1e-10, -1.123456789, 3])
        self.assertFalse(self.window.scene.dirty)

    def test_properties_roundtrip_and_original_part_unchanged(self):
        before = Path(self.obj.meshPath).read_bytes()
        self.edit()
        path = self.folder/'edited.simuO'
        self.assertTrue(self.window.saveFile(destination=path))
        self.window.loadFile(path, uploadToGPU=False)
        loaded = self.window.scene.objects[0]
        self.assertEqual(loaded.restitution, .8)
        self.assertEqual(loaded.velocity, [1.25, -2.5, 3.75])
        self.assertEqual(Path(self.obj.meshPath).read_bytes(), before)
        self.assertFalse(self.window.scene.dirty)

    def test_old_scene_uses_part_bounce_default(self):
        path = self.folder/'old.simuO'
        path.write_text(json.dumps({'objects':[{'name':'Old','meshPath':str(self.obj.meshPath)}]}))
        self.window.loadFile(path, uploadToGPU=False)
        self.assertEqual(self.window.scene.objects[0].restitution, .45)

    def test_picker_selects_correct_object_with_duplicate_names_and_axis(self):
        axis = SceneObject(name='Axis')
        other = SceneObject(name=self.obj.name, meshPath=self.obj.meshPath)
        self.window.scene.objects[:] = [axis, self.obj, other]
        def choose(dialog):
            items = dialog.findChild(QListWidget)
            self.assertEqual(items.count(), 2)
            items.setCurrentRow(1)
            return QDialog.Accepted
        with patch.object(QDialog, 'exec', new=choose), \
             patch.object(self.window, 'openPropertiesDialog') as show:
            self.window.propertiesAction.trigger()
        show.assert_called_once_with(other)

    def test_empty_scene_explains_import_first(self):
        self.window.scene.objects.clear()
        with patch('simuo.ui.scene_window.QMessageBox.information') as message:
            self.window.propertiesAction.trigger()
        message.assert_called_once()

    def test_bounds_and_invalid_values_do_not_partially_apply(self):
        dialog = PropertiesDialog(self.obj)
        self.assertEqual((dialog.bounce.minimum(), dialog.bounce.maximum()), (0, 1))
        original = self.obj.velocity[:]
        for value in [-.1, 1.1, float('nan'), True]:
            with self.subTest(value=value), self.assertRaises(ValueError):
                self.obj.setPhysicsProperties(value, [1, 2, 3])
        with self.assertRaises(ValueError):
            self.obj.setPhysicsProperties(.9, [0, float('inf'), 0])
        self.assertEqual(self.obj.restitution, .45)
        self.assertEqual(self.obj.velocity, original)

    def test_bullet_uses_overrides_and_initial_velocity_on_snapshot(self):
        self.obj.setPhysicsProperties(.8, [1, 2, 3])
        with PhysicsWorldContext(self.window.scene) as world:
            info = world.bullet.getDynamicsInfo(world.bodies[0], -1, physicsClientId=world.client)
            self.assertAlmostEqual(info[5], .8)
            velocity, _ = world.bullet.getBaseVelocity(world.bodies[0], physicsClientId=world.client)
            self.assertEqual(velocity, (1, 2, 3))
            world.step(24)
            self.assertGreater(world.scene.objects[0].position[0], 0)
            self.assertEqual(self.obj.position, [0, 1.1, 0])
            self.assertEqual(self.obj.velocity, [1, 2, 3])

    def test_legacy_static_surface_bounce_reaches_bullet(self):
        legacy = SceneObject(meshPath=ROOT/'Assets/cube.simuOPart')
        legacy.setPhysicsProperties(.65, [1, 2, 3])
        self.window.scene.objects[:] = [legacy]
        with PhysicsWorldContext(self.window.scene) as world:
            self.assertEqual(world.masses, [0])
            info = world.bullet.getDynamicsInfo(world.bodies[0], -1, physicsClientId=world.client)
            self.assertAlmostEqual(info[5], .65)

    def select_body_type(self, mode, accept=True):
        def interact(dialog):
            dialog.body_type.setCurrentIndex(dialog.body_type.findData(mode))
            return QDialog.Accepted if accept else QDialog.Rejected
        with patch.object(PropertiesDialog, 'exec', new=interact):
            self.window.propertiesAction.trigger()

    def test_body_type_defaults_and_cancel(self):
        dialog = PropertiesDialog(self.obj)
        self.assertEqual(dialog.body_type.currentData(), "dynamic")
        legacy = SceneObject(meshPath=ROOT/'Assets/cube.simuOPart')
        static_dialog = PropertiesDialog(legacy)
        self.assertEqual(static_dialog.body_type.currentData(), "static")
        self.select_body_type("static", accept=False)
        self.assertEqual(self.obj.body_type, 'dynamic')
        self.assertFalse(self.window.scene.dirty)

    def test_switches_between_static_and_dynamic_in_bullet(self):
        original_part = self.obj.part
        self.select_body_type("static")
        self.assertEqual(self.obj.body_type, 'static')
        self.assertTrue(self.window.scene.dirty)
        with PhysicsWorldContext(self.window.scene) as world:
            self.assertEqual(world.masses, [0])
            world.set_gravity(-9.81)
            world.step(48)
            self.assertEqual(world.scene.objects[0].position, self.obj.position)
        self.select_body_type("dynamic")
        with PhysicsWorldContext(self.window.scene) as world:
            self.assertGreater(world.masses[0], 0)
            world.set_gravity(-9.81)
            world.step(48)
            self.assertLess(world.scene.objects[0].position[1], self.obj.position[1])
        self.assertIs(self.obj.part, original_part)
        self.assertEqual(original_part.body_type, 'dynamic')

    def test_body_type_persists_without_changing_original_part(self):
        original = Path(self.obj.meshPath).read_bytes()
        self.select_body_type("static")
        path = self.folder/'static.simuO'
        self.assertTrue(self.window.saveFile(destination=path))
        self.assertEqual(json.loads(path.read_text())['objects'][0]['body_type'], 'static')
        self.window.loadFile(path, uploadToGPU=False)
        loaded = self.window.scene.objects[0]
        self.assertEqual(loaded.body_type, 'static')
        static_dialog = PropertiesDialog(loaded)
        self.assertEqual(static_dialog.body_type.currentData(), "static")
        self.assertEqual(Path(loaded.meshPath).read_bytes(), original)
        self.assertEqual(loaded.part.body_type, 'dynamic')

    def test_originally_static_json_can_become_dynamic(self):
        self.obj.part = replace(self.obj.part, body_type='static')
        static_dialog = PropertiesDialog(self.obj)
        self.assertEqual(static_dialog.body_type.currentData(), "static")
        self.select_body_type("dynamic")
        with PhysicsWorldContext(self.window.scene) as world:
            self.assertGreater(world.masses[0], 0)
        self.assertEqual(self.obj.part.body_type, 'static')

    def test_dynamic_legacy_mesh_falls_and_collides_with_floor(self):
        legacy = SceneObject(meshPath=ROOT/'Assets/cube.simuOPart')
        legacy.position = [0,3,0]
        self.window.scene.objects[:] = [legacy]
        self.select_body_type("dynamic")
        self.assertEqual(legacy.body_type, 'dynamic')
        path = self.folder/'legacy-dynamic.simuO'
        self.assertTrue(self.window.saveFile(destination=path))
        self.window.loadFile(path, uploadToGPU=False)
        self.assertEqual(self.window.scene.objects[0].body_type, 'dynamic')
        world = PhysicsWorld(self.window.scene)
        self.addCleanup(world.close)
        self.assertEqual(world.masses, [1])
        world.step(48)
        self.assertLess(world.scene.objects[0].position[1], 3)
        world.step(2352)
        self.assertAlmostEqual(world.scene.objects[0].position[1], 1, delta=.015)
        self.assertEqual(legacy.position, [0,3,0])

    def test_dialog_edits_kinematic_motion_and_preserves_it_when_reopened(self):
        def edit(dialog):
            dialog.body_type.setCurrentIndex(dialog.body_type.findData("kinematic"))
            dialog.acceleration[0].setValue(3)
            return QDialog.Accepted

        with patch.object(PropertiesDialog, "exec", new=edit):
            self.window.propertiesAction.trigger()
        self.assertEqual(self.obj.body_type, "kinematic")
        self.assertEqual(self.obj.acceleration, [3, 0, 0])

        with patch.object(PropertiesDialog, "exec", return_value=QDialog.Accepted):
            self.window.propertiesAction.trigger()
        self.assertEqual(self.obj.body_type, "kinematic")
        self.assertEqual(self.window.editor_state.undo_stack.count(), 1)
        self.window.editor_state.undo_stack.undo()
        self.assertEqual(self.obj.body_type, "dynamic")
        self.assertEqual(self.obj.acceleration, [0, 0, 0])

    def test_invalid_body_type_does_not_partially_apply(self):
        velocity = self.obj.velocity[:]
        with self.assertRaises(ValueError):
            self.obj.setPhysicsProperties(.9, [1,2,3], 'unknown')
        self.assertEqual(self.obj.restitution, .45)
        self.assertEqual(self.obj.velocity, velocity)
        self.assertEqual(self.obj.body_type, 'dynamic')


class PhysicsWorldContext:
    def __init__(self, scene):
        self.world = PhysicsWorld(scene, gravity=0, floor=False)
    def __enter__(self):
        return self.world
    def __exit__(self, *exc):
        self.world.close()


if __name__ == '__main__':
    unittest.main()
