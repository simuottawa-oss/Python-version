"""Real Gmsh, P2 elasticity and integrated section-result verification."""
from dataclasses import replace
from pathlib import Path
import tempfile
import unittest
import numpy as np
import manifold3d as m

from tests.structural_helpers import native_box, kernel_obj, end_selection
from simuo.structural.geometry import load_geometry
from simuo.structural.models import *
from simuo.structural.meshing import generate_mesh, validate_mesh
from simuo.structural.solver import solve_analysis, make_basis
from simuo.structural.postprocessing import recover_stress


class StructuralBackendTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temp = tempfile.TemporaryDirectory()
        cls.directory = Path(cls.temp.name)
        cls.geometry = load_geometry(native_box(cls.directory))
        cls.mesh = generate_mesh(cls.geometry, MeshSettings(.08))
        cls.clamp = end_selection(cls.geometry, 0, -.5)
        cls.tip = end_selection(cls.geometry, 0, .5)

    @classmethod
    def tearDownClass(cls):
        cls.temp.cleanup()

    def setup_analysis(self, **kwargs):
        g = self.geometry
        return replace(AnalysisSetup(g.path, g.fingerprint, "m", Material(2e11, 0., 2700), self.mesh.settings, (self.clamp,)), **kwargs)

    def test_volume_boundary_and_selection_survive_refinement(self):
        volumes = validate_mesh(self.mesh, self.geometry)
        self.assertTrue(np.all(volumes > 0))
        refined = generate_mesh(self.geometry, MeshSettings(.04))
        self.assertGreater(len(refined.tetrahedra), len(self.mesh.tetrahedra))
        self.assertEqual([p.triangles for p in refined.patches], [p.triangles for p in self.mesh.patches])
        self.assertGreater(len(refined.selected_boundary(self.tip)), 0)
        with self.assertRaisesRegex(ValueError, "reassign"):
            refined.selected_boundary((self.tip[0],))

    def test_hole_and_cavity_volumes_are_preserved(self):
        outer = m.Manifold.cube((1, 1, 1), True)
        solids = (outer-m.Manifold.cube((.4, .4, .4), True), outer-m.Manifold.cylinder(2, .2, .2, 16, True))
        for i, solid in enumerate(solids):
            g = load_geometry(kernel_obj(self.directory/f"cavity{i}.obj", solid))
            mesh = generate_mesh(g, MeshSettings(.23))
            self.assertAlmostEqual(validate_mesh(mesh).sum(), solid.volume(), places=8)

    def test_affine_displacement_patch_and_stress_projection(self):
        basis = make_basis(self.mesh)
        gradient = np.array([[.001, .002, 0], [.003, -.001, .004], [0, 0, .002]])
        values = (basis.doflocs.T@gradient.T)+[.1, .2, .3]
        u = values[np.arange(basis.N), np.arange(basis.N)%3]
        actual = basis.interpolate(u).grad.transpose(2, 3, 0, 1)
        np.testing.assert_allclose(actual, np.broadcast_to(gradient, actual.shape), rtol=1e-9, atol=1e-12)
        stress, vm, averaged, display = recover_stress(basis, u, Material(2e11, .3))
        np.testing.assert_allclose(stress, np.broadcast_to(stress[0, 0], stress.shape), rtol=1e-8, atol=.1)
        np.testing.assert_allclose(averaged, np.broadcast_to(stress[0, 0], averaged.shape), rtol=1e-8, atol=.1)

    def test_axial_bar_unloaded_and_reactions(self):
        setup = self.setup_analysis(loads=(SurfaceLoad(self.tip, "force", (1000, 0, 0)),))
        result = solve_analysis(self.mesh, setup)
        expected = 1000/(2e11*.1*.1)
        self.assertLess(abs(result.displacement[:, 0].max()/expected-1), .01)
        np.testing.assert_allclose(result.reactions.sum(axis=0), [-1000, 0, 0], atol=1e-8)
        for error in (result.residual_error, result.force_error, result.moment_error):
            self.assertLess(error, 1e-8)
        unloaded = solve_analysis(self.mesh, self.setup_analysis())
        np.testing.assert_array_equal(unloaded.displacement, 0)
        np.testing.assert_array_equal(unloaded.averaged_von_mises, 0)
        with self.assertRaisesRegex(ValueError, "clamped"):
            solve_analysis(self.mesh, replace(setup, supports=()))

    def test_inward_pressure_and_gravity_equilibrium(self):
        for setup, expected in ((self.setup_analysis(loads=(SurfaceLoad(self.tip, "pressure", (1e5,)),)), [-1000, 0, 0]),
                                (self.setup_analysis(gravity=(0, -9.81, 0)), [0, -2700*.01*9.81, 0])):
            result = solve_analysis(self.mesh, setup)
            np.testing.assert_allclose(result.applied_force, expected, atol=1e-8)
            np.testing.assert_allclose(result.reactions.sum(axis=0), -np.asarray(expected), atol=1e-8)
            self.assertLess(max(result.force_error, result.moment_error, result.residual_error), 1e-8)

    def test_refined_cantilever_displacement_and_signed_moments(self):
        setup = self.setup_analysis(material=Material(2e11, .3), loads=(SurfaceLoad(self.tip, "force", (0, -1000, 0)),), beam=BeamConfiguration(self.clamp, self.tip))
        errors = []
        for size in (.12, .03):
            mesh = generate_mesh(self.geometry, MeshSettings(size))
            result = solve_analysis(mesh, replace(setup, mesh=mesh.settings))
            expected = -1000/(3*2e11*(.1**4/12))
            errors.append(abs(result.displacement[:, 1].min()/expected-1))
        self.assertLess(errors[-1], .05)
        self.assertLess(errors[-1], errors[0])
        self.assertEqual(result.beam_stations.shape, (99,))
        expected_moment = -1000*(1-result.beam_stations)
        np.testing.assert_allclose(result.beam_moments[9:90, 1], expected_moment[9:90], rtol=.05)
        np.testing.assert_allclose(result.root_reaction, [0, 1000, 0, 0, 0, 1000], atol=1e-6)
        unsupported = solve_analysis(self.mesh, replace(setup, supports=(self.clamp, self.tip)))
        self.assertIsNone(unsupported.beam_moments)
        self.assertIn("one complete end clamp", unsupported.beam_message)
