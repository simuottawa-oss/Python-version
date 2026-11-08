"""Projection and gizmo math independent of a graphics driver."""

import math
import unittest
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "src"))

import glm
import numpy as np

from simuo.rendering.camera import Camera
from simuo.rendering.manipulation import Gizmo, Projection, TransformDrag, box_candidates, matrix_euler, rotation_matrix
from part_assets import loadObjFlatShaded
from simuo.rendering.picking import PickMesh, object_matrix
from scene import SceneObject


class Manipulation(unittest.TestCase):
    def setUp(self):
        self.camera = Camera()
        self.camera.position = glm.vec3(0, 0, 10)
        self.projection = Projection(self.camera, 800, 600)
        self.objects = [SceneObject('A'), SceneObject('B')]
        self.objects[0].position = [-2, 0, 0]
        self.objects[1].position = [2, 0, 0]

    def drag(self, tool, key, orientation='world', pivot='median'):
        gizmo = Gizmo(self.objects, tool, self.projection, orientation, pivot)
        handle = next(handle for handle in gizmo.handles if handle.key == key)
        point = handle.points[-1] if handle.kind == 'axis' else handle.points[0]
        return TransformDrag(gizmo, handle, point), point

    def test_euler_conversion_matches_renderer_including_gimbal_lock(self):
        obj = self.objects[0]
        obj.position = [0, 0, 0]
        for angles in ([10, 20, 30], [-50, 90, 20], [40, -90, 70], [200, -170, 350]):
            with self.subTest(angles=angles):
                obj.rotation = angles
                actual = np.array(object_matrix(obj), dtype=float)[:3, :3]
                np.testing.assert_allclose(rotation_matrix(angles), actual, atol=3e-7)
                np.testing.assert_allclose(rotation_matrix(matrix_euler(actual)), actual, atol=3e-7)

    def test_axis_movement_preserves_spacing_and_other_components(self):
        drag, point = self.drag('move', '0')
        updates = drag.updates(point + [80, 40])
        positions = [np.array(updates[obj.identifier]['position']) for obj in self.objects]
        np.testing.assert_allclose(positions[1]-positions[0], [4, 0, 0])
        self.assertGreater(positions[0][0], -2)
        np.testing.assert_allclose(positions[0][1:], [0, 0], atol=1e-9)
        snapped = drag.updates(point + [80, 40], snap=True)
        self.assertEqual(snapped[self.objects[0].identifier]['position'][0] % 1, 0)
        fine = drag.updates(point + [80, 40], precision=True)
        self.assertAlmostEqual(fine[self.objects[0].identifier]['position'][0]+2, (positions[0][0]+2)/10)

    def test_local_axis_follows_active_object_and_plane_locks_normal(self):
        self.objects[1].rotation = [0, 0, 90]
        drag, point = self.drag('move', '0', 'local')
        update = drag.updates(point + [40, -60])[self.objects[0].identifier]['position']
        self.assertAlmostEqual(update[0], -2)
        self.assertGreater(update[1], 0)
        plane, point = self.drag('move', '01')
        update = plane.updates(point + [30, -40])[self.objects[0].identifier]['position']
        self.assertGreater(update[0], -2)
        self.assertGreater(update[1], 0)
        self.assertEqual(update[2], 0)

    def test_depth_axis_and_center_remain_usable(self):
        drag, point = self.drag('move', '2')
        self.assertEqual(drag.handle.kind, 'depth')
        self.assertEqual(drag.gizmo.hit(point).key, '2')
        update = drag.updates(point + [0, -40])[self.objects[0].identifier]['position']
        self.assertGreater(update[2], 0)
        free, point = self.drag('move', 'free')
        self.assertEqual(free.gizmo.hit(point).key, 'free')
        update = free.updates(point + [20, -30])[self.objects[0].identifier]['position']
        self.assertGreater(update[0], -2)
        self.assertGreater(update[1], 0)

    def test_rotate_around_median_and_active_pivots_and_snap(self):
        for pivot, expected in (('median', [0, -2, 0]), ('active', [2, -4, 0])):
            drag, point = self.drag('rotate', '2', pivot=pivot)
            center = drag.gizmo.center[:2]
            offset = point-center
            # A positive 90 degree world rotation appears counterclockwise on screen.
            end = center + [offset[1], -offset[0]]
            updates = drag.updates(end, snap=True)
            np.testing.assert_allclose(updates[self.objects[0].identifier]['position'], expected, atol=1e-6)
            np.testing.assert_allclose(rotation_matrix(updates[self.objects[0].identifier]['rotation']),
                                       rotation_matrix([0, 0, 90]), atol=1e-6)

    def test_scaling_multiplies_original_scales_and_positions(self):
        self.objects[0].scale = [-2, 3, .5]
        drag, point = self.drag('scale', '0')
        updates = drag.updates(point + [80, 0])
        self.assertEqual(updates[self.objects[0].identifier]['scale'], [-4, 3, .5])
        np.testing.assert_allclose(updates[self.objects[0].identifier]['position'], [-4, 0, 0])
        uniform, point = self.drag('scale', 'free', pivot='active')
        updates = uniform.updates(point + [120, 0])
        np.testing.assert_allclose(updates[self.objects[1].identifier]['position'], [2, 0, 0])
        np.testing.assert_allclose(updates[self.objects[0].identifier]['position'], [-6, 0, 0])
        np.testing.assert_allclose(updates[self.objects[0].identifier]['scale'], [-4, 6, 1])
        update = uniform.updates(point + [-1000, 0])[self.objects[0].identifier]
        self.assertLess(update['scale'][0], 0)
        self.assertTrue(all(value != 0 for value in update['scale']))

    def test_behind_camera_has_no_gizmo_or_selection(self):
        for obj in self.objects:
            obj.position[2] = 20
        self.assertEqual(Gizmo(self.objects, 'move', self.projection).handles, [])
        self.assertEqual(self.box((0, 0, 800, 600)), [])

    def box(self, rect):
        mesh = PickMesh(loadObjFlatShaded(ROOT / 'Assets/cube.simuOPart'))
        return box_candidates([{'SceneObject': obj, 'pick_mesh': mesh} for obj in self.objects], self.projection, rect)

    def test_box_intersects_mesh_surfaces_and_excludes_hidden_locked(self):
        self.assertEqual(self.box((0, 0, 400, 600)), [self.objects[0].identifier])
        self.objects[0].editor_visible = False
        self.objects[1].selection_locked = True
        self.assertEqual(self.box((0, 0, 800, 600)), [])

    def test_box_clips_meshes_crossing_near_plane(self):
        self.objects[0].position = [0, 0, 9.9]
        self.objects[1].position = [0, 0, 20]
        self.assertEqual(self.box((380, 280, 420, 320)), [self.objects[0].identifier])
