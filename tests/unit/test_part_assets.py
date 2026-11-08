"""Production asset loading without Qt or a display."""
import json
from pathlib import Path
import tempfile
import unittest

import numpy as np

from tests import ROOT
from simuo.parts.part_assets import load_asset
from simuo.project.scene import SceneObject


class AssetTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.path = Path(self.temp.name) / "part.simuOPart"
        self.data = json.loads((ROOT / "Assets/aluminum_cube.simuOPart").read_text())

    def write(self):
        self.path.write_text(json.dumps(self.data), encoding="utf-8")
        return self.path

    def test_json_geometry_normals_winding_and_color(self):
        asset = load_asset(self.write())
        vertices = asset.vertices.reshape(-1, 6)
        self.assertEqual(vertices.shape, (36,6))
        self.assertEqual(vertices.dtype, np.float32)
        np.testing.assert_allclose(np.ptp(vertices[:,:3],axis=0), [0.2]*3)
        for triangle in vertices.reshape(-1,3,6):
            normal = np.cross(triangle[1,:3]-triangle[0,:3], triangle[2,:3]-triangle[0,:3])
            self.assertGreater(np.dot(normal,triangle[0,3:]),0)
        np.testing.assert_allclose(np.linalg.norm(vertices[:,3:],axis=1),1)
        np.testing.assert_allclose(asset.color, np.array([0x47,0xb9,0xd5])/255)
        self.assertAlmostEqual(asset.part.mass,21.6)
        np.testing.assert_allclose(asset.part.inertia,[0.144]*3)

    def test_part_initial_state_and_properties_reach_scene(self):
        obj = SceneObject(meshPath=self.write())
        self.assertEqual(obj.name,"Aluminum cube")
        self.assertEqual(obj.position,[0,1.1,0])
        self.assertEqual(obj.velocity,[0.35,0,0.15])
        self.assertEqual(obj.part.properties["demo:temperature_K"],293.15)
        renamed = SceneObject(name="Instance name",meshPath=self.path)
        self.assertEqual(renamed.name,"Instance name")

    def test_legacy_cube_and_existing_teapot(self):
        for name, count in [("cube",36),("teapot",18960)]:
            with self.subTest(name=name):
                asset = load_asset(ROOT / f"Assets/{name}.simuOPart")
                self.assertIsNone(asset.part)
                self.assertEqual(asset.vertices.size // 6,count)
                self.assertTrue(np.isfinite(asset.vertices).all())
                self.assertEqual(asset.color,(0.72,0.76,0.82))

    def test_invalid_json_never_becomes_empty_obj(self):
        for content in ['{"format":', '[1,2,3]', '{"format":"unknown"}', 'not a mesh']:
            with self.subTest(content=content):
                self.path.write_text(content)
                with self.assertRaises(ValueError):
                    load_asset(self.path)

    def test_unsupported_version_or_shape_rejected(self):
        self.data["version"] = 2
        with self.assertRaises(ValueError):
            load_asset(self.write())
        self.data["version"] = 1
        self.data["geometry"]["type"] = "sphere"
        with self.assertRaises(ValueError):
            load_asset(self.write())

    def test_part_format_identifier(self):
        self.assertEqual(self.data["format"], ".simuOPart")
        self.assertEqual(load_asset(self.write()).part.id, self.data["id"])
        self.data["format"] = "simuo.part"
        with self.assertRaisesRegex(ValueError, "Expected \\.simuOPart version 1"):
            load_asset(self.write())

    def test_bom_and_leading_whitespace_dispatch(self):
        self.path.write_text("\ufeff \n" + json.dumps(self.data), encoding="utf-8")
        self.assertEqual(load_asset(self.path).part.id,"demo.aluminum-cube")

    def test_scene_is_not_restricted_to_prototype_floor(self):
        self.data["initial_state"]["position"] = [0,-1,0]
        self.assertEqual(load_asset(self.write()).part.position,(0,-1,0))

    def test_extreme_numbers_fail_cleanly(self):
        for mutate in [lambda d: d["material"].update(density=10**400),
                       lambda d: d["geometry"].update(size=[1e200,1,1e-200]),
                       lambda d: d["initial_state"].update(position=[1e16,1.1,0]),
                       lambda d: (d["geometry"].update(size=[1e-100]*3),
                                  d["physics"].update(mass_source="explicit",mass=1))]:
            with self.subTest(mutate=mutate):
                self.data = json.loads((ROOT / "Assets/aluminum_cube.simuOPart").read_text())
                mutate(self.data)
                with self.assertRaises(ValueError):
                    load_asset(self.write())

    def test_legacy_negative_indices_and_zero_index_error(self):
        self.path.write_text("v 0 0 0\nv 1 0 0\nv 0 1 0\nf -3 -2 -1\n")
        self.assertEqual(load_asset(self.path).vertices.size,18)
        self.path.write_text("v 0 0 0\nv 1 0 0\nv 0 1 0\nf 0 1 2\n")
        with self.assertRaisesRegex(ValueError,"indices cannot be zero"):
            load_asset(self.path)


if __name__ == "__main__":
    unittest.main()
