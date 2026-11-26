"""Mesh-independent footprints and consistent quadratic surface loads."""
from dataclasses import replace
from pathlib import Path
import tempfile
import unittest
import numpy as np
import manifold3d as m

from tests.structural_helpers import native_box, end_selection, kernel_obj
from tests.integration.test_point_loads import anchor
from simuo.structural.geometry import load_geometry
from simuo.structural.models import AnalysisSetup, Material, MeshSettings, AreaLoad, SurfaceLoad
from simuo.structural.meshing import generate_mesh
from simuo.structural.solver import solve_analysis, make_basis
from simuo.structural.load_regions import area_region, assemble_area_force
from simuo.structural.persistence import save_analysis, load_analysis


class AreaLoadTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temp = tempfile.TemporaryDirectory()
        cls.geometry = load_geometry(native_box(cls.temp.name, (.2, .2, .2)))
        cls.mesh = generate_mesh(cls.geometry, MeshSettings(.07))
        cls.tip = end_selection(cls.geometry, 0, .1)
        cls.clamp = end_selection(cls.geometry, 0, -.1)

    @classmethod
    def tearDownClass(cls):
        cls.temp.cleanup()

    def load(self, point=(.1, .013, .027), radius=.035, kind="force", value=(20., -100., 30.)):
        # Edge/corner anchors can belong to multiple faces; select the +X face.
        for index in self.tip:
            triangle = self.geometry.points[self.geometry.triangles[index]]
            uv = np.linalg.lstsq((triangle[1:]-triangle[0]).T, np.asarray(point)-triangle[0], rcond=None)[0]
            bary = np.r_[1-uv.sum(), uv]
            if bary.min() >= -1e-10:
                bary = np.maximum(bary, 0); bary /= bary.sum()
                return AreaLoad(self.tip, index, tuple(bary), radius, kind, value)
        raise AssertionError("No anchor on the selected face")

    def setup_for(self, mesh, loads):
        g = self.geometry
        return AnalysisSetup(g.path, g.fingerprint, "m", Material(2e11, .3), mesh.settings,
                             (self.clamp,), area_loads=tuple(loads))

    def test_small_footprint_force_and_moment_on_coarse_and_fine_mesh(self):
        load = self.load(radius=.007)
        expected_center = np.array([.1, .013, .027])
        for mesh in (self.mesh, generate_mesh(self.geometry, MeshSettings(.04))):
            with self.subTest(size=mesh.settings.target_size):
                basis = make_basis(mesh)
                forces = assemble_area_force(basis, mesh, load).reshape(-1, 3)
                np.testing.assert_allclose(forces.sum(axis=0), load.value, atol=1e-10)
                np.testing.assert_allclose(np.cross(basis.doflocs.T[::3], forces).sum(axis=0), np.cross(expected_center, load.value), atol=1e-10)
                result = solve_analysis(mesh, self.setup_for(mesh, (load,)))
                np.testing.assert_allclose(result.applied_force, load.value, atol=1e-9)
                np.testing.assert_allclose(result.applied_moment, np.cross(expected_center-mesh.points.mean(axis=0), load.value), atol=1e-9)
                self.assertLess(max(result.force_error, result.moment_error, result.residual_error), 1e-8)

    def test_edge_corner_clipping_and_pressure_resultant(self):
        for point, fraction in (((.1, 0, 0), 1), ((.1, .1, 0), .5), ((.1, .1, .1), .25)):
            load = self.load(point, .04, "pressure", (12000.,))
            region = area_region(self.geometry.points, self.geometry.triangles, load)
            polygon_area = 128*np.sin(2*np.pi/256)*load.radius**2
            self.assertAlmostEqual(region.area, polygon_area*fraction, places=12)
            result = solve_analysis(self.mesh, self.setup_for(self.mesh, (load,)))
            force = -12000*region.area*np.array([1., 0., 0.])
            np.testing.assert_allclose(result.applied_force, force, atol=1e-9)
            np.testing.assert_allclose(result.applied_moment, np.cross(region.centroid-self.mesh.points.mean(axis=0), force), atol=1e-9)

    def test_superposition_resize_and_saved_snapshot(self):
        original = self.load()
        second = self.load(radius=.02, value=(0., 10., 0.))
        resized = replace(original, radius=.05, barycentric=(.2, .3, .5))
        setup = replace(self.setup_for(self.mesh, (resized, second)), loads=(SurfaceLoad(self.tip, value=(5., 0., 0.)),))
        result = solve_analysis(self.mesh, setup)
        np.testing.assert_allclose(result.applied_force, np.array(resized.value)+second.value+[5, 0, 0], atol=1e-9)
        path = Path(self.temp.name)/"area-design.simuO"
        setup = replace(setup, material=replace(setup.material, yield_strength=240e6, ultimate_tensile_strength=260e6))
        save_analysis(path, setup)
        self.assertEqual(load_analysis(path), setup)
        self.assertFalse(self.mesh.point_nodes)

    def test_hole_clipping_and_curved_surface_rejection(self):
        # A square through-hole remains empty even when the disk covers it.
        solid = m.Manifold.cube((1, 1, .2), True)-m.Manifold.cube((.2, .2, 1), True)
        g = load_geometry(kernel_obj(Path(self.temp.name)/"hole.obj", solid))
        top = end_selection(g, 2, .1)
        p = anchor(g, (.25, 0., .1))
        load = AreaLoad(top, p.source_triangle, p.barycentric, 2.)
        region = area_region(g.points, g.triangles, load)
        self.assertAlmostEqual(region.area, .96, places=10)
        np.testing.assert_allclose(region.centroid, [0, 0, .1], atol=1e-12)
        mesh = generate_mesh(g, MeshSettings(.23))
        pressure = replace(load, kind="pressure", value=(1000.,))
        setup = AnalysisSetup(g.path, g.fingerprint, "m", Material(2e11, .3), mesh.settings,
                              (end_selection(g, 2, -.1),), area_loads=(pressure,))
        result = solve_analysis(mesh, setup)
        np.testing.assert_allclose(result.applied_force, [0, 0, -960], atol=1e-9)
        np.testing.assert_allclose(result.applied_moment, np.cross(region.centroid-mesh.points.mean(axis=0), [0, 0, -960]), atol=1e-9)
        curved = load_geometry(kernel_obj(Path(self.temp.name)/"cylinder.obj", m.Manifold.cylinder(1., .5, .5, 16, True)))
        side = tuple(i for i, triangle in enumerate(curved.points[curved.triangles]) if np.ptp(triangle[:, 2]) > .1)
        bad = AreaLoad(side, side[0], (1/3, 1/3, 1/3), .1)
        with self.assertRaisesRegex(ValueError, "planar face"):
            area_region(curved.points, curved.triangles, bad)

    def test_invalid_radius_and_identity(self):
        for radius in (0, -1, True, float("nan"), float("inf")):
            with self.assertRaises(ValueError):
                self.load(radius=radius)
        with self.assertRaisesRegex(ValueError, "unique"):
            load = self.load()
            self.setup_for(self.mesh, (load, load))
