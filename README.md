# SimuO

Student built 3d Physics Simulator.

For part loading, rendering, property editing, persistence, and backend entry points,
see the [developer documentation index](Documentation/README.md) and
[SimuOPart developer guide](Documentation/Backend/SimuOPart.md).

## Windows setup

Use Windows 10/11 x64 with **Python 3.12 x64** from python.org (include Tcl/Tk in the installer). Install **Visual Studio Build Tools 2022** with **Desktop development with C++**, including the MSVC x64 compiler and Windows SDK. The pinned `pybullet` dependency requires a source build on Windows; its first installation can take several minutes.

Open PowerShell in the project folder:

```powershell
py -3.12 -m venv .venv
.\.venv\Scripts\python.exe -m pip install --upgrade pip setuptools wheel
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
.\Testing\Tools\run.bat
```

No environment activation or PowerShell execution-policy change is needed. After setup, double-click `Testing/Tools/run.bat` or run these commands:

```powershell
.\Testing\Tools\run.bat --new
.\Testing\Tools\run.bat "C:\My Projects\scene.simuO"
```

The launcher locates Python and the source relative to itself, so the project folder may contain spaces. To use another environment, set `$env:SIMUO_PYTHON = 'C:\path to environment\Scripts\python.exe'`. Project arguments are relative to the terminal's current folder. VS Code's run/debug and build tasks select the Windows interpreter automatically.

Install your Intel, AMD, or NVIDIA graphics driver with OpenGL 3.3 support. The Windows build uses Qt's native backend; the Linux `xcb` packages and settings below are not needed. Tests on a Windows machine:

```powershell
.\.venv\Scripts\python.exe -m unittest discover -s Testing/Developer_Tests -v
.\.venv\Scripts\python.exe Testing/Developer_Tests/gui_part_render.py
.\.venv\Scripts\python.exe Testing/Developer_Tests/gui_obj_import.py
.\.venv\Scripts\python.exe Testing/Developer_Tests/gui_physics_playback.py
```

The GUI scripts open test windows and need a working desktop graphics driver. `.github/workflows/windows.yml` runs the automated suites, tests the launcher from another folder, builds `SimuO.exe` on Windows, and checks packaged `--help` startup. That CI check does not verify interactive GPU rendering.

## Mint setup

Linux Mint 22 uses Python 3.12. Run these commands from the project folder:

```bash
sudo apt update
sudo apt install python3 python3-venv python3-pip python3-tk \
    libgl1 libegl1 libglx-mesa0 libglib2.0-0 libfontconfig1 libdbus-1-3 \
    libx11-xcb1 libxcb-cursor0 libxcb-icccm4 libxcb-image0 libxcb-keysyms1 \
    libxcb-randr0 libxcb-render-util0 libxcb-shape0 libxcb-xinerama0 \
    libxcb-xkb1 libxkbcommon-x11-0 libxi6 libxrender1 build-essential python3-dev
python3 -m venv .venv
.venv/bin/python -m pip install -r requirements.txt
./Testing/Tools/run.sh
```

Use a fresh `.venv`; the copied `path/to/venv` folders and existing Windows binaries are not installation dependencies. No Cython compilation is needed; the current renderer is Python.

The system packages above include the libraries required by [Qt's X11 backend](https://doc.qt.io/qt-6/linux-requirements.html). OpenGL 3.3 support from your graphics driver is required. Use Mint's Driver Manager if your hardware needs a proprietary graphics driver.

## Run

```bash
./Testing/Tools/run.sh                       # Startup menu
./Testing/Tools/run.sh --new                 # Open an empty editor directly
./Testing/Tools/run.sh path/to/scene.simuO    # Open an existing project
```

The launcher can be called by its absolute path from any folder, including paths containing spaces. Project arguments are resolved relative to your terminal's current folder. To use another environment:

```bash
SIMUO_PYTHON=/absolute/path/to/venv/bin/python ./Testing/Tools/run.sh
```

You can also run `.venv/bin/python src/main.py` directly. On Linux, the application defaults to Qt's `xcb` backend when an X display is available. The camera uses pointer recentering, so use Cinnamon's normal X11 session or XWayland in a Wayland session. An explicit `QT_QPA_PLATFORM` setting is respected.

If Qt reports that it cannot load `xcb`, check the system packages above. `QT_DEBUG_PLUGINS=1 ./Testing/Tools/run.sh --new` prints plugin diagnostics. For driver troubleshooting, `LIBGL_ALWAYS_SOFTWARE=1 ./Testing/Tools/run.sh --new` requests Mesa software rendering.

## MacOS setup

Run these commands from command prompt to build:

```bash
python3 -m venv .venv
.venv/bin/python -m pip install -r requirements.txt
.venv/bin/python -m PyInstaller --noconfirm src/main.spec
```

This produces a native executable, but the current configuration will not create a macOS .app bundle. 


## Models and projects

The Part Editor now opens in **3D** with a feature tree containing **Front**, **Right**, and **Top** planes. Select a plane (or a flat model face), choose **New Sketch**, draw/dimension an outline, then **Finish Sketch → Extrude**. You can also select a flat face and **Extrude** it directly. Orbit by dragging, pan with the middle mouse button, and zoom with the wheel. Try `Assets/feature_demo.simuOPart`. See [feature editor guide](Documentation/Frontend/feature_editor.md) for the current workflow and editable feature-file format.

The opening screen also provides **New Part** and **Open Part…**. The Part Editor lets you draw connected lines and three-point arcs, close an outline into a face, and apply line-length or arc-radius dimensions in millimeters. Set a thickness and save an editable `.simuOPart`, then import it into a scene. Open `Assets/sketch_plate.simuOPart` or `Assets/arc_plate.simuOPart` for examples, or run `./Testing/Tools/run.sh --part-editor`. See [sketch editor guide](Documentation/Frontend/part_editor.md) for controls, file format and scope.

For an arc, select **Draw arcs** and click the start, a point on the curve, then the end. When connected to an existing segment, the last endpoint is reused as the start. Select the arc and choose **Add dimension…** to enter its **radius**, shown as `R` in mm. Radius edits keep endpoints fixed; the minimum radius is half their separation. Esc cancels a pending arc. Lines and arcs can be mixed in one outline.

In the **SimuO Part editor**, use **File → Save SimuO Part** (Ctrl+S) or **Save SimuO Part As…** to keep editable sketches, dimensions, supports, extrusions and part properties in a `.simuOPart` file. **File → Export → OBJ… / STL…** writes the joined solid's mesh. Extrude at least one closed sketch before exporting; unfinished sketches can still be saved as parts. Mesh export keeps the current document, save path and unsaved changes intact.

Use **Draw lines** to sketch and **Select line** to choose an edge, then **Add dimension…** to enter its length. Dimensions are manual: only dimensioned lines show labels; other lines show a dash in the table. Use **Update dimension** or **Remove dimension** for the selected line. Dimensions are saved in the `.simuOPart` file. **Frame sketch** (F) fits the drawing. **View → Part properties** shows or hides the scrollable properties panel, which hides automatically in narrow windows. **Help → Controls and workflow** (F1) explains drawing, dimensions, saving, and export.

Use **Constraints → Make horizontal / Make vertical** on selected straight lines. Ctrl-click lines in the sketch or segment table to select two or more, then choose **Make equal**. The same controls are in the properties panel. Geometric relations and length/radius dimensions appear in the **Constraints** list: select one and use **Delete selected constraint**, the context menu, or Delete/Backspace while that list is focused. Removing a constraint keeps the geometry in place; Ctrl+Z restores it. Constraints save with the part, and conflicting additions leave the sketch unchanged.

OBJ/STL exports contain local geometry in **metres**, centered like the rendered part. STL has no embedded unit field, so select metres when importing it into another program (or scale by 1000 for millimetres). These mesh formats do not preserve editable dimensions or SimuO physics properties.

Use **Import File** to add a `.simuOPart` model from `Assets`. Both existing Wavefront OBJ parts and the new versioned JSON parts are supported. Try `Assets/aluminum_cube.simuOPart`: its dimensions and color come from the file, and the camera frames it automatically. JSON v1 currently supports solid boxes; existing OBJ meshes continue to render as before.

JSON parts use `"format": ".simuOPart"` and `"version": 1`. Older JSON files with `"format": "simuo.part"` need that identifier updated to `.simuOPart`.

You can also import `.obj` files. Confirm **Create SimuO Part** to create a separate `.simuOPart` copy using the supported OBJ mesh format. The source OBJ is kept intact; geometry is preserved, while OBJ material/texture sidecars are not imported. These mesh parts do not acquire the JSON box format's physical properties automatically.

Unsaved imports appear in the **Temporary parts** panel, which lists their names and temporary directory. **Save** or **Save As** first asks for the scene location if needed, then asks where to save each temporary part. Canceling any part dialog cancels the scene save. Successful saves update the scene to reference permanent part files using relative paths. Closing the editor or replacing the scene prompts you to save or discard temporary parts. Discarded parts are removed from the temporary directory.

JSON parts carry density, friction, restitution, mass/inertia and custom properties, available through each scene object's `part` definition. The editor loads their starting position and velocity. **Save** and **Save As** write `.simuO` scene files with instance transforms, motion and paths relative to the scene file. Material and custom properties are reloaded from the referenced part, so keep the part files when moving a project. Geometry and asset definitions are not embedded in the scene.

The design and v1 field contract are in `Testing/Part_Playground/FORMAT.md`. The production loader is `src/part_format.py`; unlike the floor-contact experiment, the editor allows parts below y=0. Unsupported versions, malformed parts, and geometry outside the renderer's numerical range report an error.

When opening older projects with stale absolute paths or Windows paths, SimuO also looks for the model beside the project, in its `Assets` subfolder, and in the application's bundled `Assets` folder. Missing files produce an error dialog.

## Render physics

Click **Render** on the top menu bar beside **File**, or press **Ctrl+R** to open a separate live physics window for the current scene. Playback starts automatically and simulates a copy, preserving the editor's original objects. Use **Pause/Play**, **Step** (1/240 s), **Reset**, **Frame scene**, the gravity control, and the optional floor at y=0. P toggles playback, R resets, and F frames the scene in that window. The normal camera controls also work there.

The Bullet solver handles gravity, linear/angular motion, box-to-box collisions, floor contact, bounce, friction and static bodies. Part dimensions, density/explicit mass, inertia and material coefficients drive the simulation. Legacy OBJ-based parts default to static mesh colliders; enable **Dynamic body** in Properties to simulate them using a convex hull and a default mass of 1 kg. Custom metadata has no physical effect. See [physics backend guide](Documentation/Backend/physics_world.md) for units, scaling and limitations.

PyBullet is included in the project requirements and installed on this device. On Python versions without a matching binary wheel it builds from source, which is why the setup includes compiler/Python headers. To update an older environment, run `.venv/bin/python -m pip install -r requirements.txt`.

## Build an executable (optional)

To build **on Windows**, run:

```powershell
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
.\.venv\Scripts\python.exe -m PyInstaller --noconfirm src/main.spec
.\dist\SimuO.exe
```

Build each executable on its target OS; a Linux executable cannot run on Windows. The Windows executable bundles Python and dependencies, so recipients do not need Python or C++ build tools installed, but do need a compatible graphics driver.

Build on Linux; existing Windows `.pyd` files cannot run on Linux.

```bash
.venv/bin/python -m pip install -r requirements.txt
.venv/bin/python -m PyInstaller --noconfirm src/main.spec
./dist/SimuO
```

`src/main.spec` is the single build specification and locates sources and assets relative to its own location. The executable bundles the logo, sample models, and CustomTkinter data. The target machine still needs a desktop session, the system libraries above, and an OpenGL 3.3 driver.

On Linux, verify the packaged startup screen and logo on an X11/XWayland desktop with `wmctrl` available:

```bash
.venv/bin/python Testing/Developer_Tests/gui_packaged_startup.py dist/SimuO
```

## Controls

Open **Edit → Physics Properties** to choose a part. Check **Dynamic body** to let it move under physics, or uncheck it to keep it static. You can also edit **Bounce** (0–1) and starting **Velocity X/Y/Z** in m/s. Click **OK** to apply or **Cancel** to leave it unchanged. These values are saved with the scene for that object; the original part file stays intact. Open a new **Render** window to simulate the updated values. Dynamic legacy meshes use a convex collision hull (which fills concavities) and a default mass of 1 kg.

Use the [scene panels and viewport tools guide](Documentation/Frontend/scene_panels.md) for docking, selection, transforms, and shortcuts. **Help → Controls** is also available in the editor.

**New Project**, **Open Project**, and closing the editor offer **Save**, **Discard**, or **Cancel** when there are unsaved changes. Cancelling or failing to save keeps your scene open. If a save fails, choose a writable folder and try again; the scene's previous project path is retained.

- `W` / `S`: move forward / backward
- `A` / `D`: move left / right
- `Left` / `Right` arrows: turn the camera left / right (editor and physics window)
- `Space` / `C`: move up / down in the editor. Physics playback uses `Space` / `Ctrl`.
- Click a part to select it, then choose Move, Rotate, or Scale in the viewport toolbar. Changes are saved with the scene.
- Hold the right mouse button and move the mouse: look around
- `Esc`: close the editor

## Testing

Production automated checks: `.venv/bin/python -m unittest discover -s Testing/Developer_Tests -v`. Desktop renderer integration: `.venv/bin/python Testing/Developer_Tests/gui_part_render.py`. Physics playback integration: `.venv/bin/python Testing/Developer_Tests/gui_physics_playback.py`. The independent playground checks run with `.venv/bin/python -m unittest discover -s Testing/Part_Playground -v`. Desktop checks open and close their own windows. See the [developer documentation](Documentation/README.md) for implementation details and test locations.

On Mint, check startup **New Scene**, **Import Scene**, and closing the startup menu. In the editor, import a model, save, reopen, use **Save As**, reposition and rotate objects, and use the camera before and after switching windows. Also check launching from another working directory and opening a project whose folder contains spaces. Move a scene together with its model files and reopen it to check relative paths. If building a release, repeat startup and model loading with `dist/SimuO`.
