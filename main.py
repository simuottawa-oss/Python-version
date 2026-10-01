"""Compatibility launcher for the SimuO application.

This repository contains both a legacy demo and the active Qt editor. Running the
repository root script should delegate to the actual app entrypoint under src/.
"""

import importlib.util
import os


def _load_src_main():
    """Load the app entrypoint from src/main.py without recursive import loops."""
    project_root = os.path.dirname(os.path.abspath(__file__))
    src_main = os.path.join(project_root, "src", "main.py")

    if not os.path.exists(src_main):
        raise FileNotFoundError(f"Missing launcher: {src_main}")

    spec = importlib.util.spec_from_file_location("simuo_src_main", src_main)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


if __name__ == "__main__":
    _load_src_main().main()


