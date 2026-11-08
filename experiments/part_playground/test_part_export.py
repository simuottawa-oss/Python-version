"""Independent geometry and native-file persistence regressions."""
import json
import math
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from part import load_part
from part_export import export_obj, export_stl, save_part

SAMPLE = Path(__file__).with_name("aluminum_cube.simuOPart")


class ExportTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="SimuO export ")
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.part = load_part(SAMPLE)

    def test_obj_dimensions_closed_surface_and_outward_winding(self):
        path = self.root / "cube.obj"
        export_obj(path, self.part)
        vertices, faces, normals = [], [], []
        for line in path.read_text().splitlines():
            tokens = line.split()
            if tokens[0] == "v":
                vertices.append(tuple(map(float, tokens[1:])))
            elif tokens[0] == "vn":
                normals.append(tuple(map(float, tokens[1:])))
            elif tokens[0] == "f":
                faces.append([int(token.split("//")[0])-1 for token in tokens[1:]])
        self.assertEqual(len(vertices), 8)
        self.assertEqual(len(faces), 12)
        edges = {}
        for face in faces:
            a, b, c = (vertices[i] for i in face)
            ab = [b[i]-a[i] for i in range(3)]
            ac = [c[i]-a[i] for i in range(3)]
            normal = (ab[1]*ac[2]-ab[2]*ac[1], ab[2]*ac[0]-ab[0]*ac[2], ab[0]*ac[1]-ab[1]*ac[0])
            self.assertGreater(sum(normal[i]*a[i] for i in range(3)), 0)
            for edge in zip(face, face[1:]+face[:1]):
                edge = tuple(sorted(edge))
                edges[edge] = edges.get(edge, 0)+1
        self.assertTrue(all(count == 2 for count in edges.values()))
        for axis in range(3):
            self.assertAlmostEqual(max(v[axis] for v in vertices)-min(v[axis] for v in vertices), self.part.size[axis])
            self.assertAlmostEqual(sum(v[axis] for v in vertices), 0)
        self.assertTrue(all(math.isclose(math.hypot(*n), 1) for n in normals))

    def test_stl_twelve_triangles_correct_volume_and_normals(self):
        path = self.root / "cube.stl"
        export_stl(path, self.part)
        vertices, normals = [], []
        for line in path.read_text().splitlines():
            tokens = line.split()
            if tokens[:1] == ["vertex"]:
                vertices.append(tuple(map(float, tokens[1:])))
            elif tokens[:2] == ["facet", "normal"]:
                normals.append(tuple(map(float, tokens[2:])))
        self.assertEqual(len(vertices), 36)
        self.assertEqual(len(normals), 12)
        volume = 0
        for index, normal in enumerate(normals):
            a, b, c = vertices[index*3:index*3+3]
            bc = (b[1]*c[2]-b[2]*c[1], b[2]*c[0]-b[0]*c[2], b[0]*c[1]-b[1]*c[0])
            volume += sum(a[i]*bc[i] for i in range(3))/6
            ab, ac = [b[i]-a[i] for i in range(3)], [c[i]-a[i] for i in range(3)]
            cross = (ab[1]*ac[2]-ab[2]*ac[1], ab[2]*ac[0]-ab[0]*ac[2], ab[0]*ac[1]-ab[1]*ac[0])
            self.assertGreater(sum(cross[i]*normal[i] for i in range(3)), 0)
        self.assertAlmostEqual(volume, self.part.volume)

    def test_native_save_preserves_explicit_mass_description_and_properties(self):
        data = json.loads(SAMPLE.read_text())
        data["physics"].update(mass_source="explicit", mass=12.5)
        data["description"] = "Test part — preserved"
        text = json.dumps(data, ensure_ascii=False)
        path = self.root / "saved.simuOPart"
        save_part(path, text)
        self.assertEqual(json.loads(path.read_text(encoding="utf-8")), data)
        self.assertEqual(load_part(path).mass, 12.5)
        self.assertEqual(load_part(path).properties, self.part.properties)

    def test_failed_export_preserves_existing_file_and_cleans_staging(self):
        path = self.root / "cube.obj"
        path.write_bytes(b"existing file")
        with patch("part_export.os.replace", side_effect=PermissionError("Read-only destination")):
            with self.assertRaises(PermissionError):
                export_obj(path, self.part)
        self.assertEqual(path.read_bytes(), b"existing file")
        self.assertEqual(list(self.root.glob(".cube.obj.*")), [])

    def test_unwritable_destination_reports_failure_without_changing_source(self):
        original = SAMPLE.read_bytes()
        for exporter, extension in ((export_obj, "obj"), (export_stl, "stl")):
            with self.assertRaises(OSError):
                exporter(self.root / "missing folder" / ("cube."+extension), self.part)
        self.assertEqual(SAMPLE.read_bytes(), original)


if __name__ == "__main__":
    unittest.main()
