"""Movement-tool integration with loaded parts, scene saving, and deletion."""
from types import SimpleNamespace
import unittest
from unittest.mock import Mock

import glm
import numpy as np
from PySide6.QtCore import QPointF

from tests import ROOT
from simuo.physics.viewport.mover import Mover
from simuo.physics.viewport.renderer import Camera, OpenGLViewport
from simuo.project.scene import Scene, SceneObject


class MoverTests(unittest.TestCase):
    def object(self):
        obj = SceneObject(meshPath=ROOT / "Assets/aluminum_cube.simuOPart")
        obj.position = [0, 0, 0]
        return obj

    def test_bounds_and_arrows_exist_before_gpu_upload(self):
        obj = self.object()
        mover = Mover(obj)
        np.testing.assert_allclose(mover.world_center(), [0, 0, 0])
        np.testing.assert_allclose(mover.half_extent(), [.1, .1, .1])
        start, end = mover.axis_endpoints(0)
        obj.position = [2, 3, 4]
        moved_start, moved_end = mover.axis_endpoints(0)
        np.testing.assert_allclose(moved_start - start, [2, 3, 4], atol=1e-6)
        np.testing.assert_allclose(moved_end - end, [2, 3, 4], atol=1e-6)
        data, segments = mover.build_render_data()
        self.assertEqual(data.dtype, np.float32)
        self.assertEqual(len(segments), 3)
        self.assertEqual(sum(s[3] for s in segments), data.size // 3)

    def test_drag_marks_scene_dirty_and_deletion_clears_selection(self):
        obj = self.object()
        scene = Scene()
        scene.addObject(obj)
        camera = Camera()
        camera.position = glm.vec3(0, 0, 5)
        mover = Mover(obj)
        mover.begin_drag("x", camera.position, camera.front)
        viewport = SimpleNamespace(
            mover=mover, selectedObject=obj, scene=scene, camera=camera,
            width=lambda: 800, height=lambda: 600, update=Mock(), renderObjects=[],
        )
        event = SimpleNamespace(position=lambda: QPointF(450, 300))
        OpenGLViewport.mouseMoveEvent(viewport, event)
        self.assertGreater(obj.position[0], 0)
        np.testing.assert_allclose(obj.position[1:], [0, 0])
        self.assertTrue(scene.dirty)
        viewport.update.assert_called()
        OpenGLViewport.removeObject(viewport, obj)
        self.assertIsNone(viewport.selectedObject)
        self.assertIsNone(viewport.mover)


if __name__ == "__main__":
    unittest.main()
