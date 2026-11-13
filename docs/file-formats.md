# File formats

## Projects: scenes and structural designs

Both workspaces save `.simuO` JSON projects. New projects use `format: ".simuO"`,
`version: 2`, and `project_type: "scene"` or `"structural"`. Import Scene, recent
projects, command-line opening and File → Open inspect this header to choose
an editor. Unknown project types/versions and malformed payloads are rejected.

A scene stores an `objects` array, `groups`, and `hierarchy_order`. Each object
stores its ID, name, external `meshPath`, position, rotation, scale, motion,
body type (`static`, `dynamic`, or `kinematic`), bounce and optional `material`
override. A material snapshot contains name, preset ID, Young's modulus in Pa,
Poisson ratio and density in kg/m³. `material: null` inherits the source part.
Optional `editor` values store visibility and selection lock. Existing version
1 scenes, including files with an objects array and no explicit version, remain
readable. Subsequent saves use the version 2 header.

Structural projects store a `setup` object containing the geometry reference
and fingerprint, import units, material snapshot, supports, named surface and
point loads, gravity, mesh settings and optional beam configuration. Point loads
store a stable identifier, source-triangle index, barycentric location and XYZ
force in N. Their mesh-node numbers are regenerated and are never persisted.
Meshes and results are also regenerated after opening.

Legacy `.simuOAnalysis` version 1 remains readable. Save offers a `.simuO`
destination without overwriting the legacy file. The extension identifies a
project file; the JSON project type identifies its workspace. File → Open of a
different type opens its corresponding window and preserves the current project.

References are relative to the project when possible. Move a project together
with its referenced geometry. Legacy scene references can also recover beside
the project or in project/bundled Assets folders. Structural geometry retains
its fingerprint checks and requires boundary reassignment after source changes.
Saves replace files atomically; a scene with multiple parts may involve separate
atomic writes for each file.

## Parts

The loader detects content inside `.simuOPart` files:

| Format | Geometry | Editing |
| --- | --- | --- |
| JSON v1 | `box` | Opens as a rectangular sketch and symmetric extrusion |
| JSON v2 | `sketch` | Opens as feature history |
| JSON v3 | `feature_part` | Current editable feature history |
| Legacy OBJ text | Vertices and faces | Imports as a mesh |

JSON parts require `format: ".simuOPart"` and the corresponding version,
identity, units, coordinates, geometry, appearance, material, physics, and
initial state. Use metres, kilograms, and seconds, and right-handed Y-up
coordinates. Colors use `#RRGGBB`. Density sets mass from volume, or the part
can supply an explicit mass. Optional custom keys belong under `properties`.

Use the [v1 box](../Assets/aluminum_cube.simuOPart),
[v2 sketch](../Assets/sketch_plate.simuOPart), and
[v3 feature part](../Assets/feature_demo.simuOPart) as examples.
[Part validation](../src/simuo/parts/part_format.py) defines the accepted
fields. [Feature geometry](../src/simuo/parts/feature_geometry.py) defines
the supported sketch planes, face references, and ordered extrusion rules.
Drafts can open in the Part Editor. Scene import requires solid geometry.

Scene rotations use degrees in `Rx * Ry * Rz` order, angular velocity uses
radians per second, and scale is dimensionless. The sketch and extrusion UI
displays millimetres.
