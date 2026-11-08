# SimuO documentation

- [Scene editor](scene-editor.md) covers panels, selection, transforms, and physics playback.
- [Part editor](part-editor.md) covers sketches, extrusions, constraints, and export.
- [File formats](file-formats.md) covers scenes, parts, and compatibility.
- [Installation](../README.md) covers Windows, Linux Mint, and macOS.

## Project layout

| Location | Responsibility |
| --- | --- |
| `src/main.py` | Source and PyInstaller entry point |
| `src/simuo/app.py` | Command-line routing and startup |
| `src/simuo/ui/` | Scene window, panels, workspace settings, and Part Editor widgets |
| `src/simuo/editor/` | Scene selection, hierarchy, and undo/redo |
| `src/simuo/project/` | Scene model, file reference resolution, and temporary imports |
| `src/simuo/parts/` | Part validation, sketch and feature geometry, and export |
| `src/simuo/rendering/` | Scene editor viewport, picking, selection outlines, and gizmos |
| `src/simuo/physics/` | Bullet simulation and the separate playback viewport |
| `src/simuo/resources/`, `Assets/`, `Images/` | Styles, sample models and scenes, and app images |
| `tests/` | Unit tests, integration tests, desktop checks, and fixtures |
| `experiments/part_playground/` | Standalone physics prototype with its own checks |
| `Testing/Tools/` | Existing Windows and Unix launch commands |

The scene window connects its panels and viewport to `EditorState`. Add
dockable panels through the [panel registry](../src/simuo/ui/panel_registry.py).
Use a stable panel ID so existing saved workspaces can restore it.

`PartAsset` holds CPU geometry and an optional reusable `Part` definition.
`SceneObject` holds instance transforms, motion, and physics overrides.
Rendering uses flat float32 position and normal data, six values per vertex and
three vertices per triangle. The scene viewport uses these assets directly.
Physics playback simulates a snapshot and uses its own viewport. The Part Editor
has a separate 3D preview for its editable feature model.

## Testing

Run the suite from the repository root with the Python environment you installed:

```bash
.venv/bin/python -m unittest discover -s tests -t . -v
```

On Windows, replace `.venv/bin/python` with `.\.venv\Scripts\python.exe`.
`tests/unit` covers model and math behavior, including the Bullet solver.
`tests/integration` runs Qt offscreen and covers editing, persistence, and
launcher behavior. Both suites use the normal dependencies, including PyBullet.
The playground runs independently with
`python -m unittest discover -s experiments/part_playground -v`.

Run desktop checks with a working graphics driver from the repository root:

```bash
.venv/bin/python -m tests.desktop.gui_part_render
.venv/bin/python -m tests.desktop.gui_obj_import
.venv/bin/python -m tests.desktop.gui_point_dragging
.venv/bin/python -m tests.desktop.gui_physics_playback
```

The headless CI jobs cover Windows and macOS. The Windows workflow also checks
launching from a different working directory, builds the executable, and runs
its `--help` command. Use the desktop checks to exercise interactive OpenGL.

## Build an executable

Build on the OS that will run the executable:

```bash
.venv/bin/python -m PyInstaller --noconfirm src/main.spec
```

Run `dist/SimuO` on Linux or macOS, or `.\dist\SimuO.exe` on Windows.
The macOS build produces an executable. On Linux, a desktop with `wmctrl` can
check the packaged startup window and logo with
`.venv/bin/python -m tests.desktop.gui_packaged_startup dist/SimuO`.

On Linux, `QT_DEBUG_PLUGINS=1` prints Qt plugin diagnostics.
`LIBGL_ALWAYS_SOFTWARE=1` requests Mesa software rendering for troubleshooting.
