# SimuO

SimuO is a student-built 3D physics simulator. Sketch and extrude parts, arrange
them in a scene, and preview rigid-body motion.

[Scene editor](docs/scene-editor.md) · [Part editor](docs/part-editor.md) ·
[Developer guide](docs/README.md)

Set up your environment once, then use the [Run](#run) section to open the app.

## Windows setup

Use Windows 10/11 x64 with **Python 3.12 x64** from python.org. Install **Visual Studio Build Tools 2022** with **Desktop
development with C++**, including MSVC x64 and the Windows SDK. PyBullet may
take several minutes to build from source.

Open PowerShell in the repository:

```powershell
py -3.12 -m venv .venv
.\.venv\Scripts\python.exe -m pip install --upgrade pip setuptools wheel
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
```

Use a graphics driver with OpenGL 3.3 support.

## Linux Mint 22 setup

Run these commands from the repository:

```bash
sudo apt update
sudo apt install python3 python3-venv python3-pip \
    libgl1 libegl1 libglx-mesa0 libglib2.0-0 libfontconfig1 libdbus-1-3 \
    libx11-xcb1 libxcb-cursor0 libxcb-icccm4 libxcb-image0 libxcb-keysyms1 \
    libxcb-randr0 libxcb-render-util0 libxcb-shape0 libxcb-xinerama0 \
    libxcb-xkb1 libxkbcommon-x11-0 libxi6 libxrender1 build-essential python3-dev
python3 -m venv .venv
.venv/bin/python -m pip install -r requirements.txt
```

Use an X11 or XWayland session for camera controls and a graphics driver with
OpenGL 3.3 support.

## macOS setup

Use **Python 3.12** and Xcode Command Line Tools
(`xcode-select --install`). The install command includes a compiler flag for
PyBullet, which can take a few minutes to build.

```bash
python3.12 -m venv .venv
.venv/bin/python -m pip install --upgrade pip setuptools wheel
CFLAGS="-include stdio.h" .venv/bin/python -m pip install -r requirements.txt
```

## Run

In VS Code, select the project's `.venv` interpreter and run `src/main.py`.
From a terminal, run the command for your OS from the repository root.

### Windows (PowerShell)

```powershell
.\.venv\Scripts\python.exe src\main.py
```

### macOS

```bash
.venv/bin/python src/main.py
```

### Linux

```bash
.venv/bin/python src/main.py
```

See the [developer guide](docs/README.md#testing) for tests and
[executable builds](docs/README.md#build-an-executable).
