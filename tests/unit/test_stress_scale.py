"""Strength validation and quantitative stress scales."""
from dataclasses import replace
import unittest
import numpy as np

from tests import ROOT
from simuo.materials import MaterialDefinition, MATERIAL_PRESETS, material_from_dict
from simuo.structural.models import Material
from simuo.structural.postprocessing import gradient_texture, normalized_field, stress_scale


class StressScaleTests(unittest.TestCase):
    def test_strength_validation_and_legacy_defaults(self):
        for values in ({"yield_strength": -1}, {"yield_strength": True}, {"ultimate_tensile_strength": float("inf")},
                       {"yield_strength": 20., "ultimate_tensile_strength": 10.}):
            for factory in (lambda: MaterialDefinition("Custom", **values), lambda: Material(1e9, .3, **values)):
                with self.assertRaises(ValueError):
                    factory()
        legacy = material_from_dict({"name": "Old", "young_modulus": 1e9})
        self.assertIsNone(legacy.yield_strength)
        self.assertIsNone(legacy.ultimate_tensile_strength)
        value = MATERIAL_PRESETS["aluminum-6061-t6"]
        self.assertEqual(material_from_dict(value.to_dict()), value)

    def test_shared_gradient_endpoints(self):
        np.testing.assert_array_equal(gradient_texture(256)[[0, 85, 170, 255]],
                                      [[0, 0, 255], [0, 255, 0], [255, 255, 0], [255, 0, 0]])

    def test_absolute_scale_saturation_and_fallback(self):
        material = MATERIAL_PRESETS["aluminum-6061-t6"]
        values = np.array([0, 120e6, 240e6, 300e6])
        before = values.copy()
        maximum, label = stress_scale(values, "yield", material)
        self.assertEqual(maximum, 240e6)
        self.assertEqual(label, "Material yield")
        np.testing.assert_array_equal(normalized_field(values, maximum)[0], [0, .5, 1, 1])
        self.assertEqual(stress_scale(values, "uts", material)[0], 260e6)
        self.assertEqual(stress_scale(values, "custom", material, 600e6)[0], 600e6)
        no_strength = replace(material, yield_strength=None)
        maximum, label = stress_scale(values, "yield", no_strength)
        self.assertEqual(maximum, 300e6)
        self.assertIn("not supplied", label)
        np.testing.assert_array_equal(normalized_field(np.zeros(3), material.yield_strength)[0], 0)
        np.testing.assert_array_equal(normalized_field(np.full(3, 120e6), material.yield_strength)[0], .5)
        np.testing.assert_array_equal(values, before)
