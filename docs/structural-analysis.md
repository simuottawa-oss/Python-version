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
3. Choose **Fixed Face**, **Pinned Face**, or **Fixed Point** in the viewport tool
   rail, then click the solid. A fixed face prevents translation at all face
   vertices and edges. A fixed point restrains one exact surface location.
   A pinned face moves as a rigid face about its area centroid: the centroid
   cannot translate, and all three rotations are free. A single point or face
   pin cannot stabilize a free solid; Properties explains any remaining rigid
   motions. Select a face support in the hierarchy to switch Fixed/Pinned.
4. Choose **Add Load…**. **Force at a point** places a single marker at the clicked
   surface location. **Force over a face** distributes a total XYZ force across
   a face. **Pressure on a face** acts perpendicular to a face, inward or outward,
   with Pa, kPa, or MPa units. Clicking creates a zero-valued condition and selects
   it in Properties. Enter the force or pressure there; finishing an edit applies
   it automatically. The tool stays active for repeated placement; Escape or
   Select exits it. Ctrl-click extends the selected matching face condition.
   Clicking the same target selects its condition. Use **Duplicate Load** to add
   another load at that target deliberately.
5. Select Mesh to choose element size in metres. **Generate Mesh** creates the
   tetrahedral mesh without calculating results. Then choose **Run Analysis**
   to calculate displacement, stress and reactions using that mesh;
   its availability and Properties explain missing setup or insufficient restraints.
   The mesh view shows the surface of the tetrahedral volume mesh. Right-drag looks
   around; WASD moves, Space moves up and Alt moves down while the viewport has
   focus, without right-click. F frames the selection; Shift+F frames the solid.

The hierarchy and Properties docks share the Scene editor's styling and controls.
Results open in a bottom dock, with Summary and Beam Diagram tabs. View → Reset
Layout restores the default arrangement. Each workspace keeps separate layout
preferences. Setup edits support Undo/Redo, with one step per completed edit.
Select a load marker or hierarchy entry to edit, rename, reposition or delete it.

Sources must be closed, orientable, nondegenerate manifold triangle surfaces.
The importer repairs winding, retains double precision separately from GPU
buffers, and preserves source files, through-holes and enclosed cavities.
Disconnected material bodies, intersections and invalid surfaces are rejected.
No convex-hull approximation is used. Gmsh may reject surfaces it cannot
parametrize; its diagnostic is shown without substituting geometry.

## Results and beam diagrams

The stress view uses a lookup texture: zero is green, half the displayed maximum
is yellow, and the maximum is red. Results Properties offers a full range or
a custom maximum; values above a custom maximum saturate red and the legend
labels saturation. Scaling never changes the computed field or raw peak.
The numeric legend is in Pa. Its field is
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
boundary reassignment. **Generate Mesh** only creates the mesh. Calculations
run only when you choose **Run Analysis**. Input edits apply immediately in
Properties and invalidate old results; they do not start meshing or analysis. Material, force, pressure, gravity
and support changes reuse the mesh; names and selections preserve results. Mesh
coverage depends on geometry, mesh settings and actual required point locations,
not condition IDs or values. Moving a point needs a mesh update only if that
location has no boundary vertex; deleting points retains harmless extra nodes.
Meshing and solving run in isolated spawned processes. Cancel and window close
terminate the worker;
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
uncondensed stiffness system. Sparse displacement transformations implement face-pin constraints. Individual
support forces and moments are reported about each support origin; a free pin
transmits zero net moment about its centroid. Six rigid modes, finite results, free residuals,
and force/moment balance are checked; accepted normalized errors are ≤ 1e-8.

Run the regression suite with the documented Python 3.12 environment:

```bash
.venv/bin/python -m unittest discover -s tests -t . -v
.venv/bin/python src/main.py --structural-smoke
```

The backend tests exercise real Gmsh, cavities/holes, refinement, an affine
displacement patch, axial response (1%), zero load, pressure/gravity equilibrium,
and a slender point-loaded cantilever's displacement, signed interior stresses
and moments (5%). Fixed points, freely rotating face pins, rigid modes and
mesh reuse have numerical regressions. Offscreen Qt
tests cover setup persistence, worker failures/cancellation and invalidation.
Use `python -m tests.desktop.gui_structural` with a desktop/OpenGL driver for
interactive patch selection and the rendered lookup texture. Packaged builds
expose the same `--structural-smoke` check and include Gmsh's native library.

Assemblies, contact, plasticity, dynamics, painted regions and stored result
archives are outside this version. Near-incompressible materials may require a
different formulation; this version uses displacement elements.
