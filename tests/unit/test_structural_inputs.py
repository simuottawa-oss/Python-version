"""Import safety, topology, precise geometry, input persistence and display scaling."""
from dataclasses import replace
import json
from pathlib import Path
import struct
import tempfile
import unittest
from unittest.mock import patch
import numpy as np
import manifold3d as m

from tests import ROOT
from tests.structural_helpers import native_box, kernel_obj, write_obj
from simuo.structural.geometry import load_geometry, validate_surface
from simuo.structural.models import *
from simuo.structural.persistence import save_analysis, load_analysis
from simuo.structural.postprocessing import gradient_texture, normalized_field, von_mises


class StructuralInputTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.directory = Path(self.temp.name)

    def test_native_versions_and_obj_preserve_source_and_precision(self):
        for name in ("aluminum_cube", "sketch_plate", "feature_demo"):
            source = ROOT/f"Assets/{name}.simuOPart"
            before = source.read_bytes()
            g = load_geometry(source)
            self.assertEqual(source.read_bytes(), before)
            self.assertEqual(g.points.dtype, np.float64)
            self.assertGreater(g.volume, 0)
            self.assertIsNotNone(g.density)
        path = native_box(self.directory, (1.1234567890123, .1, .1))
        g = load_geometry(path)
        self.assertAlmostEqual(g.dimensions[0], 1.1234567890123, places=14)
        for suffix in (".obj", ".simuOPart"):
            obj = write_obj(self.directory/f"raw{suffix}", g.points, g.triangles)
            actual = load_geometry(obj)
            self.assertAlmostEqual(actual.volume, g.volume, places=14)
            self.assertIsNone(actual.density)

    def test_ascii_binary_stl_solid_header_and_units(self):
        g = load_geometry(native_box(self.directory))
        triangles = g.points[g.triangles]
        binary = b"solid binary header".ljust(80, b" ")+struct.pack("<I", len(triangles))
        for triangle in triangles:
            binary += struct.pack("<12fH", 0, 0, 0, *triangle.ravel(), 0)
        ascii_stl = "solid beam\n"+"".join("facet normal 0 0 0\nouter loop\n"+"".join("vertex %.17g %.17g %.17g\n" % tuple(p) for p in t)+"endloop\nendfacet\n" for t in triangles)+"endsolid beam\n"
        for content in (binary, ascii_stl.encode()):
            path = self.directory/"beam.stl"
            path.write_bytes(content)
            for units, scale in (("m", 1.), ("mm", .001), ("cm", .01), ("in", .0254)):
                actual = load_geometry(path, units)
                np.testing.assert_allclose(actual.dimensions, g.dimensions*scale, rtol=1e-7)
                self.assertEqual(path.read_bytes(), content)

    def test_closed_orientable_connected_and_cavity_validation(self):
        outer = m.Manifold.cube((1, 1, 1), True)
        for label, solid, volume in (("cavity", outer-m.Manifold.cube((.4, .4, .4), True), .936),
                                      ("hole", outer-m.Manifold.cylinder(2, .2, .2, 24, True), 1-m.Manifold.cylinder(1, .2, .2, 24, True).volume())):
            g = load_geometry(kernel_obj(self.directory/f"{label}.obj", solid))
            self.assertAlmostEqual(g.volume, volume, places=10)
        g = load_geometry(native_box(self.directory))
        with self.assertRaisesRegex(ValueError, "closed"):
            validate_surface(g.points, g.triangles[:-1])
        with self.assertRaisesRegex(ValueError, "Duplicate"):
            validate_surface(g.points, np.vstack((g.triangles, g.triangles[0])))
        with self.assertRaisesRegex(ValueError, "Degenerate"):
            validate_surface(g.points, np.vstack((g.triangles, [0, 0, 1])))
        points = np.vstack((g.points, g.points+[2, 0, 0]))
        with self.assertRaisesRegex(ValueError, "one connected"):
            validate_surface(points, np.vstack((g.triangles, g.triangles+len(g.points))))
        # Closed but intersecting shells are not valid cavities/material bodies.
        with self.assertRaisesRegex(ValueError, "intersect|touch|Overlapping"):
            validate_surface(np.vstack((g.points, g.points+[.25, .025, .025])), np.vstack((g.triangles, g.triangles+len(g.points))))
        shuffled = g.triangles.copy(); shuffled[::2] = shuffled[::2, ::-1]
        _, _, shells, _ = validate_surface(g.points, shuffled)
        self.assertEqual(len(shells), 1)

    def test_invalid_imports_fail_cleanly(self):
        for suffix, content in (("stl", b"solid broken\nvertex 0 0 0"), ("obj", b"v nan 0 0\nf 1 1 1"), ("simuOPart", b'{"version": 999}')):
            path = self.directory/f"bad.{suffix}"; path.write_bytes(content)
            with self.assertRaises(ValueError):
                load_geometry(path)
        with self.assertRaisesRegex(ValueError, "metres"):
            load_geometry(native_box(self.directory), "mm")

    def test_persistence_atomic_relative_and_geometry_change(self):
        g = load_geometry(native_box(self.directory))
        setup = AnalysisSetup(g.path, g.fingerprint, "m", Material(2e11, .3, 2700), MeshSettings(.1), ((0, 1),), (SurfaceLoad((2, 3), "force", (1, 2, 3)),), beam=BeamConfiguration((0, 1), (2, 3)))
        path = self.directory/"saved.simuO"
        save_analysis(path, setup)
        self.assertEqual(load_analysis(path), setup)
        self.assertEqual(json.loads(path.read_text())["setup"]["geometry_path"], "beam.simuOPart")
        original = path.read_bytes()
        with patch("simuo.structural.persistence.os.replace", side_effect=OSError("disk full")):
            with self.assertRaises(OSError):
                save_analysis(path, setup)
        self.assertEqual(path.read_bytes(), original)
        self.assertEqual(list(self.directory.glob(".saved.*")), [])
        Path(g.path).write_text(Path(g.path).read_text()+"\n")
        with self.assertRaisesRegex(ValueError, "changed"):
            load_analysis(path)
        Path(g.path).unlink()
        with self.assertRaises(FileNotFoundError):
            load_analysis(path)

    def test_invalid_inputs_and_display_fields(self):
        for e, nu in ((0, .3), (1, .5), (1, -1), (float("nan"), .3), (True, .3)):
            with self.assertRaises(ValueError):
                Material(e, nu)
        for value in (0, -1, float("inf")):
            with self.assertRaises(ValueError):
                MeshSettings(value)
        with self.assertRaises(ValueError):
            SurfaceLoad((1, 1))
        np.testing.assert_array_equal(gradient_texture()[[0, 128, 256]], [[0, 255, 0], [255, 255, 0], [255, 0, 0]])
        np.testing.assert_array_equal(normalized_field(np.zeros(3))[0], [0, 0, 0])
        np.testing.assert_array_equal(normalized_field(np.ones(3)*5)[0], [1, 1, 1])
        self.assertEqual(normalized_field([0, 5, 10])[1], 10)
        self.assertAlmostEqual(von_mises(np.diag([3., 0, 0])), 3.)
        with self.assertRaises(ValueError):
            normalized_field([np.nan])
