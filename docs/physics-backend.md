# Physics backend

MuJoCo 3.3.7 is installed through `requirements.txt`. Each playback window owns
a model compiled from a copy of the scene. `PhysicsWorld.step()` advances
1/240 s using eight solver substeps. Scene files still use Y-up coordinates,
metres, and Euler angles in degrees.

- Moving meshes collide as convex hulls. Static mesh surfaces use 10 µm
  triangle prisms to preserve holes and concavities. Dense meshes cost more
  to compile and simulate, and triangle seams can affect contact.
- Kinematic objects follow their prescribed translation with fixed orientation.
  Their motion can push dynamic bodies without changing their own path.
- Friction and bounce coefficients multiply across contacting surfaces. The
  optional floor has coefficients of 1. Bounce is approximated with soft-contact
  stiffness and damping, so measured restitution varies with contact conditions.

## Migration validation

On Apple Silicon, 272 unit and integration tests passed and one Windows-only
test was skipped. All 16 playground tests passed. The macOS executable built,
while live OpenGL playback and packaged startup still need a desktop check
because sandbox restrictions blocked both.

Run the solver benchmark with `.venv/bin/python -m tests.physics_benchmark`.
For two seconds of simulated motion, MuJoCo took 129 ms with one body and
553 ms with 20 bodies. The Bullet baseline took 4 ms and 511 ms on the same
machine. See the [developer guide](README.md#testing) for test and build commands.
