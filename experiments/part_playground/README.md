# SimuO physics part experiment

An isolated proposal for physics-capable `.simuOPart` files, a sample solid cube,
and an independent interactive 3D renderer. No main application files or
dependencies are changed. This experiment does not use the production OBJ loader.

## Run

From the repository root:

```bash
python3 experiments/part_playground/viewer.py
```

Requires Python 3.10+ and the standard-library Tk bindings (`python3-tk` on Linux). No pip install, OpenGL, Qt, network,
or running SimuO instance is needed. A desktop display is needed for the window.
If Python reports `No module named tkinter`, use a Python installation with Tk.

The window initially pauses at release height. **Play** drops the cube onto the
floor; **Reset** restores its file-defined state; **Step** advances 1/240 second.

The viewer follows the scene editor's charcoal theme and workspace layout: top menus, a left toolbar, a central model viewport, a right **Part properties** panel, and a bottom status bar. Use **View → Part properties** to toggle the panel and **Frame part** (F) to restore the camera. The properties panel hides automatically in narrow windows to keep the model visible.
Drag to orbit, scroll to zoom, and use **Open part** to load an edited copy.
**Save SVG** exports the current view. Space toggles playback; R resets.

The lab's **File** menu also has **Save SimuO Part…** (Ctrl+S), which preserves the loaded definition, material/physics settings and custom properties. **File → Export** offers **OBJ…**, **STL…**, and **SVG Image…**. OBJ/STL contain the box's local geometry in metres, independent of its playback position; select metres when importing STL elsewhere. Mesh exports do not retain SimuO physics metadata. Cancelled dialogs and failed writes leave the current part intact.

Headless rendering and automated checks need only Python's standard library:

```bash
python3 experiments/part_playground/viewer.py --render /tmp/part-initial.svg
python3 experiments/part_playground/viewer.py --seconds 0.5 --render /tmp/part-falling.svg
python3 experiments/part_playground/viewer.py --seconds 3 --render /tmp/part-resting.svg
python3 -m unittest discover -s experiments/part_playground -v
```

Open SVG files in a browser or image viewer. These images use the same perspective
projection, face lighting, and depth ordering as the interactive canvas. A
checked-in `preview.svg` shows the supplied part at release height.

Use `python3 experiments/part_playground/viewer.py /path/to/custom.simuOPart` for a
custom part. Edit `appearance.color`, `geometry.size`, `material` coefficients,
and `properties` in a copy of the sample to explore different parts. Unsupported
fields or semantics fail validation rather than silently changing a simulation.
The sample material numbers are illustrative inputs, not certified material data.

## What is implemented

- Versioned JSON part loading, explicit SI units and axes, strict field and value
  validation, duplicate-key rejection, finite-number checks, custom metadata.
- Solid box geometry shared by the visual mesh and collision shape. Appearance
  comes from the file; physical coefficients come from the file as well.
- Density-derived or explicit positive mass; analytical center of mass (origin)
  and diagonal box inertia; static or dynamic bodies.
- A perspective software renderer with shaded faces, edges, a floor grid,
  orbit/zoom camera, live physical values, file loading and SVG export.
- Gravity, fixed-step semi-implicit Euler integration at 240 Hz, infinite floor
  contact, normal restitution and tangential Coulomb friction. Static bodies
  stay still. Reset reproduces the starting state.

The demo locks body orientation and has one body plus an infinite, immovable
floor at y=0. It does not implement torque, rotational dynamics, object/object
collisions, deformation, joints, or arbitrary meshes. Inertia is calculated and
displayed for future integration; this translation-only solver does not use it.
Floor contact uses the part's friction/restitution directly; a future engine
must define a two-material mixing rule. Very small bounces are stopped to avoid
contact chatter. Impacts are discrete, with penetration corrected each step;
this is not continuous collision detection. GUI stalls cap catch-up to 0.1 s
per frame, so simulation time may lag wall time under heavy load.

See the [prototype format](FORMAT.md) and the [production file formats](../../docs/file-formats.md).
