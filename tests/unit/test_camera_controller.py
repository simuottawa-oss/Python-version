"""Shared navigation timing, coordinate frames and camera fitting."""
import unittest
import glm
import numpy as np
from PySide6.QtCore import QEvent, Qt
from PySide6.QtGui import QKeyEvent
from PySide6.QtWidgets import QApplication, QWidget
from simuo.rendering.camera import Camera
from simuo.rendering.camera_controller import CameraController


class CameraControls(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def controller(self):
        viewport = QWidget()
        viewport.camera = Camera()
        self.addCleanup(viewport.deleteLater)
        return CameraController(viewport)

    def test_movement_is_independent_of_frame_rate(self):
        positions = []
        for frames in (30, 60, 120):
            controller = self.controller()
            controller.keys.update((Qt.Key_W, Qt.Key_D, Qt.Key_Space))
            for _ in range(frames):
                controller.advance(1/frames)
            positions.append(tuple(controller.camera.position))
        np.testing.assert_allclose(positions, [[10., 12., 18.]]*3, atol=1e-4)

    def test_vertical_motion_and_mouse_look_use_shared_world_axes(self):
        controller = self.controller()
        controller.look(150., 10000.)
        self.assertEqual(controller.camera.pitch, 89.)
        before = glm.vec3(controller.camera.position)
        controller.keys.add(Qt.Key_Space)
        controller.advance(.1)
        np.testing.assert_allclose(controller.camera.position-before, (0., 1., 0.), atol=1e-6)
        controller.keys.clear()
        controller.keys.add(Qt.Key_Alt)
        controller.advance(.1)
        np.testing.assert_allclose(controller.camera.position, before, atol=1e-6)
        before = glm.vec3(controller.camera.position)
        controller.dolly(2.)
        np.testing.assert_allclose(controller.camera.position-before, controller.camera.front*.3, atol=2e-6)

    def test_shortcuts_and_manipulation_clear_navigation(self):
        controller = self.controller()
        controller.keys.add(Qt.Key_W)
        before = glm.vec3(controller.camera.position)
        event = QKeyEvent(QEvent.KeyPress, Qt.Key_Control, Qt.ControlModifier)
        self.assertTrue(controller.key_press(event))
        self.assertFalse(controller.advance(.1))
        self.assertEqual(controller.camera.position, before)
        controller.keys.add(Qt.Key_Alt)
        controller.advance(.1, blocked=True)
        self.assertFalse(controller.keys)
        self.assertEqual(controller.camera.position, before)
        self.assertFalse(controller.key_press(QKeyEvent(QEvent.KeyPress, Qt.Key_F, Qt.NoModifier)))

    def test_frame_points_fits_bounds_and_preserves_view_direction(self):
        camera = Camera()
        camera.rotate(120., -80.)
        front = glm.vec3(camera.front)
        points = [(x,y,z) for x in (-200.,100.) for y in (-1.,50.) for z in (-4.,4.)]
        self.assertTrue(camera.frame_points(points, .5))
        self.assertEqual(camera.front, front)
        projection = glm.perspective(glm.radians(camera.field_of_view), .5, camera.near_plane, camera.far_plane)
        for point in points:
            clip = projection*camera.view_matrix()*glm.vec4(*point,1.)
            self.assertGreater(clip.w, 0.)
            self.assertLessEqual(max(abs(clip.x/clip.w), abs(clip.y/clip.w), abs(clip.z/clip.w)), 1.+1e-5)
        self.assertFalse(camera.frame_points([], 1.))
        self.assertFalse(camera.look_at(camera.position))

    def test_playback_exports_the_same_camera_class(self):
        from simuo.physics.viewport.renderer import Camera as PlaybackCamera
        self.assertIs(PlaybackCamera, Camera)
