# Python 3D Renderer

## Setup

### Windows

Install the Python dependencies:

```bash
py -m pip install -r requirements.txt
```

### macOS

```bash
python3 -m pip install -r requirements.txt
```

## Build

### Windows

```bash
py setup.py build_ext --inplace
```

### macOS

```bash
python3 setup.py build_ext --inplace
```

The source file `cppCalculations.pyx` is cross-platform, but the compiled extension is platform-specific. Windows builds a `.pyd` file, while macOS builds a `.so` file. Run the build command on each computer before running the program, and run it again any time you edit `cppCalculations.pyx`.

Windows also needs a C++ compiler installed. If the build fails with a compiler error, install Microsoft C++ Build Tools, then try the build command again.

## Run

### Windows

```bash
py main.py
```

### macOS

```bash
python3 main.py
```

## Controls

- `W` moves the camera forward
- `S` moves the camera backward
- `A` moves the camera left
- `D` moves the camera right
- `Left Arrow` rotates the camera left
- `Right Arrow` rotates the camera right
