"""Camera framing consumes scene state without access to solver internals."""

from types import SimpleNamespace
import unittest
from unittest.mock import Mock

import glm
import numpy as np

from tests import ROOT
from simuo.project.scene import Scene, SceneObject
from simuo.project.transforms import rotation_matrix
from simuo.ui.physics_render import PhysicsRenderWindow


def viewport_rotation(angles):
    """Independent reference following the OpenGL viewport's GLM operations."""
    matrix = glm.mat4(1)
    for angle, axis in zip(angles, ((1, 0, 0), (0, 1, 0), (0, 0, 1))):
        matrix = glm.rotate(matrix, glm.radians(angle), glm.vec3(*axis))
    return np.array(matrix.to_list()).T[:3, :3]


class PhysicsFramingTests(unittest.TestCase):
    def test_rotation_matches_viewport_including_gimbal_lock(self):
        for angles in ([0, 0, 0], [90, 0, 0], [0, 90, 0], [0, 0, 90],
                       [20, 35, 65], [-130, -90, 275], [45, 90, -30]):
            with self.subTest(angles=angles):
                np.testing.assert_allclose(rotation_matrix(angles),
                                           viewport_rotation(angles), atol=2e-7)

    def test_framing_rotated_scaled_objects_without_solver_handle(self):
        objects = []
        for position, rotation, scale in (([2, 3, -4], [20, 35, 65], [2, 1, .5]),
                                          ([-1, 1, 2], [45, 90, -30], [.5, 3, 2])):
            obj = SceneObject(meshPath=ROOT / "Assets/aluminum_cube.simuOPart")
            obj.position, obj.rotation, obj.scale = position, rotation, scale
            objects.append(obj)
        scene = Scene()
        scene.objects = objects
        # Deliberately omit bullet/client/bodies: only the public scene is needed.
        world = SimpleNamespace(scene=scene, floor=False)
        window = SimpleNamespace(world=world, viewport=Mock())
        expected = np.concatenate([
            (obj.asset.vertices.reshape(-1, 6)[:, :3]*obj.scale)
            @ viewport_rotation(obj.rotation).T + obj.position for obj in objects
        ])
        for floor in (False, True):
            with self.subTest(floor=floor):
                world.floor = floor
                PhysicsRenderWindow.frame_scene(window)
                frame = window.viewport.frameObject.call_args.args[0]
                bounds = frame.asset.vertices.reshape(-1, 6)[:, :3]
                low, high = expected.min(axis=0), expected.max(axis=0)
                if floor:
                    low[1] = min(0, low[1])
                np.testing.assert_allclose(bounds, [low, high], atol=1e-6)
        self.assertEqual(objects[0].position, [2, 3, -4])

    def test_empty_scene_leaves_camera_unchanged(self):
        window = SimpleNamespace(world=SimpleNamespace(scene=Scene(), floor=True),
                                 viewport=Mock())
        PhysicsRenderWindow.frame_scene(window)
        window.viewport.frameObject.assert_not_called()
