"""Real spawned-worker smoke check, also available in the packaged executable."""
import json
from pathlib import Path
import tempfile
import time
import numpy as np

from simuo.resources.paths import resource_path
from .jobs import BackgroundJob
from .models import AnalysisSetup, Material, MeshSettings, SurfaceLoad, PointLoad
from .persistence import save_analysis, load_analysis
from simuo.project.project_format import read_project
from dataclasses import replace


def wait_for_job(job, timeout=60.):
    deadline = time.monotonic()+timeout
    try:
        while time.monotonic() < deadline:
            for kind, value in job.poll():
                if kind == "error":
                    raise RuntimeError(value)
                if kind == "result":
                    return value
            time.sleep(.02)
        raise TimeoutError("Structural worker smoke test timed out")
    finally:
        job.cancel()


def run_smoke():
    with tempfile.TemporaryDirectory(prefix="simuo-structural-smoke-") as directory:
        path = Path(directory)/"bar.simuOPart"
        data = json.loads(resource_path("Assets", "aluminum_cube.simuOPart").read_text(encoding="utf-8"))
        data["geometry"]["size"] = [1., .1, .1]
        path.write_text(json.dumps(data), encoding="utf-8")
        job = BackgroundJob()
        settings = MeshSettings(.09)
        job.start("prepare", str(path), "m", settings)
        geometry, patches = wait_for_job(job)
        job.start("mesh", geometry, settings)
        mesh = wait_for_job(job)
        ends = [tuple(i for i, triangle in enumerate(geometry.points[geometry.triangles]) if np.allclose(triangle[:, 0], x)) for x in (-.5, .5)]
        setup = AnalysisSetup(str(path), geometry.fingerprint, "m", Material(2e11, 0.), settings,
                              (ends[0],), (SurfaceLoad(ends[1], "force", (1000., 0., 0.)),))
        job.start("solve", mesh, setup)
        result = wait_for_job(job)
        expected = 1000/(2e11*.01)
        if not np.isclose(result.displacement[:, 0].max(), expected, rtol=.01):
            raise RuntimeError("Packaged axial benchmark failed")
        point = PointLoad(ends[1][0], (1/3, 1/3, 1/3), (0., -100., 0.))
        job.start("mesh", geometry, settings, (point,))
        point_mesh = wait_for_job(job)
        point_setup = replace(setup, loads=(), point_loads=(point,))
        project = Path(directory)/"structural.simuO"
        save_analysis(project, point_setup)
        if read_project(project).project_type != "structural":
            raise RuntimeError("Packaged project routing failed")
        job.start("solve", point_mesh, load_analysis(project))
        point_result = wait_for_job(job)
        if not np.allclose(point_result.applied_force, (0., -100., 0.), atol=1e-8) or point.identifier not in point_mesh.point_nodes:
            raise RuntimeError("Packaged point force benchmark failed")
        print("Structural smoke passed: real Gmsh, spawned P2 solver, axial benchmark, exact point force and .simuO roundtrip")
    return 0


if __name__ == "__main__":
    import multiprocessing
    multiprocessing.freeze_support()
    raise SystemExit(run_smoke())
