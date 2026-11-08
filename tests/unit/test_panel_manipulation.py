"""Projection and gizmo math independent of a graphics driver."""

import unittest


import glm

from tests import ROOT
from simuo.rendering.camera import Camera
from simuo.rendering.manipulation import MoveDrag, MoveGizmo, Projection, box_candidates
from simuo.parts.part_assets import loadObjFlatShaded
from simuo.rendering.picking import PickMesh
from simuo.project.scene import SceneObject


class Manipulation(unittest.TestCase):
    def setUp(self):
        self.camera = Camera()
        self.camera.position = glm.vec3(0, 0, 10)
        self.projection = Projection(self.camera, 800, 600)
        self.objects = [SceneObject('A'), SceneObject('B')]
        self.objects[0].position = [-2, 0, 0]
        self.objects[1].position = [2, 0, 0]

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

    def test_behind_camera_has_no_gizmo_or_selection(self):
        for obj in self.objects:
            obj.position[2] = 20
        self.assertEqual(MoveGizmo(self.objects[0], self.projection).handles, [])
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
