"""Reproducible CPU playback benchmark; run with python -m tests.physics_benchmark.

Reports model construction and stepping separately. This is a diagnostic, not
a timing assertion: results vary by hardware, Python, and solver version.
"""
from dataclasses import replace
import json
import platform
import statistics
import time

import mujoco

from tests import ROOT
from simuo.physics.physics_world import PhysicsWorld
from simuo.project.scene import Scene, SceneObject


def benchmark():
    results = []
    for count in (1, 20):
        compile_times, step_times = [], []
        for _ in range(3):
            scene = Scene()
            for index in range(count):
                obj = SceneObject(meshPath=ROOT / "Assets/aluminum_cube.simuOPart")
                obj.position = [(index % 5)*.4, .1 + (index // 5)*.2, 0]
                obj.velocity = [0, 0, 0]
                obj.part = replace(obj.part, restitution=0)
                scene.addObject(obj)
            start = time.perf_counter()
            world = PhysicsWorld(scene)
            compile_times.append(time.perf_counter()-start)
            try:
                start = time.perf_counter()
                world.step(480)
                step_times.append(time.perf_counter()-start)
            finally:
                world.close()
        elapsed = statistics.median(step_times)
        results.append({"bodies": count, "compile_seconds": statistics.median(compile_times),
                        "step_seconds": elapsed, "simulated_seconds": 2,
                        "realtime_factor": 2/elapsed})
    return {"python": platform.python_version(), "platform": platform.platform(),
            "mujoco": mujoco.__version__, "runs": results}


if __name__ == "__main__":
    print(json.dumps(benchmark(), indent=2))
