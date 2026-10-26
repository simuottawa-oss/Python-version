"""Check the environment and optionally test the application's graphics startup."""

import argparse
import importlib.metadata
import os
from pathlib import Path
import stat
import subprocess
import sys

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))


def run_python(arguments, timeout=20):
    """Isolate native imports and graphics crashes from the diagnostic process."""
    return subprocess.run(
        [sys.executable, "-B", *arguments],
        capture_output=True, text=True, timeout=timeout,
    )


def bootstrap(arguments):
    """Run without site first, then check the same interpreter's normal startup."""
    try:
        result = run_python(["-c", "pass"], timeout=15)
    except subprocess.TimeoutExpired:
        print("FAIL: The virtual environment's Python did not start within 15 seconds.")
        print("If this folder is cloud-synced, download it fully or move it outside iCloud.")
        print("Then create a fresh virtual environment. See README.md.")
        return 1
    if result.returncode:
        print("FAIL: The virtual environment's Python cannot start normally.")
        print(result.stderr.strip())
        print("See README.md: macOS troubleshooting.")
        return 1
    # Normal startup is now verified; preserve output, arguments, and exit status.
    os.execv(sys.executable, [sys.executable, "-B", str(Path(__file__).resolve()), *arguments])


def check_dependencies():
    """Check the declared versions and actually import their Python modules."""
    aliases = {"PyOpenGL": "OpenGL", "PyGLM": "glm"}
    modules = []
    ok = True
    for line in (ROOT / "requirements.txt").read_text().splitlines():
        requirement = line.split("#", 1)[0].strip()
        if not requirement:
            continue
        name, _, pinned = requirement.partition("==")
        try:
            version = importlib.metadata.version(name)
        except importlib.metadata.PackageNotFoundError:
            print(f"FAIL: {name} is not installed.")
            ok = False
            continue
        if pinned and version != pinned:
            print(f"FAIL: {name} {version} is installed; requirements.txt specifies {pinned}.")
            ok = False
        else:
            print(f"PASS: {name} {version}")
        modules.append(aliases.get(name, name))
    if ok:
        code = (
            "import importlib, sys\n"
            "for name in sys.argv[1:]:\n"
            "    print('Importing ' + name, flush=True)\n"
            "    importlib.import_module(name)\n"
        )
        try:
            result = run_python(["-c", code, *modules])
            if result.returncode:
                print("FAIL: A dependency could not be imported.")
                print(result.stdout.strip())
                print(result.stderr.strip())
                ok = False
        except subprocess.TimeoutExpired:
            print("FAIL: Dependency imports timed out. Check for cloud-offloaded files.")
            ok = False
    if not ok:
        print('Repair: python -m pip install -r "' + str(ROOT / "requirements.txt") + '"')
    return ok


def macos_qt_plugin_status():
    """Inspect plugin metadata without changing it or trying to load Qt."""
    if sys.platform != "darwin":
        return None, None

    from PySide6.QtCore import QLibraryInfo

    candidates = []
    for directory in os.environ.get("QT_QPA_PLATFORM_PLUGIN_PATH", "").split(os.pathsep):
        if directory:
            candidates.extend([
                Path(directory) / "libqcocoa.dylib",
                Path(directory) / "platforms" / "libqcocoa.dylib",
            ])
    default = Path(QLibraryInfo.path(QLibraryInfo.PluginsPath)) / "platforms" / "libqcocoa.dylib"
    candidates.append(default)

    problems = []
    for plugin in candidates:
        try:
            info = plugin.stat()
        except FileNotFoundError:
            continue
        except OSError as error:
            problems.append((plugin, f"Cannot inspect Qt's macOS plugin: {error}"))
            continue
        if not stat.S_ISREG(info.st_mode):
            continue
        if getattr(info, "st_flags", 0) & stat.UF_HIDDEN:
            problems.append((plugin, "Qt's macOS plugin is hidden and may not be discovered."))
        elif not os.access(plugin, os.R_OK):
            problems.append((plugin, "Qt's macOS plugin is not readable."))
        else:
            return plugin, None

    return problems[0] if problems else (default, "Qt's macOS platform plugin is missing.")


def check_plugin():
    """Report metadata warnings; the graphics probe tests actual Qt loading."""

    plugin, problem = macos_qt_plugin_status()
    if plugin is None:
        return True
    if problem:
        print(f"WARN: {problem}\nPlugin: {plugin}")
        print("Use --graphics to test actual Qt startup.")
        return False
    print(f"PASS: Qt's macOS platform plugin is visible and readable: {plugin}")
    return True


def graphics_probe():
    """Show a small viewport and exercise the application's real shader setup."""
    from PySide6.QtCore import QTimer
    from PySide6.QtWidgets import QApplication
    from main import configure_opengl
    from renderer import OpenGLViewport

    configure_opengl()
    app = QApplication([])
    app.setQuitOnLastWindowClosed(False)
    errors = []

    class Probe(OpenGLViewport):
        ready = False

        def initializeGL(self):
            try:
                super().initializeGL()
                self.ready = True
            except Exception as error:
                errors.append(f"Graphics initialization failed: {error}")

        def paintGL(self):
            if self.ready and not errors:
                try:
                    super().paintGL()
                except Exception as error:
                    errors.append(f"Drawing failed: {error}")

    viewport = Probe()
    viewport.setWindowTitle("SimuO setup check")
    viewport.resize(160, 120)

    def finish():
        valid = viewport.isValid() and viewport.ready
        if valid and not errors:
            image = viewport.grabFramebuffer()
            if image.isNull():
                errors.append("Could not read the rendered framebuffer.")
        elif not errors:
            errors.append("Could not create a working OpenGL viewport.")
        viewport.close()
        for error in errors:
            print(f"FAIL: {error}")
        app.exit(1 if errors else 0)

    viewport.show()
    QTimer.singleShot(500, finish)
    return app.exec()


def main(arguments=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--graphics", action="store_true", help="briefly open a window and test Qt startup and rendering")
    parser.add_argument("--graphics-probe", action="store_true", help=argparse.SUPPRESS)
    args = parser.parse_args(arguments)
    if args.graphics_probe:
        return graphics_probe()

    print(f"Python: {sys.version.split()[0]} ({sys.executable})")
    if not (3, 10) <= sys.version_info < (3, 15):
        print("FAIL: PySide6 6.11.2 requires CPython 3.10–3.14. Python 3.12 is tested here.")
        return 1
    if sys.prefix == sys.base_prefix:
        print("FAIL: This interpreter is not in a virtual environment. Follow README.md.")
        return 1
    if sys.version_info[:2] != (3, 12):
        print("INFO: This project was checked with Python 3.12; your version is not verified here.")
    if not check_dependencies():
        return 1
    # File metadata is advisory; do not prevent the real graphics test from running.
    check_plugin()
    if args.graphics:
        print("Checking OpenGL (a small window will briefly appear)...", flush=True)
        try:
            result = run_python([str(Path(__file__).resolve()), "--graphics-probe"], timeout=20)
        except subprocess.TimeoutExpired:
            print("FAIL: The graphics check timed out. Run it in a logged-in desktop session.")
            return 1
        print(result.stdout.strip())
        if result.returncode:
            print(f"FAIL: Graphics check exited with status {result.returncode}.")
            print(result.stderr.strip())
            print("For a Qt plugin error, recreate .venv outside cloud-synced storage; see README.md.")
            print("For an OpenGL error, check your graphics driver supports OpenGL 3.3 Core.")
            return 1
        print("PASS: OpenGL context, application shaders, drawing, and framebuffer readback.")
        print("Setup and graphics checks passed.")
    else:
        print("Dependency checks passed. Qt startup and rendering have not been tested.")
        print("Add --graphics from a logged-in desktop session to test them.")
    return 0


if __name__ == "__main__":
    try:
        if sys.argv[1:2] == ["--bootstrap"]:
            raise SystemExit(bootstrap(sys.argv[2:]))
        raise SystemExit(main())
    except (OSError, subprocess.SubprocessError) as error:
        print(f"FAIL: Could not finish checking the environment: {error}", file=sys.stderr)
        raise SystemExit(1)
