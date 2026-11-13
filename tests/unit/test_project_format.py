"""One project extension, explicit dispatch and compatible legacy payloads."""
import json
from pathlib import Path
import tempfile
import unittest

from simuo.project.project_format import read_project, project_data
from simuo.structural.models import AnalysisSetup, Material, MeshSettings, PointLoad
from simuo.structural.persistence import save_analysis, load_analysis
from simuo.structural.geometry import load_geometry
from tests.structural_helpers import native_box


class ProjectFormatTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.directory = Path(self.temp.name)
        self.path = self.directory/"project.simuO"

    def read(self, data):
        self.path.write_text(json.dumps(data))
        return read_project(self.path)

    def test_headers_and_legacy_scenes(self):
        for data in ({"objects": []}, {"version": 1, "objects": []}, project_data("scene", objects=[])):
            self.assertEqual(self.read(data).project_type, "scene")
        self.assertEqual(self.read(project_data("structural", setup={})).project_type, "structural")
        self.assertTrue(self.read({"format": ".simuOAnalysis", "version": 1, "setup": {}}).legacy)

    def test_malformed_files_never_become_empty_scenes(self):
        for data in ({}, [], {"version": 2, "objects": []}, {"version": True, "objects": []},
                     project_data("scene", objects={}), {"format": ".simuO", "version": 99, "project_type": "scene", "objects": []},
                     {"format": ".simuO", "version": 2, "project_type": "unknown"},
                     project_data("structural", setup=[])):
            with self.subTest(data=data), self.assertRaises(ValueError):
                self.read(data)
        for content in ('{"objects": [], "objects": []}', '{"objects": [], "x": NaN}', '{"objects": [], "x": 1e999}'):
            self.path.write_text(content)
            with self.assertRaises(ValueError):
                read_project(self.path)

    def test_structural_roundtrip_and_legacy_migration(self):
        geometry = load_geometry(native_box(self.directory))
        point = PointLoad(0, (.2, .3, .5), (1., 2., 3.), name="Tip force")
        setup = AnalysisSetup(geometry.path, geometry.fingerprint, "m", Material(69e9, .33, 2700, "6061-T6 aluminum", "aluminum-6061-t6"), MeshSettings(.05), point_loads=(point,))
        save_analysis(self.path, setup)
        document = read_project(self.path)
        self.assertEqual(document.data["format"], ".simuO")
        self.assertEqual(document.data["version"], 2)
        self.assertEqual(load_analysis(self.path), setup)
        legacy = document.data
        legacy.pop("project_type")
        legacy["format"], legacy["version"] = ".simuOAnalysis", 1
        legacy["setup"].pop("point_loads")
        legacy["setup"].pop("support_names")
        legacy["setup"]["material"].pop("name")
        legacy["setup"]["material"].pop("preset_id")
        self.path.write_text(json.dumps(legacy))
        restored = load_analysis(self.path)
        self.assertEqual(restored.point_loads, ())
        self.assertEqual(restored.material.young_modulus, setup.material.young_modulus)
        save_analysis(self.directory/"migrated.simuO", restored)
        self.assertTrue(read_project(self.path).legacy)
        self.assertFalse(read_project(self.directory/"migrated.simuO").legacy)
