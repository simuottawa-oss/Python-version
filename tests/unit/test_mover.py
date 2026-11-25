"""Movement-tool integration with loaded parts, scene saving, and deletion."""
import unittest

import numpy as np

from tests import ROOT
from simuo.physics.viewport.mover import Mover, world_corners
from simuo.project.scene import SceneObject


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

    def test_world_corners_and_gizmo_anchor_follow_rotation(self):
        obj = self.object()
        obj.position = [1, 2, 3]
        obj.rotation = [0, 0, 90]
        # Rz(90) maps the local max corner (.1,.1,.1) to (-.1,.1,.1), so it
        # should land at (0.9, 2.1, 3.1) in world space, not the unrotated
        # (1.1, 2.1, 3.1) a stale, rotation-ignoring bounding box would give.
        corners = {signs: tuple(point) for signs, point in world_corners(obj)}
        np.testing.assert_allclose(corners[(1, 1, 1)], [0.9, 2.1, 3.1], atol=1e-6)

        mover = Mover(obj)
        obj.origin_corner = (1, 1, 1)
        np.testing.assert_allclose(mover.world_center(), [0.9, 2.1, 3.1], atol=1e-6)
        obj.origin_corner = None
        np.testing.assert_allclose(mover.world_center(), [1, 2, 3], atol=1e-6)


if __name__ == "__main__":
    unittest.main()
