"""Exact boundary point forces, conforming meshes and nodal load conservation."""
from dataclasses import replace
from pathlib import Path
import tempfile
import unittest
import numpy as np
from skfem import asm
from skfem.models.elasticity import linear_elasticity

from tests.structural_helpers import native_box, end_selection
from simuo.structural.geometry import load_geometry
from simuo.structural.models import *
from simuo.structural.meshing import generate_mesh, validate_mesh
from simuo.structural.solver import solve_analysis, make_basis


def anchor(geometry, point, force=(0., -100., 0.)):
    point = np.asarray(point)
    for i, triangle in enumerate(geometry.points[geometry.triangles]):
        edges = (triangle[1:]-triangle[0]).T
        uv = np.linalg.lstsq(edges, point-triangle[0], rcond=None)[0]
        bary = np.r_[1-uv.sum(), uv]
        if bary.min() > -1e-10 and np.linalg.norm(triangle[0]+edges@uv-point) < 1e-10:
            bary = np.maximum(bary, 0); bary /= bary.sum()
            return PointLoad(i, tuple(bary), force)
    raise AssertionError("Test point is not on the solid")


class PointLoadTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.geometry = load_geometry(native_box(self.temp.name, (.2, .2, .2)))

    def setup_for(self, mesh, loads):
        g = self.geometry
        return AnalysisSetup(g.path, g.fingerprint, "m", Material(2e11, .3), mesh.settings,
                             (end_selection(g, 0, -.1),), point_loads=tuple(loads))

    def test_face_edge_corner_and_coincident_forces(self):
        g = self.geometry
        for point in ((.1, .013, .027), (.1, .1, .027), (.1, .1, .1)):
            with self.subTest(point=point):
                load = anchor(g, point)
                second = replace(load, identifier=load.identifier+"2", force=(0., -25., 0.))
                mesh = generate_mesh(g, MeshSettings(.07), (load, second))
                np.testing.assert_allclose(mesh.points[mesh.point_nodes[load.identifier]], point, atol=1e-12)
                self.assertEqual(mesh.point_nodes[load.identifier], mesh.point_nodes[second.identifier])
                self.assertTrue(np.all(validate_mesh(mesh, g) > 0))
                setup = self.setup_for(mesh, (load, second))
                result = solve_analysis(mesh, setup)
                np.testing.assert_allclose(result.applied_force, (0, -125, 0), atol=1e-9)
                np.testing.assert_allclose(result.reactions.sum(axis=0), (0, 125, 0), atol=1e-8)
                self.assertLess(max(result.residual_error, result.force_error, result.moment_error), 1e-8)
                basis = make_basis(mesh)
                stiffness = asm(linear_elasticity(*setup.material.lame), basis)
                actual = stiffness@result.solution-result.reactions.ravel()
                expected = np.zeros_like(actual)
                expected[basis.nodal_dofs[:, mesh.point_nodes[load.identifier]]] = (0, -125, 0)
                np.testing.assert_allclose(actual, expected, atol=1e-8)

    def test_refinement_retains_anchor_and_reposition_requires_mesh(self):
        load = anchor(self.geometry, (.1, .013, .027))
        for size in (.08, .04):
            mesh = generate_mesh(self.geometry, MeshSettings(size), (load,))
            np.testing.assert_allclose(mesh.points[mesh.point_nodes[load.identifier]], (.1, .013, .027), atol=1e-12)
        moved = replace(load, barycentric=(.1, .1, .8))
        with self.assertRaisesRegex(ValueError, "locations changed"):
            solve_analysis(mesh, self.setup_for(mesh, (moved,)))
        changed_force = replace(load, force=(0, -200, 0))
        result = solve_analysis(mesh, self.setup_for(mesh, (changed_force,)))
        np.testing.assert_allclose(result.applied_force, (0, -200, 0), atol=1e-8)

    def test_point_loaded_cantilever_displacement_and_interior_moments(self):
        folder = Path(self.temp.name)/"cantilever"
        folder.mkdir()
        geometry = load_geometry(native_box(folder))
        clamp, tip = [end_selection(geometry, 0, x) for x in (-.5, .5)]
        load = anchor(geometry, (.5, 0., 0.), (0., -1000., 0.))
        mesh = generate_mesh(geometry, MeshSettings(.03), (load,))
        setup = AnalysisSetup(geometry.path, geometry.fingerprint, "m", Material(2e11, .3), mesh.settings,
                              (clamp,), beam=BeamConfiguration(clamp, tip), point_loads=(load,))
        result = solve_analysis(mesh, setup)
        expected_displacement = -1000/(3*2e11*(.1**4/12))
        actual = result.displacement[mesh.point_nodes[load.identifier], 1]
        self.assertLess(abs(actual/expected_displacement-1), .05)
        self.assertEqual(result.beam_message, "")
        expected_moments = -1000*(1-result.beam_stations)
        np.testing.assert_allclose(result.beam_moments[9:80, 1], expected_moments[9:80], rtol=.05)
        np.testing.assert_allclose(result.root_reaction, [0, 1000, 0, 0, 0, 1000], atol=1e-6)

    def test_invalid_point_data(self):
        for triangle, bary, force in ((-1, (1, 0, 0), (1, 2, 3)), (0, (-.1, .5, .6), (1, 2, 3)), (0, (.2, .3, .6), (1, 2, 3)), (0, (1, 0, 0), (float("nan"), 0, 0))):
            with self.assertRaises(ValueError):
                PointLoad(triangle, bary, force)
