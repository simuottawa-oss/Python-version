# Structural analysis

Open **New Scene → Structural Analysis**, run `python src/main.py --structural`,
or pass a structural `.simuO` project to the launcher. This workspace analyzes one
connected solid with static, isotropic, small-displacement linear elasticity.

## Set up a solid

1. Choose **Import solid** for a `.simuOPart`, OBJ or STL file. Native JSON
   versions 1–3 use metres. Legacy OBJ-text parts, OBJ and STL use the selected
   import units: metres (default), millimetres, centimetres or inches. The
   dimensions and volume shown after import are in SI units.
2. Select **Material** in the Analysis Hierarchy. The shared Material inspector
   offers common grades and Custom, with properties in GPa and kg/m³. It is the
   same component used by the Scene editor. See [Material presets](materials.md).
   Native density is retained by From Part; choose a preset or complete Custom
   elasticity before solving. Gravity starts off.
3. Select faces with the viewport or Surface Selection list (Ctrl adds), then use
   **Fix Faces** to create a complete displacement restraint. Supports can be
   renamed or reassigned in Properties.
4. Choose **Add Load…**. **Force at a point** places a marker at an exact clicked
   surface location; enter XYZ force in N and select Add Point Force. **Force over
   a face** distributes a total XYZ force uniformly across selected faces.
   **Pressure on a face** acts perpendicular to selected faces; choose inward or
   outward direction and Pa, kPa, or MPa. The latter defaults to kPa. Arrows preview
   the load before committing it.
5. Select Mesh, choose element size in metres, and Generate Mesh. Then Run Analysis.
   The mesh view shows the surface of the tetrahedral volume mesh. Right-drag looks
   around, WASD moves, F frames the selection and Shift+F frames the solid.

The hierarchy and Properties docks share the Scene editor's styling and controls.
Results open in a bottom dock, with Summary and Beam Diagram tabs. View → Reset
Layout restores the default arrangement. Each workspace keeps separate layout
preferences. Setup edits support Undo/Redo; Escape cancels unfinished placement.
Select a load marker or hierarchy entry to edit, rename, reposition or delete it.

Sources must be closed, orientable, nondegenerate manifold triangle surfaces.
The importer repairs winding, retains double precision separately from GPU
buffers, and preserves source files, through-holes and enclosed cavities.
Disconnected material bodies, intersections and invalid surfaces are rejected.
No convex-hull approximation is used. Gmsh may reject surfaces it cannot
parametrize; its diagnostic is shown without substituting geometry.

## Results and beam diagrams

The stress view uses a lookup texture: zero is green, half the displayed maximum
is yellow, and the maximum is red. The numeric legend is in Pa. Its field is
**averaged von Mises stress**, computed after projecting the tensor components
onto a continuous linear field. The separately reported unaveraged peak uses
the original element quadrature stresses. An unloaded model stays green; a
uniform nonzero stress field is red. Peak displacement is reported in metres.

To request a beam diagram, select every patch on the clamped end and assign it
as the beam clamp; select every patch on the opposite end as the free end. There
must be exactly one complete end clamp and no other supports. Ends must be
parallel, the beam straight and its cross-section constant. An unsupported beam
configuration leaves the 3D stress analysis available and reports the reason.

Beam x points from clamp to free end. Local y is projected world Y, or projected
world Z when the beam runs along Y. Local z = x × y. The diagram plots signed
local My and Mz, in N·m, at 99 interior stations. These are the moments of the
traction σn on the **+x section normal**: for a beam along world +X with a
downward end force, Mz is negative. Root force and moment reactions are reported
separately in world XYZ about the clamped-end area centroid.

Each section intersects the actual tetrahedra; stress is evaluated from the
quadratic displacement gradient at degree-two triangle quadrature points.
The diagram is not inferred from a fitted beam equation or averaged display
stresses. Refinement may be needed near clamps and concentrated load changes.

An ideal point force has a local stress singularity: stress immediately at its
location can increase as the mesh is refined. The result summary identifies this;
displacement, reaction balance and section moments away from the point remain
useful. Point forces act at one mesh node, including points placed on edges or
corners. Coincident forces share a node and add together.

## Save, reopen and cancel

Save a version 2 `.simuO` project with `project_type: "structural"` to retain
all input data, named loads, exact material values and source-anchored point
locations. References are relative when possible, with an absolute-path fallback
across Windows drives. Writes are atomic. Meshes and results regenerate after
reopening. Legacy `.simuOAnalysis` files still open; Save offers a new `.simuO`
file. Import Scene and recent-project cards route both project types automatically.

A missing geometry file must be restored to its saved reference or imported as
a new analysis. Changed geometry and incompatible reconstructed patches require
boundary reassignment. Material, load and support edits invalidate results;
geometry, point-location and element-size edits also invalidate meshes. Meshing and solving
run in isolated spawned processes. Cancel and window close terminate the worker;
results from obsolete input revisions are discarded.

## Numerical implementation and checks

`simuo.structural` separates validated models, import, meshing, solving,
postprocessing, beam integration, persistence and workers from Qt/OpenGL.
Gmsh follows the [discrete-surface workflow](https://gmsh.info/doc/texinfo/gmsh.html#t13):
classify, parametrize, construct outer and cavity surface loops, and tetrahedralize.
Positive element volumes, full surface coverage and agreement with source volume
are checked. Source triangle membership, rather than entity numbers, identifies
patches across refinement.

The solver uses [scikit-fem](https://scikit-fem.readthedocs.io/en/stable/api.html)
vector P2 displacement elements on linear tetrahedra and a SciPy sparse direct
solve. Both vertex and edge degrees of freedom are constrained. Surface and
gravity loads are integrated consistently. Reactions come from the original
uncondensed stiffness system. Six rigid modes, finite results, free residuals,
and force/moment balance are checked; accepted normalized errors are ≤ 1e-8.

Run the regression suite with the documented Python 3.12 environment:

```bash
.venv/bin/python -m unittest discover -s tests -t . -v
.venv/bin/python src/main.py --structural-smoke
```

The backend tests exercise real Gmsh, cavities/holes, refinement, an affine
displacement patch, axial response (1%), zero load, pressure/gravity equilibrium,
and a slender cantilever's displacement and interior moments (5%). Offscreen Qt
tests cover setup persistence, worker failures/cancellation and invalidation.
Use `python -m tests.desktop.gui_structural` with a desktop/OpenGL driver for
interactive patch selection and the rendered lookup texture. Packaged builds
expose the same `--structural-smoke` check and include Gmsh's native library.

Assemblies, contact, plasticity, dynamics, painted regions and stored result
archives are outside this version. Near-incompressible materials may require a
different formulation; this version uses displacement elements.
