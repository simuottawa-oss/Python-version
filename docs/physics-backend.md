# Physics backend

SimuO uses MuJoCo 3.3.7 through its native Python bindings. Install the normal
project requirements; the wheel includes the native engine. Playback uses the
existing Qt/OpenGL viewport, not MuJoCo's viewer. Editing and saving do not load
MuJoCo; creating a `PhysicsWorld` imports it lazily.

## Scene and playback contract

`PhysicsWorld(scene, gravity=-9.81, floor=True)` copies instance transforms,
velocity, acceleration, angular velocity and scale. It shares asset definitions
but never changes the editor scene. The existing `step`, `sync`, `reset`,
`set_gravity`, `time`, `floor`, `scene`, and `close` operations remain available.
Each playback window owns a separate MuJoCo model/data pair. `close()` releases
those references, sets `closed`, and is idempotent. A closed world cannot step
or reset.

Scene coordinates remain Y-up, in metres, seconds, kilograms and radians per
second for angular velocity. Scene rotations remain Euler degrees with the
viewport's Rx * Ry * Rz convention. MuJoCo quaternions use WXYZ; free-joint
angular velocities use body-local axes and are converted to/from the scene's
world axes. Scene files and part formats are unchanged.

The public outer timestep is 1/240 s. Each outer step runs eight MuJoCo
substeps with the implicit-fast integrator, elliptic friction cones and up to
80 Newton solver iterations. Non-finite state and MuJoCo numerical/capacity
warnings raise an error; the playback window pauses and displays it.

## Body and collision behavior

- Dynamic boxes use free joints and analytical box inertia. Density-based mass
  scales with volume; explicit mass remains fixed.
- Moving sketch, feature and OBJ meshes collide as convex hulls. MuJoCo derives
  their inertial frame and inertia from collision geometry; these are
  approximations for concave shapes, not engineering mass-property analysis.
- Static mesh surfaces are represented by individual two-sided triangle prisms
  with total thickness 0.00001 m, preserving holes and concavities. Degenerate
  triangles are skipped. This is a surface approximation: seams and extremely
  thin features can affect contacts, and large triangle counts increase model
  construction and collision cost.
- Kinematic objects use massless mocap bodies. Their translation follows the
  prescribed velocity and constant acceleration; gravity and contact impulses
  do not change their path. Orientation stays fixed, as in previous playback.
  Mocap bodies have no velocity DOFs, so their prescribed relative velocity and
  acceleration are included in the contact constraint reference. Tests cover
  normal pushing, tangential friction and an accelerating support platform.
- Legacy OBJ bodies retain their static default and 1 kg dynamic fallback.

The floor is an infinite plane at Y=0; its displayed patch is visual only.
Changing the floor flag and resetting rebuilds the model. Changing gravity
updates the current model without resetting motion.

## Materials

Both surfaces contribute: sliding friction and bounce coefficients are
multiplied. The optional floor has neutral coefficients of 1. MuJoCo requires a
small positive friction floor (0.00001) for its constraint solver.

MuJoCo does not expose a rigid impact restitution coefficient. SimuO maps the
bounce target to a unilateral damped spring contact in direct `solref` format.
The damping ratio is found from the continuous force-release restitution
relation; stiffness and damping are bounded for the selected substep. A bounce
setting of zero uses a highly dissipative limit (target 0.005); one is undamped.
Measured restitution remains approximate and depends on timestep, geometry,
impact speed and simultaneous contacts. Numerical results will differ from the
old Bullet baseline. This is not a guarantee of exact impact coefficients or
research-grade contact accuracy.

Material parameters are applied to the detected contacts, then MuJoCo's
constraint rows are rebuilt before solving. No process-global callbacks are
installed, so simultaneous worlds do not override one another's behavior.

## Verification

```bash
.venv/bin/python -m unittest discover -s tests -t . -v
.venv/bin/python -m tests.physics_benchmark
.venv/bin/python -m tests.desktop.gui_physics_playback
.venv/bin/python -m tests.desktop.gui_properties
.venv/bin/python -m PyInstaller --noconfirm src/main.spec
```

The benchmark reports medians of three runs for one body and twenty bodies,
with model construction separate from two seconds of simulated contact motion.
It is a diagnostic, not a cross-machine performance requirement. The earlier
[Bullet baseline](physics-migration-baseline.md) records physical acceptance
checks and observations before the replacement.

The PyInstaller spec collects MuJoCo's native libraries, plugins, data and
bindings. Windows and macOS CI install the same pinned requirements and run the
headless tests. Windows CI also builds and starts the packaged executable.
Local results and remaining platform checks are recorded below.

## Local validation (2026-11-25)

Environment: macOS arm64, Python 3.12.5, MuJoCo 3.3.7. `pip check` reports no
broken requirements. Physical regressions cover free fall, initial/angular
velocity, additional acceleration, bounce, friction, momentum exchange, stacks,
reset/replay, scaling/inertia, static concavity, sketch/feature meshes and
kinematic contact. Offscreen playback checks exercise pause/step/reset, gravity,
floor toggling, source isolation, independent windows, cleanup and error display
with the real solver and a GPU-free viewport stub.

Timing medians below use the same three-run benchmark and scene setup. The
Bullet comparison loaded the original `PhysicsWorld` source from Git commit
`088d0d3` into a temporary namespace; it is not a second shipped backend.

| Engine | Bodies | Model construction | Time to simulate 2 s | Simulated time / elapsed time |
| --- | ---: | ---: | ---: | ---: |
| PyBullet 3.2.7 baseline | 1 | 4.98 ms | 3.98 ms | 502.6× |
| MuJoCo 3.3.7 | 1 | 0.94 ms | 128.70 ms | 15.5× |
| PyBullet 3.2.7 baseline | 20 | 7.72 ms | 511.04 ms | 3.91× |
| MuJoCo 3.3.7 | 20 | 2.27 ms | 553.20 ms | 3.62× |

The replacement is slower at stepping these cases, especially the one-body
case because of Python substep/contact handling. Both measured scenes run
faster than real time. This migration does not claim a speed improvement;
large imported meshes and more demanding scenes need separate profiling.

The complete macOS application and a frozen physics smoke program both built
successfully with the production MuJoCo collection settings. Launching either
frozen executable was blocked by the environment's semaphore restriction
(`semctl: Operation not permitted`) before application code could execute.
The desktop playback test also terminated while connecting to macOS
pasteboard/HI services. Thus actual OpenGL playback and frozen solver startup
remain manual checks on an unrestricted desktop. Windows/Linux execution was
not available locally; configured CI and platform testing remain necessary.

If PyInstaller's default cache is not writable, direct it to a writable scratch
location using `PYINSTALLER_CONFIG_DIR`; this was needed for the local build.

Final automated results: 273 unit/integration tests run, one Windows-only test
skipped, no failures; all 16 independent part-playground tests passed.
`git diff --check` reported no whitespace errors.
