# File formats

## Scenes

A `.simuO` scene saves JSON with `version: 1` and an `objects` array. Each
object stores its ID, name, external `meshPath`, position, rotation, scale,
motion, body type, and bounce. Optional `editor` values store visibility and
selection lock. Top-level `groups` and `hierarchy_order` store the hierarchy by
ID. Older scenes can omit IDs and panel metadata.

Part references are relative to the scene when possible. Move a project
together with its referenced models. For legacy paths, the loader also checks
beside the project, in the project's `Assets` directory, and in the bundled
`Assets` directory. Material and custom properties are loaded from the
referenced part. Scene saves replace each file atomically, and saving multiple
parts and a scene can involve several separate writes.

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
