"""Projection and gizmo math independent of a graphics driver."""

import math
import unittest


import glm
import numpy as np

from tests import ROOT
from simuo.physics.viewport.mover import Mover, object_center
from simuo.rendering.camera import Camera
from simuo.rendering.manipulation import (
    MoveDrag, MoveGizmo, Projection, RotateDrag, RotateGizmo, ScaleDrag, ScaleGizmo,
    box_candidates, decompose_euler_xyz,
)
from simuo.parts.part_assets import loadObjFlatShaded
from simuo.rendering.picking import PickMesh, rotation_matrix
from simuo.project.scene import SceneObject


class Manipulation(unittest.TestCase):
    def setUp(self):
        self.camera = Camera()
        self.camera.position = glm.vec3(0, 0, 10)
        self.projection = Projection(self.camera, 800, 600)
        self.objects = [SceneObject('A'), SceneObject('B')]
        self.objects[0].position = [-2, 0, 0]
        self.objects[1].position = [2, 0, 0]
        for obj in self.objects:
            obj.localMin = np.array([-1.0, -1.0, -1.0])
            obj.localMax = np.array([1.0, 1.0, 1.0])

    def test_move_handle_previews_world_axis_without_mutating_object(self):
        obj = self.objects[0]
        obj.rotation = [0, 0, 90]
        gizmo = MoveGizmo(obj, self.projection)
        handle = next(handle for handle in gizmo.handles if handle.key == 'x')
        point = handle.points[-1]
        self.assertIs(gizmo.hit(point), handle)
        drag = MoveDrag(gizmo, handle, tuple(point))

        update = drag.updates(point + [80, 40])[obj.identifier]['position']

        self.assertGreater(update[0], -2)
        self.assertEqual(update[1:], [0, 0])
        self.assertEqual(obj.position, [-2, 0, 0])

    def test_scale_handle_resizes_only_its_own_axis_without_mutating_object(self):
        obj = self.objects[0]
        obj.rotation = [0, 0, 0]
        gizmo = ScaleGizmo(obj, self.projection)
        handle = next(h for h in gizmo.handles if h.key == 'x')
        point = handle.points[-1]
        self.assertIs(gizmo.hit(point), handle)
        drag = ScaleDrag(gizmo, handle, tuple(point))

        grown = drag.updates(point + [80, 0])[obj.identifier]['scale']
        self.assertGreater(grown[0], 1.0)
        self.assertEqual(grown[1:], [1.0, 1.0])

        shrunk = drag.updates(point - [80, 0])[obj.identifier]['scale']
        self.assertLess(shrunk[0], 1.0)
        self.assertEqual(shrunk[1:], [1.0, 1.0])

        # A huge inward drag clamps to a small positive scale instead of
        # going to zero or flipping negative.
        clamped = drag.updates(point - [10000, 0])[obj.identifier]['scale']
        self.assertEqual(clamped[0], ScaleDrag.MIN_SCALE)

        self.assertEqual(obj.scale, [1.0, 1.0, 1.0])

    def test_behind_camera_has_no_gizmo_or_selection(self):
        for obj in self.objects:
            obj.position[2] = 20
        self.assertEqual(MoveGizmo(self.objects[0], self.projection).handles, [])
        self.assertEqual(RotateGizmo(self.objects[0], self.projection).handles, [])
        self.assertEqual(self.box((0, 0, 800, 600)), [])

    def test_rotate_gizmo_hides_rings_seen_edge_on(self):
        obj = self.objects[0]
        obj.position = [0, 0, 0]
        obj.rotation = [0, 0, 0]
        obj.localMin, obj.localMax = np.array([-1., -1., -1.]), np.array([1., 1., 1.])
        # Camera looks straight down world Z at an unrotated box, so the x
        # ring (spans Y/Z) and y ring (spans X/Z) both have Z - the camera's
        # own view axis - as one of their two in-plane directions, which
        # projects to (near) zero screen-space length: edge-on.
        self.assertEqual({h.key for h in RotateGizmo(obj, self.projection).handles}, {'z'})

    def test_rotate_gizmo_rings_are_centered_on_the_object(self):
        obj = self.objects[0]
        obj.position = [0, 0, 0]
        obj.rotation = [20, 35, 50]
        obj.localMin, obj.localMax = np.array([-1., -1., -1.]), np.array([1., 1., 1.])
        gizmo = RotateGizmo(obj, self.projection)
        self.assertEqual({h.key for h in gizmo.handles}, {'x', 'y', 'z'})
        center2d = self.projection.point(object_center(obj))[:2]
        for handle in gizmo.handles:
            np.testing.assert_allclose(handle.center2d, center2d, atol=1e-6)

    def test_rotate_gizmo_scales_with_box_size_not_camera_distance(self):
        obj = self.objects[0]
        obj.position = [0, 0, 0]
        obj.rotation = [20, 35, 50]
        obj.localMin, obj.localMax = np.array([-1., -1., -1.]), np.array([1., 1., 1.])

        def ring_spans(projection):
            return {h.key: np.linalg.norm(h.right2d) + np.linalg.norm(h.up2d)
                    for h in RotateGizmo(obj, projection).handles}

        at_default_distance = ring_spans(self.projection)
        obj.localMin, obj.localMax = np.array([-2., -2., -2.]), np.array([2., 2., 2.])
        bigger_box = ring_spans(self.projection)
        for key in at_default_distance:
            self.assertGreater(bigger_box[key], at_default_distance[key])

        obj.localMin, obj.localMax = np.array([-1., -1., -1.]), np.array([1., 1., 1.])
        far_camera = Camera()
        far_camera.position = glm.vec3(0, 0, 30)
        farther_away = ring_spans(Projection(far_camera, 800, 600))
        for key in at_default_distance:
            # Same box, farther camera: shrinks like normal perspective now,
            # instead of the old trick that kept it a constant screen size.
            self.assertLess(farther_away[key], at_default_distance[key])

    def test_rotate_gizmo_rings_share_the_smallest_axis_radius(self):
        obj = self.objects[0]
        obj.position = [0, 0, 0]
        obj.rotation = [20, 35, 50]
        # A non-cubic box: each axis's own cross-section would circumscribe a
        # different-sized ring if sized independently.
        obj.localMin, obj.localMax = np.array([-1., -3., -0.5]), np.array([1., 3., 0.5])
        half_size = [(obj.localMax[axis] - obj.localMin[axis]) * 0.5 for axis in range(3)]
        expected_radius = min(math.hypot(half_size[(i + 1) % 3], half_size[(i + 2) % 3]) for i in range(3)) * 1.15
        origin = object_center(obj)
        columns = [glm.normalize(glm.vec3(rotation_matrix(obj.rotation)[i])) for i in range(3)]

        gizmo = RotateGizmo(obj, self.projection)
        self.assertEqual({h.key for h in gizmo.handles}, {'x', 'y', 'z'})
        for i, handle in enumerate(sorted(gizmo.handles, key=lambda h: 'xyz'.index(h.key))):
            right = columns[(i + 1) % 3]
            expected_right2d = self.projection.point(origin + right * expected_radius)[:2] - handle.center2d
            np.testing.assert_allclose(handle.right2d, expected_right2d, atol=1e-5)

    def test_rotate_handle_spins_about_its_own_local_axis_without_mutating_object(self):
        obj = self.objects[0]
        obj.position = [0, 0, 0]
        obj.rotation = [20, 35, 50]
        gizmo = RotateGizmo(obj, self.projection)
        handle = next(h for h in gizmo.handles if h.key == 'x')
        # An eighth-turn point, not a quarter-turn - at some angles a ring
        # point coincides with another axis's ring at a different angle,
        # which would make gizmo.hit() ambiguous between the two.
        start = handle.points[len(handle.points) // 8]
        self.assertIs(gizmo.hit(start), handle)
        drag = RotateDrag(gizmo, handle, tuple(start))

        # A point a quarter-turn around the ring - any point at a different
        # angle works for the drag math.
        end = handle.center2d + handle.right2d * math.cos(math.pi / 2) + handle.up2d * math.sin(math.pi / 2)
        update = drag.updates(tuple(end))
        new_rotation = update[obj.identifier]['rotation']

        before_axis = glm.normalize(glm.vec3(rotation_matrix(obj.rotation)[0]))
        after_axis = glm.normalize(glm.vec3(rotation_matrix(new_rotation)[0]))
        for before, after in zip(before_axis, after_axis):
            self.assertAlmostEqual(before, after, places=5)
        self.assertNotEqual(new_rotation, obj.rotation)
        self.assertEqual(obj.rotation, [20, 35, 50])

    def test_rotate_drag_keeps_the_boxs_true_center_fixed_in_world_space(self):
        obj = self.objects[0]
        obj.position = [1, 2, 3]
        obj.rotation = [10, 20, 30]
        # Off-center box, like a mesh whose own origin sits at its base
        # rather than its middle - previously, only Euler angles changed, so
        # the object visibly spun about that off-center local origin instead
        # of the box's true center the gizmo is drawn around.
        obj.localMin, obj.localMax = np.array([-1., 0., -1.]), np.array([1., 4., 1.])
        pivot = np.array(object_center(obj))

        gizmo = RotateGizmo(obj, self.projection)
        handle = next(h for h in gizmo.handles if h.key == 'y')
        drag = RotateDrag(gizmo, handle, tuple(handle.points[0]))
        end = handle.center2d + handle.right2d * math.cos(1.3) + handle.up2d * math.sin(1.3)
        update = drag.updates(tuple(end))[obj.identifier]

        after = SceneObject('probe')
        after.position, after.rotation = update['position'], update['rotation']
        after.localMin, after.localMax = obj.localMin, obj.localMax
        np.testing.assert_allclose(np.array(object_center(after)), pivot, atol=1e-5)
        # The object itself stays untouched until the drag is committed.
        self.assertEqual(obj.position, [1, 2, 3])
        self.assertEqual(obj.rotation, [10, 20, 30])

    def test_rotate_gizmo_ignores_move_origin_override(self):
        obj = self.objects[0]
        obj.position = [0, 0, 0]
        obj.rotation = [20, 35, 50]
        # An off-center box, so the move gizmo's user-chosen origin corner
        # sits at a different world point than the box's true center.
        obj.localMin = np.array([-0.1, -0.1, -0.1])
        obj.localMax = np.array([0.3, 0.1, 0.1])

        without_override = {h.key: h.center2d.copy() for h in RotateGizmo(obj, self.projection).handles}
        obj.origin_corner = (1, 1, 1)
        with_override = {h.key: h.center2d for h in RotateGizmo(obj, self.projection).handles}

        # The move gizmo's own anchor does move to the chosen corner...
        self.assertFalse(np.allclose(Mover(obj).world_center(), object_center(obj)))
        # ...but the rotate gizmo is built straight from object_center() and
        # never even looks at origin_corner, so it's completely unaffected.
        self.assertEqual(set(without_override), set(with_override))
        for key in without_override:
            np.testing.assert_allclose(without_override[key], with_override[key])

    def test_decompose_euler_xyz_round_trips_including_near_gimbal_lock(self):
        # Near pitch=90 (gimbal lock), float32 rotation matrices lose a little
        # precision, so that case gets a looser tolerance than the others.
        for angles, places in (([20, 35, 50], 3), ([0, 0, 0], 3), ([10, -20, 170], 3), ([5, 89.95, 30], 1)):
            matrix = rotation_matrix(angles)
            roundtrip = decompose_euler_xyz(matrix, angles)
            for expected, actual in zip(angles, roundtrip):
                self.assertAlmostEqual(expected, actual, places=places)

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
