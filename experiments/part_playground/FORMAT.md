# An ideal SimuO part file

## Design

A part should describe a reusable physical asset, not just its triangles. It
should have a stable identifier and a versioned, validated contract for geometry,
appearance, material, collision, and mass properties. A simulation should be able
to load the same part without needing the renderer or the original CAD program.

Use UTF-8 JSON as the initial `.simuOPart` format: it is inspectable, editable,
diffable, and supported by Python without a new dependency. For large models,
eventually use a package containing a JSON manifest and portable mesh/texture
assets. Keep the logical schema independent of the package. Do not embed scripts
or executable expressions in properties. Unknown simulation semantics must be
rejected; optional metadata can be preserved.

An ideal full format should include:

| Area | Contents and purpose |
| --- | --- |
| Identity | Format tag, schema version, stable part ID, human name, description, source/license and revision. IDs identify assets; scene instances need separate IDs. |
| Units and frame | SI meters, kilograms, seconds; right-handed axes, +Y up; local origin and unambiguous rotation convention. Convert imports once at the boundary. |
| Geometry | Analytic primitives or indexed triangle meshes, with normals/UVs and material assignments. Use content hashes and relative paths for external resources. |
| Appearance | Base color and optional PBR roughness, metallic value, opacity, textures. Visual appearance must not imply density or friction. |
| Collision | Primitive/compound or convex collision shapes, local transforms, collision layers, margins and triggers. Keep detailed visual meshes independent of simplified collision shapes. |
| Material | Density (kg/m³), dimensionless friction and restitution; optional solver-defined thermal, elastic, electrical or fluid properties with explicit units and valid ranges. |
| Mass properties | One declared mass source: derive from density/volume or use explicit kg. Local center of mass and a symmetric positive-definite 3×3 inertia tensor (kg·m²), or a declared derivation method. Imported shells need an explicit thickness/volume policy. |
| Body behavior | Dynamic/static/kinematic type, gravity participation, damping and allowed degrees of freedom. Explicit capability requirements prevent an engine ignoring unsupported behavior. |
| Interfaces | Named local attachment frames, joint limits and connection surfaces for assemblies, expressed in the same coordinate frame. |
| Extensions | Namespaced custom properties and versioned capability/extension IDs; required physical extensions fail on unsupported engines. |

Keep global gravity, solver settings, floor/environment, world transforms and
live velocities in a **scene**, not in the reusable part definition. For this
self-contained test, `initial_state` supplies spawn defaults; scene-instance
values should override them in a future integration. Never save transient
simulation state over immutable asset definitions.

Store mass/inertia exactly once or define precedence explicitly. Density-derived
mass should be recomputed after dimension changes; a dimensionless visual scale
must not silently resize a physical collider. Prefer baking instance scale into
geometry and recalculating physical properties. Quaternions should use an
explicit order such as `[x,y,z,w]`, normalized, for future orientations.

## Exact prototype v1 contract

`aluminum_cube.simuOPart` is a complete, working example. V1 intentionally
implements a narrow subset of the ideal format. Fields are required except
where marked optional. Additional core fields are errors.

| Field | Accepted value / meaning |
| --- | --- |
| `format` | Exact string `.simuOPart`. |
| `version` | Integer `1`; other versions fail before loading. |
| `id`, `name` | Nonempty strings. |
| `description` | Optional nonempty string. |
| `units` | Exactly `{"length":"m","mass":"kg","time":"s"}`. |
| `coordinates` | Exactly `{"handedness":"right","up":"+Y"}`. |
| `geometry` | `{"type":"box","size":[x,y,z]}`; finite positive full dimensions in meters, centered at local origin. Solid, homogeneous box. |
| `appearance` | `{"color":"#RRGGBB"}`. |
| `material` | Nonempty `name`, positive finite `density` in kg/m³, finite `friction >= 0`, finite `restitution` in [0,1]. Coefficients are dimensionless. Friction is not limited to 1. |
| `physics.body_type` | `dynamic` or `static`. Static still describes the material mass, but the solver does not integrate it. |
| `physics.mass_source` | `density` computes `density*x*y*z`; `explicit` requires positive finite `physics.mass` in kg. Explicit mass takes precedence over density for inertia. Density remains descriptive in explicit mode. |
| `physics.collider` | Exact string `geometry`: collision box matches the rendered box. No separately offset shape. |
| `initial_state.position` | Three finite numbers in meters. Center Y must be at least half the box's Y dimension, since the demo floor is y=0. This floor restriction belongs to this demo's scene, not to future generic assets. |
| `initial_state.velocity` | Three finite numbers in m/s; must be zero for static parts. No angular state in v1. |
| `properties` | Optional JSON object with namespaced keys, e.g. `demo:temperature_K`. Values are preserved and shown but have no physical effect. Units belong in metadata keys/documentation until an extension schema defines them. |

`physics.mass` is forbidden in density mode. JSON NaN/Infinity, duplicate keys,
booleans where numbers are expected, non-finite computed mass/inertia, and unknown
fields are rejected. `part.py::load_part` is the executable validation contract.
Metadata never creates new physical behavior merely by naming a property.

The supplied 0.2 m cube has volume 0.008 m³ and mass 21.6 kg at 2700 kg/m³.
Its center of mass is `[0,0,0]`; its inertia tensor is diagonal with
`Ixx=Iyy=Izz=0.144 kg·m²`. For any box, `Ixx=m*(y²+z²)/12`, with cyclic
permutations for the other axes. The initial center height is 1.1 m, so the
bottom starts 1 m above the floor. Gravity is [0,-9.81,0] m/s² in the demo scene.

## Integration with today's SimuO

**Migration update (2026-11-02):** the main editor now implements JSON/OBJ content
dispatch through `src/part_assets.py` and production v1 validation through
`src/part_format.py`. Import `Assets/aluminum_cube.simuOPart` to use it. The
original proposal below describes the boundary this migration implements;
its statement about incompatibility applies to the original OBJ-only snapshot.
The experimental viewer stays independent. The production loader removes the
demo-floor restriction and adds GPU numerical-range checks. Main-editor physics
playback and non-box JSON geometry remain future work.

Today's `.simuOPart` files contain OBJ text. The new JSON file uses the same
extension as an experiment, but is **not** compatible with the existing loader.
Keep both readers: detect a leading JSON object, validate `format` and `version`,
then dispatch to a version-specific loader; otherwise use the legacy OBJ path.
Malformed JSON must report its error rather than falling back to OBJ.

The new loader should return a domain object that owns visual geometry,
colliders and validated material data; the renderer consumes a mesh/material
view and the physics engine consumes a rigid-body view. Scenes reference the
asset ID/path and store instance transforms and state. Do not make the physics
engine infer mass from the current GPU mesh or renderer scale.

Next steps are a formal schema, a production adapter behind a format dispatch,
explicit collision/visual mesh separation, and a rigid-body solver with rotation
and tested mass/inertia handling. Introduce incompatible semantics through a new
version or a required extension, rather than reinterpreting existing fields.
