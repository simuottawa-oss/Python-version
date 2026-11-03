# Development structure

The application is a Python package under `src/simuo/`. Keep imports qualified
with `simuo.` so launching from a different directory or running a test subset
uses the same module identities.

```text
src/simuo/
├── app.py                      # Application lifecycle and launch entrypoints
├── scene/
│   ├── model.py                # Objects, groups, and scene organization
│   └── persistence.py          # .simuO reading/writing; no GUI dependencies
├── editor/
│   ├── state.py                # Shared selection, edits, grouping, isolation
│   └── commands.py             # Reversible object and scene commands
├── rendering/
│   ├── context.py              # OpenGL format configured before QApplication
│   ├── camera.py               # Camera pose and mouse-ray unprojection
│   ├── meshes.py               # OBJ-compatible asset loading
│   ├── geometry.py             # Generated reference axes
│   ├── picking.py              # CPU bounds/triangle intersection
│   ├── ray.py                  # Ray data and debug line geometry
│   ├── shaders.py              # GLSL source
│   ├── outline.py              # Selection silhouette rendering
│   ├── manipulation.py         # Projection, gizmos, constraints, box geometry
│   ├── overlays.py             # Gizmo/selection painting in logical pixels
│   ├── selection_buffer.py     # Depth-tested GPU IDs for box selection
│   └── viewport.py             # Qt viewport, GPU resources, and input
├── ui/
│   ├── main_window.py          # Menus, toolbar, dialogs, and editor wiring
│   ├── startup.py              # New/open startup dialog
│   ├── docking.py              # Panel containers and saved workspace layout
│   ├── panel_registry.py       # Available panel factories and stable IDs
│   ├── theme.py                # Package-resource stylesheet loading
│   ├── viewport_tools.py       # Active tool rail
│   ├── viewport_options.py     # Option dropdowns and hover explanations
│   └── panels/
│       ├── properties.py       # Properties form and inspector widgets
│       └── hierarchy/
│           ├── panel.py        # Filtering, selection, navigation, and drops
│           ├── rows.py         # Object/group rows and inline renaming
│           ├── widgets.py      # Buttons, elision, and native drop surfaces
│           └── icons.py        # Vector icons
└── resources/
    ├── images/                 # Packaged application images
    └── styles/                 # Qt stylesheets for each major UI surface
```

`Assets/` remains a repository folder for sample/user mesh files. Application
images and styles are package resources, so they also work in installed builds
and when the working directory is outside the checkout.

## Responsibility boundaries

- **Scene** describes data and its file format. It must not import Qt, OpenGL,
  editor state, or UI modules. Loading returns data; the editor decides when to
  replace the current scene and clear history.
- **Editor** coordinates selection and changes using signals and undo commands.
  Object edits go through `EditorState` so undo, dirty tracking, and every panel
  receive the same updates. Selection and temporary isolation are view state.
- **Rendering** owns camera math, geometry, picking, shaders, and GPU resources.
  The viewport emits user intent; the main window connects it to editor state.
- **UI** contains widgets and application wiring. Panel content does not create
  its own selection/history model or manage the dock layout. `panel_registry.py`
  supplies factories to the generic docking manager.
- **Resources** contains appearance assets. Edit `.qss` files for surface styling
  rather than adding large stylesheet strings to constructors.

The hierarchy uses ordinary native row widgets because virtual Qt item-view
accessibility cells are unstable on the pinned macOS Qt version. Preserve that
choice when extending its rows; the coordination and widget code are separated
so behavior can evolve without replacing the accessibility surface.

## Running and installing

`python main.py` remains the source-checkout launcher. `python src/main.py` is
also retained as a thin launcher; all application code lives in `simuo`.

For development, install the package into the activated environment:

```bash
python -m pip install -e .
python -m simuo
# Or use the installed command:
simuo
```

`pyproject.toml` supplies package discovery, bundled resources, and the console
entrypoint. It reads runtime dependencies from `requirements.txt`, which remains
the single dependency list used by the setup checker. The checker itself stays
in `tools/` and can diagnose an environment without importing the editor.

## Tests

Tests are grouped by responsibility, with shared fixtures in `tests/support/`:

| Folder | Coverage |
| --- | --- |
| `tests/app/` | Launchers, import boundaries, and packaged resources |
| `tests/scene/` | Project-file compatibility and scene persistence |
| `tests/editor/` | Editor history and complete scene-editing workflows |
| `tests/ui/` | Hierarchy, groups, navigation, and docking |
| `tests/rendering/` | Picking, gizmo math/input, and native GPU selection checks |
| `tests/setup/` | Dependency/startup diagnostics; standard library only |
| `tests/support/` | Repository paths, Qt application setup, recording viewport |

Run the full suite from the repository root:

```bash
python -m unittest discover -s tests -t . -v
```

The existing `python -m unittest discover -s tests -v` command and default
`python -m unittest discover -v` also find the nested tests. To run a subset:

```bash
python -m unittest discover -s tests/ui -t . -v
python -m unittest tests.editor.test_history -v
python -m unittest tests.scene.test_persistence -v
python -m unittest tests.setup.test_environment -v
```

On macOS/Linux, a display-free run is:

```bash
QT_QPA_PLATFORM=offscreen python -m unittest discover -s tests -t . -v
```

GPU tests explicitly skip in that mode. Use a native desktop session to verify
OpenGL rendering, and avoid simultaneously interacting with another preview
while focus-sensitive GUI tests run. Qt tests use `tests.support.qt` to configure
OpenGL before the first `QApplication`; test files do not modify `sys.path`.
The source-checkout bootstrap is centralized in `tests/__init__.py`.

## Adding features

- Add a new panel under `ui/panels/`, then register its `PanelSpec` in
  `ui/panel_registry.py`. Keep IDs stable to retain users' saved layouts.
- Add scene fields and their defaults to `scene/model.py`, update persistence
  with backward-compatible defaults, and cover old and new files in
  `tests/scene/`.
- Add reversible operations through `editor/state.py` and its command objects;
  verify their undo/redo behavior in `tests/editor/`.
- Put reusable graphics math/loading outside `viewport.py`; put shaders in
  `rendering/shaders.py`, and extend `tests/rendering/` for rendering changes.
- Keep test helpers outside `test_*.py` files so discovery cannot accidentally
  collect fixtures as application tests.

## macOS troubleshooting

- **Python startup timeout / `init_import_site`:** if the project is in iCloud-synced
  storage, download it fully, move it outside iCloud, and recreate `.venv`.
- **Qt plugin errors:** recreate `.venv` outside cloud-synced storage and reinstall
  dependencies. The checker diagnoses problems without modifying installed libraries.
