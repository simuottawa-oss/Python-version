"""Independent input builders for structural integration and desktop checks."""
import json
from pathlib import Path
import numpy as np

from tests import ROOT


def native_box(directory, size=(1., .1, .1)):
    path = Path(directory)/"beam.simuOPart"
    data = json.loads((ROOT/"Assets/aluminum_cube.simuOPart").read_text())
    data["geometry"]["size"] = list(size)
    path.write_text(json.dumps(data), encoding="utf-8")
    return path


def write_obj(path, points, triangles):
    Path(path).write_text("".join("v %.17g %.17g %.17g\n" % tuple(p) for p in points)+"".join("f %d %d %d\n" % tuple(t+1) for t in triangles), encoding="utf-8")
    return Path(path)


def kernel_obj(path, solid):
    mesh = solid.to_mesh64()
    return write_obj(path, np.asarray(mesh.vert_properties)[:, :3], np.asarray(mesh.tri_verts))


def end_selection(geometry, axis, value):
    return tuple(i for i, triangle in enumerate(geometry.points[geometry.triangles]) if np.all(np.abs(triangle[:, axis]-value) < 1e-10))
