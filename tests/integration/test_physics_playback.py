"""Playback controls with the real solver and a GPU-free viewport."""
import unittest
from unittest.mock import patch

from PySide6.QtCore import QTimer
from PySide6.QtWidgets import QApplication

from tests import ROOT
from tests.integration.viewport_stub import ViewportStub
from simuo.project.scene import Scene, SceneObject
from simuo.ui.physics_render import PhysicsRenderWindow


class PlaybackViewport(ViewportStub):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.timer = QTimer(self)

    def isValid(self):
        return True


class PhysicsPlaybackTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def window(self):
        source = SceneObject(meshPath=ROOT / "Assets/aluminum_cube.simuOPart")
        scene = Scene()
        scene.addObject(source)
        with patch("simuo.ui.physics_render.OpenGLViewport", PlaybackViewport):
            window = PhysicsRenderWindow(scene)
        window.timer.stop()
        self.addCleanup(window.close)
        return source, window

    def test_pause_step_reset_gravity_floor_and_snapshot_isolation(self):
        source, window = self.window()
        with patch("simuo.ui.physics_render.time.perf_counter", return_value=window.last_time+.05):
            window.tick()
        self.assertGreater(window.world.steps, 0)
        self.assertNotEqual(window.world.scene.objects[0].position, source.position)
        window.play.click()
        self.assertFalse(window.running)
        steps = window.world.steps
        window.tick()
        self.assertEqual(window.world.steps, steps)
        window.step_button.click()
        self.assertEqual(window.world.steps, steps+1)
        window.reset_button.click()
        self.assertEqual(window.world.time, 0)
        self.assertFalse(window.running)
        self.assertEqual(window.world.scene.objects[0].position, source.position)
        window.gravity.setValue(0)
        self.assertEqual(window.world.gravity, 0)
        self.assertEqual(window.world.model.opt.gravity.tolist(), [0, 0, 0])
        window.floor.setChecked(False)
        self.assertFalse(window.world.floor)
        self.assertNotIn(window.ground, window.render_scene.objects)
        self.assertEqual(len(window.viewport.renderObjects), 1)
        window.floor.setChecked(True)
        self.assertIn(window.ground, window.render_scene.objects)
        self.assertEqual(len(window.viewport.renderObjects), 2)
        self.assertEqual(source.position, [0, 1.1, 0])

    def test_windows_own_separate_native_state_and_close_independently(self):
        _, first = self.window()
        _, second = self.window()
        self.assertIsNot(first.world.model, second.world.model)
        self.assertIsNot(first.world.data, second.world.data)
        first.close()
        self.assertTrue(first.world.closed)
        second.single_step()
        self.assertEqual(second.world.steps, 1)
        second.close()
        self.assertTrue(second.world.closed)

    def test_solver_error_pauses_and_explains_failure(self):
        _, window = self.window()
        with patch.object(window.world, "step", side_effect=RuntimeError("invalid state")), \
             patch("simuo.ui.physics_render.time.perf_counter", return_value=window.last_time+.05):
            window.tick()
        self.assertFalse(window.running)
        self.assertEqual(window.info.text(), "Simulation stopped: invalid state")
        self.assertTrue(window.stats.text().startswith("PAUSED"))

    def test_manual_step_reports_solver_error_and_reset_clears_it(self):
        from mujoco import FatalError

        _, window = self.window()
        with patch.object(window.world, "step", side_effect=FatalError("invalid state")):
            window.single_step()
        self.assertFalse(window.running)
        self.assertEqual(window.info.text(), "Simulation stopped: invalid state")
        window.reset_button.click()
        self.assertNotIn("invalid state", window.info.text())
        window.step_button.click()
        self.assertEqual(window.world.steps, 1)
