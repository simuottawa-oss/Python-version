# SimuO OpenGL Renderer

## Setup and run

The pinned Qt dependency supports **CPython 3.10–3.14**.
A graphics driver supporting **OpenGL 3.3 Core** is required.

Run your OS's commands below from the project root. Confirm the first command
reports Python 3.10–3.14 before continuing.

### Windows (PowerShell)

```powershell
py -3 --version
py -3 -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -r requirements.txt
python tools/check_setup.py --graphics
python main.py
```

### macOS (Terminal)

```bash
python3 --version
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -r requirements.txt
bash tools/check_setup.sh --graphics
python main.py
```

### Linux (Bash)

```bash
python3 --version
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -r requirements.txt
python tools/check_setup.py --graphics
python main.py
```

If your default Python is outside the supported range, select an installed
supported version instead, such as `py -3.12` on Windows or `python3.12` on
macOS/Linux, for the version check and environment creation.

The setup check briefly opens a window to test rendering; omit `--graphics` for
environment checks only. In a new terminal, activate `.venv` again before running
`python main.py`.

## macOS troubleshooting

- **Python startup timeout / `init_import_site`:** if the project is in iCloud-synced
  storage, download it fully, move it outside iCloud, and recreate `.venv`.
- **Qt plugin errors:** recreate `.venv` outside cloud-synced storage and reinstall
  dependencies. The checker diagnoses problems without modifying installed libraries.

## Project layout

- `main.py`: convenience launcher.
- `src/`: application, startup menu, scene, ray casting, and OpenGL renderer.
- `Assets/`: sample meshes in `.simuOPart` format.
- `Images/`: application images.
- `requirements.txt`: Python runtime dependencies.
- `tools/check_setup.py`: environment checker and optional graphics test.
- `tools/check_setup.sh`: macOS wrapper for checking Python startup failures.
- `tests/`: diagnostic tests, run `python -m unittest discover -s tests -v`.

## Controls

- `W`, `A`, `S`, and `D` move the camera relative to its viewing direction.
- `Space` moves the camera up.
- `Control` moves the camera down.
- Hold the right mouse button and move the mouse to look around.
- `Escape` closes the application.
