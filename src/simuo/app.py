"""Entry point for the SimuO application.

This module decides whether the user starts a new scene or imports an existing
one, then launches the main window.
"""

import argparse
import os
import sys
from pathlib import Path

# The camera uses pointer warping, which requires X11 (or XWayland).
# Respect an explicitly selected Qt backend.
if sys.platform.startswith("linux") and os.environ.get("DISPLAY"):
    os.environ.setdefault("QT_QPA_PLATFORM", "xcb")

from simuo.ui.scene_window import App


def main():
    """Parse command-line options, choose the scene/part editor or startup menu, and start
    the selected application.

    Returns:
        int or None: Editor event-loop exit code, or None if the startup chooser was
        closed without a selection.
    """
    parser = argparse.ArgumentParser(description="SimuO scene and part editors")
    parser.add_argument("project", nargs="?", help=".simuO scene or .simuOPart to open")
    parser.add_argument("--new", action="store_true", help="open a new scene directly")
    parser.add_argument("--part-editor", action="store_true", help="open the part sketch editor (optionally supply a .simuOPart)")
    args = parser.parse_args()
    qt_app = None
    if args.part_editor:
        action,filepath = "open_part" if args.project else "new_part",args.project
    elif args.project and Path(args.project).suffix.lower()==".simuopart":
        action,filepath = "open_part",args.project
    elif args.project:
        action, filepath = "import", args.project
    elif args.new:
        action, filepath = "new", None
    else:
        from PySide6.QtWidgets import QApplication
        from simuo.rendering.context import configure_opengl
        from simuo.ui.startup_dialog import StartupDialog

        configure_opengl()
        qt_app = QApplication(sys.argv)
        chooser = StartupDialog()
        chooser.exec()
        action, filepath = chooser.choice

    if action is None:
        return

    if action in ("new_part","open_part"):
        from simuo.ui.parts.part_editor import run_part_editor
        return run_part_editor(filepath)

    if action == "new":
        print("Creating new SimuO build")

        app = App()

    elif action == "import":
        print("Opening project:", filepath)

        app = App(projectPath=filepath)
    result = app.run()
    return qt_app.exec() if qt_app is not None else result
