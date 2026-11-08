"""Linux desktop regression check for the packaged Qt startup screen and logo.

Requires wmctrl and an X11/XWayland desktop. Run from the repository root:
.venv/bin/python -m tests.desktop.gui_packaged_startup dist/SimuO
"""
import argparse
from pathlib import Path
import shutil
import subprocess
import tempfile
import time


def windows():
    """Return mapped desktop window IDs and titles using wmctrl."""
    result = subprocess.run(["wmctrl", "-lp"], check=True, capture_output=True, text=True)
    rows = {}
    for line in result.stdout.splitlines():
        columns = line.split(None, 4)
        if len(columns) == 5:
            rows[columns[0]] = columns[4]
    return rows


def check_startup(executable):
    """Open an executable from a temporary directory and close its startup window.

    Args:
        executable (Path): Linux executable to verify.

    Returns:
        None. Raises an assertion for startup errors, missing windows, or bad exit.
    """
    baseline = set(windows())
    with tempfile.TemporaryDirectory(prefix="SimuO packaged startup ") as directory:
        process = subprocess.Popen(
            [str(executable.resolve())], cwd=directory,
            stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
        )
        try:
            deadline = time.monotonic() + 30
            window = None
            while time.monotonic() < deadline and process.poll() is None:
                window = next((key for key, title in windows().items()
                               if key not in baseline and title == "SimuO"), None)
                if window:
                    break
                time.sleep(0.1)
            if window is None:
                if process.poll() is None:
                    process.terminate()
                output, error = process.communicate(timeout=10)
                raise AssertionError("Startup window never appeared:\n" + output + error)
            time.sleep(1)
            assert process.poll() is None, "Executable exited after showing startup"
            subprocess.run(["wmctrl", "-ic", window], check=True)
            output, error = process.communicate(timeout=15)
            assert process.returncode == 0, (process.returncode, output, error)
            assert "Traceback" not in error, error
            print("PASS packaged startup window and logo; clean exit from another directory")
        finally:
            if process.poll() is None:
                process.terminate()
                process.communicate(timeout=10)


def main():
    """Read the executable path, check Linux tooling, and run the desktop check."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("executable", type=Path)
    args = parser.parse_args()
    if shutil.which("wmctrl") is None:
        parser.error("This Linux desktop check requires wmctrl and an X11/XWayland display")
    if not args.executable.is_file():
        parser.error(f"Executable does not exist: {args.executable}")
    check_startup(args.executable)


if __name__ == "__main__":
    main()
