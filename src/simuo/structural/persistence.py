"""Versioned, atomic analysis inputs. Meshes and results are regenerated."""
from dataclasses import asdict
import json
import os
from pathlib import Path
import tempfile

from .geometry import fingerprint
from .models import AnalysisSetup, Material, MeshSettings, SurfaceLoad, BeamConfiguration, PointLoad
from simuo.project.project_format import read_project, project_data


def save_analysis(path, setup):
    path = Path(path).resolve()
    data = asdict(setup)
    try:
        data["geometry_path"] = Path(os.path.relpath(setup.geometry_path, path.parent)).as_posix()
    except ValueError:  # Windows geometry on another drive
        data["geometry_path"] = str(Path(setup.geometry_path).resolve())
    data = project_data("structural", setup=data)
    encoded = json.dumps(data, indent=2, allow_nan=False) + "\n"
    temporary = None
    try:
        with tempfile.NamedTemporaryFile(mode="w", encoding="utf-8", dir=path.parent, prefix=f".{path.name}.", delete=False) as stream:
            temporary = stream.name
            stream.write(encoded)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
        temporary = None
    finally:
        if temporary is not None:
            Path(temporary).unlink(missing_ok=True)


def load_analysis(path, verify_geometry=True):
    path = Path(path).resolve()
    try:
        document = read_project(path)
        if document.project_type != "structural":
            raise ValueError("This file is a scene, not a structural analysis")
        data = document.data
        d = dict(data["setup"])
        d["geometry_path"] = str((path.parent / d["geometry_path"].replace("\\", "/")).resolve())
        d["material"] = Material(**d["material"])
        d["mesh"] = MeshSettings(**d["mesh"])
        d["loads"] = tuple(SurfaceLoad(**item) for item in d["loads"])
        d["point_loads"] = tuple(PointLoad(**item) for item in d.get("point_loads", ()))
        d["beam"] = BeamConfiguration(**d["beam"]) if d["beam"] else None
        setup = AnalysisSetup(**d)
    except (TypeError, KeyError, AttributeError) as error:
        raise ValueError("Malformed analysis file") from error
    if verify_geometry and fingerprint(setup.geometry_path, setup.units) != setup.geometry_fingerprint:
        raise ValueError("Geometry changed; import it again and reassign boundaries")
    return setup
