# SimuO OpenGL Renderer

## Setup

Create and activate a virtual environment, then install the dependencies:

### Windows

```powershell
py -m venv .venv
.venv\Scripts\Activate.ps1
py -m pip install -r requirements.txt
```

### macOS and Linux

```bash
python3 -m venv .venv
source .venv/bin/activate
python3 -m pip install -r requirements.txt
```

## Run

### Windows

```powershell
py main.py
```

### macOS and Linux

```bash
python3 main.py
```

Run these commands from the repository root. You can also launch the app directly
with `python src/main.py`. The app does not require a Cython or C++ build step.

## Project layout

- `main.py`: convenience launcher.
- `src/`: application, startup menu, scene, ray casting, and OpenGL renderer.
- `Assets/`: sample meshes in `.simuOPart` format.
- `Images/`: application images.
- `requirements.txt`: Python runtime dependencies.

## Controls

- `W`, `A`, `S`, and `D` move the camera relative to its viewing direction.
- `Space` moves the camera up.
- `Control` moves the camera down.
- Hold the right mouse button and move the mouse to look around.
- `Escape` closes the application.
