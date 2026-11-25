# Physics migration baseline

Recorded on 2026-11-25 with PyBullet 3.2.7, before replacing any solver code.
These observations describe current behavior; they are not accuracy guarantees
or requirements to reproduce Bullet's numerical output exactly.

This document describes the pre-migration state. For the current solver and
validation results, see [physics backend](physics-backend.md).

## Focused checks used for the baseline

```bash
.venv/bin/python -m unittest tests.unit.test_physics_world tests.integration.test_properties tests.integration.test_sketch_parts tests.integration.test_physics_framing -v
```

Before the MuJoCo replacement, the original 46 physics, properties, and sketch checks passed before the refactor.
After adding stacking and engine-independent framing coverage, all 50 focused
checks passed. Integration tests use Qt's offscreen platform.
The full `unittest discover -s tests -t .` run also completed successfully:
260 tests run, one skipped, no failures.

## Representative behavior

Default physics uses a 1/240 s outer timestep, four Bullet substeps, 80 solver
iterations, Y-up coordinates, and gravity of -9.81 m/s². The test cube is 0.2 m
on each side. Initial motion in each case is zero unless specified.

| Case | Setup and duration | Observed result / acceptance check |
| --- | --- | --- |
| Free fall | Cube at y=2 m, no floor, 48 steps (0.2 s) | y=1.802778125 m; vy=-1.962 m/s. Analytical y=1.8038 m; existing position tolerance 0.005 m. |
| Bounce and reset | Default aluminum cube at y=1.1 m, floor, 2400 steps (10 s) | Upward speed exceeds 0.3 m/s during bounce; settles at y≈0.1 m; reset and replay reproduce position within 1e-8 m. |
| Sliding friction | Cube at y=0.1 m with vx=1 m/s, floor, 480 steps (2 s) | x≈0.101438 m; final speed≈0.0000106 m/s, below the existing 0.05 m/s threshold. |
| Stack | Three cubes at y=0.1/0.3/0.5 m, zero restitution, floor, 2400 steps | Centers settle at y≈0.099989/0.299979/0.499969 m. Each remains within 0.005 m of its initial center, speed below 0.01 m/s. |
| Head-on collision | Equal cubes, vx=+1/-1 m/s, restitution=1, friction=0, no gravity or floor, 120 steps | Directions reverse, outgoing speed exceeds 0.8 m/s; summed X velocities remain zero to five decimal places. |
| Prescribed kinematic motion | Start (1,2,3) m, vx=2 m/s, ax=4 m/s², 240 steps | Ends at (5,2,3) m with vx=6 m/s; ignores gravity and resets to initial state. |
| Kinematic contact | Moving kinematic cube pushes a dynamic cube, 240 steps | Dynamic cube moves forward; restitution=1 yields at least 0.5 m/s more outgoing speed than restitution=0. |
| Sketch-generated mesh | Saved rectangular prism, volume=0.0001 m³, mass=0.1 kg, 480 steps | Loads into physics and remains supported above y=0.004 m with floor contact. |

Existing tests also cover static/legacy meshes, scale-dependent mass and box
inertia, rotation conventions, property persistence, and isolated simulations.
Some assertions inspect Bullet internals; adapt those when adding a new backend
while retaining the scene-state and physical-behavior assertions.

## Rendering boundary

`PhysicsRenderWindow` now uses `simuo.project.transforms.rotation_matrix` for
camera framing. The helper follows the viewport's Rx * Ry * Rz convention in
degrees. Tests compare it with the viewport's GLM rotation operations, including
gimbal-lock orientations, and frame rotated/scaled objects using a world stub
with no Bullet handle. Framing covers floor enabled/disabled and empty scenes.

At this stage, playback continued to use `PhysicsWorld` for scene state, stepping, reset,
gravity, floor selection, time, counts, and cleanup. PyBullet still implemented
the solver; the MuJoCo replacement had not yet been introduced.

The desktop OpenGL playback check was attempted but macOS terminated the
process while connecting to desktop services (pasteboard/HI services). Live
OpenGL playback therefore remains unverified in this environment. To check it
in a desktop terminal:

```bash
.venv/bin/python -m tests.desktop.gui_physics_playback
```
