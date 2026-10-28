import sys
import tempfile
import unittest
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
from ray import Ray
from scene import SceneObject


class RayCollisionTests(unittest.TestCase):
    def test_stress_grid_hits_and_indices(self):
        path = ROOT / "Assets/stress_test.simuOPart"
        vertex_count = 0
        for line in path.read_text().splitlines():
            fields = line.split()
            if not fields:
                continue
            if fields[0] == "v":
                vertex_count += 1
            elif fields[0] in ("f", "l"):
                for token in fields[1:]:
                    index = int(token.split("/")[0])
                    self.assertGreaterEqual(index, 1)
                    self.assertLessEqual(index, vertex_count)
        # Cover both boundary cells as well as the interior of the grid.
        for x, y in ((-2.49, -2.49), (0.01, 0.01), (2.46, 2.46)):
            with self.subTest(x=x, y=y):
                hit = Ray([x, y, 5], [0, 0, -1]).checkCollisions(path)
                self.assertIsNotNone(hit)
                np.testing.assert_allclose(hit["point"], [x, y, 2], atol=1e-6)
                self.assertAlmostEqual(hit["distance"], 3)

    def test_repository_formats(self):
        for path in (ROOT / "cube.obj", ROOT / "Assets/cube.simuOPart"):
            with self.subTest(path=path):
                hit = Ray([0, 0.5, -3], [0, 0, 2]).checkCollisions(path)
                self.assertIsNotNone(hit)
                np.testing.assert_allclose(hit["point"], [0, 0.5, -3 + 2 * hit["t"]])

    def test_transforms_nearest_and_inside(self):
        near = SceneObject("near", ROOT / "Assets/cube.simuOPart")
        near.position = [0, 0, 5]
        near.rotation = [0, 90, 0]
        near.scale = [2, 1, 3]
        far = SceneObject("far", near.meshPath)
        far.position = [0, 0, 12]
        ray = Ray([0, 0, 0], [0, 0, 2])
        hit = ray.checkCollisions([far, near])
        self.assertIs(hit["object"], near)
        self.assertAlmostEqual(hit["distance"], 3, places=5)
        np.testing.assert_allclose(hit["point"], ray.at(hit["t"]))
        hit = Ray([0, 0, 5], [0, 0, 1]).checkCollisions(near)
        self.assertAlmostEqual(hit["distance"], 2, places=5)

    def test_misses(self):
        path = ROOT / "Assets/cube.simuOPart"
        for origin, direction in (([5, 0, -3], [0, 0, 1]),
                                  ([0, 0, -3], [0, 0, -1]),
                                  ([0, 0, -3], [1, 0, 0])):
            self.assertIsNone(Ray(origin, direction).checkCollisions(path))
        self.assertIsNone(Ray([0, 0, 0], [0, 0, 1]).checkCollisions([]))
        with self.assertRaises(ValueError):
            Ray([0, 0, 0], [0, 0, 0]).checkCollisions(path)

    def test_polygon_negative_indices_edges_and_degenerate_faces(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "quad.simuOPart"
            path.write_text("v -1 -1 0\nv 1 -1 0\nv 1 1 0\nv -1 1 0\n"
                            "f 1 1 1\nf -4/1/1 -3/2/1 -2/3/1 -1/4/1 # quad\n")
            for x, y in ((0, 0), (1, 1), (-0.5, 0.5)):
                for z in (-2, 2):
                    hit = Ray([x, y, z], [0, 0, -z]).checkCollisions(path)
                    self.assertAlmostEqual(hit["distance"], 2)
            path.write_text("# empty mesh\n")
            self.assertIsNone(Ray([0, 0, -2], [0, 0, 1]).checkCollisions(path))


if __name__ == "__main__":
    unittest.main()
