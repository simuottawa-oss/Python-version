"""Ray geometry and camera projection checks for the integrated debug-ray feature."""
from types import SimpleNamespace
import unittest

import glm
import numpy as np
from PySide6.QtCore import QPointF

from simuo.physics.viewport.ray import Ray
from simuo.physics.viewport.renderer import Camera


class RayTests(unittest.TestCase):
    def test_rendered_segment_has_requested_origin_endpoint_and_dtype(self):
        ray = Ray([1, 2, 3], [0, 0, -1])
        np.testing.assert_allclose(ray.at(5), [1, 2, -2])
        vertices = ray.render(5)
        self.assertEqual(vertices.dtype, np.float32)
        np.testing.assert_allclose(vertices, [1, 2, 3, 1, 2, -2])
        np.testing.assert_allclose(ray.position, [1, 2, 3])

    def ray_at(self, camera, x, y):
        event = SimpleNamespace(position=lambda: QPointF(x, y))
        projection = glm.perspective(glm.radians(60.0), 800 / 600, 0.1, 1000.0)
        return camera.mouse_ray(event, 800, 600, projection, camera.view_matrix())

    def test_center_ray_matches_translated_and_rotated_camera(self):
        camera = Camera()
        camera.position = glm.vec3(4, 7, 12)
        for yaw, pitch in [(-90, 0), (-45, 20), (30, -15)]:
            with self.subTest(yaw=yaw, pitch=pitch):
                camera.yaw, camera.pitch = yaw, pitch
                camera.update_vectors()
                origin, direction = self.ray_at(camera, 400, 300)
                np.testing.assert_allclose(origin, camera.position)
                np.testing.assert_allclose(direction, camera.front, atol=2e-5)
                self.assertAlmostEqual(glm.length(direction), 1.0, places=5)

    def test_corner_rays_follow_screen_axes_and_stay_in_front(self):
        camera = Camera()
        for x, y, right_sign, up_sign in [(0, 0, -1, 1), (800, 0, 1, 1),
                                          (0, 600, -1, -1), (800, 600, 1, -1)]:
            with self.subTest(x=x, y=y):
                _, direction = self.ray_at(camera, x, y)
                self.assertGreater(glm.dot(direction, camera.front), 0)
                self.assertGreater(glm.dot(direction, camera.right) * right_sign, 0)
                self.assertGreater(glm.dot(direction, camera.up) * up_sign, 0)
                self.assertAlmostEqual(glm.length(direction), 1.0, places=5)


if __name__ == "__main__":
    unittest.main()
