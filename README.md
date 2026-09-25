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
py src/main.py
```

### macOS and Linux

```bash
python3 src/main.py
```

## Controls

- `W`, `A`, `S`, and `D` move the camera horizontally.
- `Space` moves the camera up.
- `Control` moves the camera down.
- Hold the right mouse button and move the mouse to look around.
- `Escape` releases the mouse.
