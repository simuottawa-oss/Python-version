"""Display deformation scales without changing physical inputs or results."""
import unittest
import numpy as np

from tests import ROOT
from simuo.structural.postprocessing import deformed_points


class DeformationTests(unittest.TestCase):
    def setUp(self):
        self.points = np.array([[0., 0., 0.], [1., 0., 0.], [2., 0., 0.]])
        self.displacement = np.array([[0., 0., 0.], [0., -.001, 0.], [0., -.004, 0.]])

    def test_true_custom_and_automatic_magnification(self):
        points, displacement = self.points.copy(), self.displacement.copy()
        true, scale, peak = deformed_points(points, displacement, "true")
        np.testing.assert_allclose(true, points+displacement)
        self.assertEqual(scale, 1.)
        self.assertEqual(peak, .004)
        custom, scale, _ = deformed_points(points, displacement, "custom", 12.5)
        np.testing.assert_allclose(custom, points+12.5*displacement)
        self.assertEqual(scale, 12.5)
        auto, scale, _ = deformed_points(points, displacement)
        self.assertEqual(scale, 50.)
        self.assertAlmostEqual(auto[-1, 1], -.2)
        np.testing.assert_array_equal(auto[0], points[0])
        np.testing.assert_array_equal(points, self.points)
        np.testing.assert_array_equal(displacement, self.displacement)

    def test_zero_load_and_no_automatic_reduction_of_real_displacement(self):
        unloaded, scale, peak = deformed_points(self.points, np.zeros_like(self.points))
        self.assertEqual((scale, peak), (1., 0.))
        np.testing.assert_array_equal(unloaded, self.points)
        large = self.displacement*1000
        displayed, scale, peak = deformed_points(self.points, large)
        self.assertEqual((scale, peak), (1., 4.))
        np.testing.assert_array_equal(displayed, self.points+large)

    def test_invalid_fields_and_magnifications(self):
        for value in (0, -1, True, float("inf"), float("nan")):
            with self.assertRaisesRegex(ValueError, "finite and positive"):
                deformed_points(self.points, self.displacement, "custom", value)
        for bad in (np.zeros((2, 3)), np.zeros((3, 2)), np.full((3, 3), np.nan)):
            with self.assertRaisesRegex(ValueError, "matching finite"):
                deformed_points(self.points, bad)
        with self.assertRaisesRegex(ValueError, "Unknown"):
            deformed_points(self.points, self.displacement, "unknown")
