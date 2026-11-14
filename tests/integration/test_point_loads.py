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
from simuo.structural.solver import solve_analysis, make_basis, boundary_facets
from simuo.structural.constraints import build_constraints
from simuo.structural.meshing import bind_point_targets


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
        for target_size in (.05, .03):
            with self.subTest(target_size=target_size):
                mesh = generate_mesh(geometry, MeshSettings(target_size), (load,))
                setup = AnalysisSetup(geometry.path, geometry.fingerprint, "m", Material(2e11, .3), mesh.settings,
                                      (clamp,), beam=BeamConfiguration(clamp, tip), point_loads=(load,))
                result = solve_analysis(mesh, setup)
                expected_displacement = -1000/(3*2e11*(.1**4/12))
                actual = result.displacement[mesh.point_nodes[load.identifier], 1]
                self.assertLess(abs(actual/expected_displacement-1), .05)
                coordinates = make_basis(mesh).global_coordinates().transpose(1, 2, 0)
                x, y, z = coordinates.transpose(2, 0, 1)
                interior = (abs(x) < .3) & (abs(y) > .025) & (abs(z) < .03)
                expected_stress = 1000*(.5-x)*y/(.1**4/12)
                actual_stress = result.stress[..., 0, 0]
                error = np.linalg.norm((actual_stress-expected_stress)[interior])/np.linalg.norm(expected_stress[interior])
                self.assertLess(error, .05)
                self.assertGreater(actual_stress[interior & (y > 0)].mean(), 0.)
                self.assertLess(actual_stress[interior & (y < 0)].mean(), 0.)
                self.assertEqual(result.beam_message, "")
                expected_moments = -1000*(1-result.beam_stations)
                np.testing.assert_allclose(result.beam_moments[9:80, 1], expected_moments[9:80], rtol=.05)
                np.testing.assert_allclose(result.root_reaction, [0, 1000, 0, 0, 0, 1000], atol=1e-6)
    def test_short_cube_point_load_section_stress_equilibrium(self):
        g = self.geometry
        load = anchor(g, (.1, 0., 0.), (0., -100., 0.))
        clamp, tip = [end_selection(g, 0, x) for x in (-.1, .1)]
        for size in (.04, .025):
            with self.subTest(size=size):
                mesh = generate_mesh(g, MeshSettings(size), (load,))
                setup = replace(self.setup_for(mesh, (load,)), beam=BeamConfiguration(clamp, tip))
                result = solve_analysis(mesh, setup)
                expected = -100*(.2-result.beam_stations)
                np.testing.assert_allclose(result.beam_moments[15:75, 1], expected[15:75], rtol=.05)
                self.assertLess(max(result.residual_error, result.force_error, result.moment_error), 1e-8)

    def test_point_and_pin_supports_and_mesh_binding(self):
        g = self.geometry
        def fixed(xyz):
            p = anchor(g, xyz)
            return SupportCondition("fixed_point", source_triangle=p.source_triangle, barycentric=p.barycentric)
        supports = tuple(fixed(p) for p in ((-.1,-.1,-.1), (-.1,.1,-.1), (-.1,-.1,.1)))
        load = anchor(g, (.1, .013, .027))
        mesh = generate_mesh(g, MeshSettings(.07), (*supports, load))
        setup = replace(self.setup_for(mesh, (load,)), supports=(), support_conditions=supports)
        basis = make_basis(mesh)
        for count, modes in ((0,6), (1,3), (2,1), (3,0)):
            constraints = build_constraints(basis, mesh, replace(setup, support_conditions=supports[:count]))
            self.assertEqual(constraints.remaining_modes, modes)
        result = solve_analysis(mesh, setup)
        bindings = bind_point_targets(mesh, supports)
        for support in supports:
            np.testing.assert_allclose(result.displacement[bindings[support.identifier]], 0., atol=1e-14)
        self.assertLess(max(result.residual_error, result.force_error, result.moment_error), 1e-8)
        # IDs and force values are independent of mesh coverage; deleting a target
        # or rebinding to an already inserted position keeps the same mesh.
        replacement = replace(load, identifier="new-identity", force=(1., 2., 3.))
        self.assertEqual(bind_point_targets(mesh, (replacement,))[replacement.identifier], mesh.point_nodes[load.identifier])
        solve_analysis(mesh, replace(setup, point_loads=(replacement,)))
        pin = SupportCondition("pinned_face", end_selection(g, 0, .1))
        clamp = SupportCondition("fixed_face", end_selection(g, 0, -.1))
        pinned = replace(setup, support_conditions=(clamp, pin))
        self.assertEqual(build_constraints(basis, mesh, replace(pinned, support_conditions=(pin,))).remaining_modes, 3)
        result = solve_analysis(mesh, pinned)
        reaction = result.support_reactions[pin.identifier]
        np.testing.assert_allclose(reaction["moment"], 0., atol=1e-8)
        # The pin face moves as a rigid plane and may rotate about its centroid.
        facets = basis.get_dofs(facets=boundary_facets(basis, mesh, pin.triangles)).all()
        nodes = np.unique(facets//3)
        points = basis.doflocs.T[::3][nodes]-reaction["origin"]
        from simuo.structural.constraints import cross_matrix
        operator = np.vstack([cross_matrix(p) for p in points])
        actual = result.solution.reshape(-1, 3)[nodes].ravel()
        rotation = np.linalg.lstsq(operator, actual, rcond=None)[0]
        np.testing.assert_allclose(operator@rotation, actual, atol=1e-13)
        self.assertGreater(np.linalg.norm(rotation), 1e-12)

    def test_invalid_point_data(self):
        for triangle, bary, force in ((-1, (1, 0, 0), (1, 2, 3)), (0, (-.1, .5, .6), (1, 2, 3)), (0, (.2, .3, .6), (1, 2, 3)), (0, (1, 0, 0), (float("nan"), 0, 0))):
            with self.assertRaises(ValueError):
                PointLoad(triangle, bary, force)
