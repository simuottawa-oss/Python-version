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

from PySide6.QtWidgets import QApplication, QMessageBox
from simuo.ui.startup import showStartMenu
from simuo.ui.scene_window import App
from simuo.resources.paths import resource_path
from simuo.rendering.context import configure_opengl
from PySide6.QtGui import QIcon

def startup_menu():
    """Run the modal Qt startup chooser and return the selected action.

    Returns:
        tuple: (action, filepath), with None values when no action/path was chosen.
    """
    # The surface format has to be selected before the first QApplication is made,
    # including when the first window happens to be this non-OpenGL dialog.
    configure_opengl()
    qt_app = QApplication.instance() or QApplication(sys.argv)
    qt_app.setWindowIcon(
        QIcon(str(resource_path("Images", "simuo_logo.png")))
    )
    startup = {
        "action": None,
        "filepath": None
    }

    def new_project():
        """Record the startup choice to create an empty scene in the enclosing result
        dictionary.

        Returns:
            None. Mutates captured startup state.
        """
        startup["action"] = "new"

    def import_project(filepath):
        """Record the chosen scene path and import action in the enclosing startup state.

        Args:
            filepath (str or Path): Selected scene or part file path.

        Returns:
            None. Mutates captured startup state.
        """
        startup["action"] = "import"
        startup["filepath"] = filepath

    def new_part():
        """Record the startup choice to create a new editable part.

        Returns:
            None. Mutates captured startup state.
        """
        startup["action"] = "new_part"

    def open_part(filepath):
        """Record the chosen part path and open-part action in the enclosing startup state.

        Args:
            filepath (str or Path): Selected scene or part file path.

        Returns:
            None. Mutates captured startup state.
        """
        startup["action"] = "open_part"
        startup["filepath"] = filepath

    def new_structural():
        startup["action"] = "structural"

    logo_path = resource_path("Images", "simuo_logo.png")

    menu = showStartMenu(
        parent=None,
        logo_path=logo_path,
        on_new=new_project,
        on_import=import_project,
        on_new_part=new_part,
        on_open_part=open_part,
        on_structural=new_structural,
    )

    # Keep closing the chooser from scheduling an application quit before the selected
    # editor window has been created.
    quit_on_close = qt_app.quitOnLastWindowClosed()
    qt_app.setQuitOnLastWindowClosed(False)
    try:
        menu.exec()
    finally:
        qt_app.setQuitOnLastWindowClosed(quit_on_close)

    return (
        startup["action"],
        startup["filepath"]
    )


def main():
    """Parse command-line options, choose the scene/part editor or startup menu, and start
    the selected application.

    Returns:
        int or None: Editor event-loop exit code, or None if the startup chooser was
        closed without a selection.
    """
    parser = argparse.ArgumentParser(description="SimuO scene, part and structural editors")
    parser.add_argument("project", nargs="?", help=".simuO project or .simuOPart to open (legacy analyses supported)")
    parser.add_argument("--new", action="store_true", help="open a new scene directly")
    parser.add_argument("--part-editor", action="store_true", help="open the part sketch editor (optionally supply a .simuOPart)")
    parser.add_argument("--structural", action="store_true", help="open structural analysis (optionally supply a solid or .simuO project)")
    parser.add_argument("--structural-smoke", action="store_true", help="run the packaged meshing/solver self-check and exit")
    args = parser.parse_args()
    if args.structural_smoke:
        from simuo.structural.smoke import run_smoke
        return run_smoke()
    if args.structural or (args.project and Path(args.project).suffix.lower() == ".simuoanalysis"):
        action, filepath = "structural", args.project
    elif args.part_editor:
        action,filepath = "open_part" if args.project else "new_part",args.project
    elif args.project and Path(args.project).suffix.lower()==".simuopart":
        action,filepath = "open_part",args.project
    elif args.project:
        action, filepath = "import", args.project
    elif args.new:
        action, filepath = "new", None
    else:
        action, filepath = startup_menu()

    if action is None:
        return

    if filepath and Path(filepath).suffix.lower() in (".simuo", ".simuoanalysis"):
        from simuo.project.project_format import read_project
        try:
            kind = read_project(filepath).project_type
            action = "structural" if kind == "structural" else "import"
        except (OSError, ValueError, UnicodeError) as error:
            configure_opengl()
            qt_app = QApplication.instance() or QApplication(sys.argv)
            QMessageBox.warning(None, "Cannot Open Project", str(error))
            return 1

    if action == "structural":
        from simuo.ui.structural_window import run_structural
        return run_structural(filepath)

    if action in ("new_part","open_part"):
        from simuo.ui.parts.part_editor import run_part_editor
        return run_part_editor(filepath)

    if action == "new":
        print("Creating new SimuO build")

        app = App()

    elif action == "import":
        print("Opening project:", filepath)

        app = App(projectPath=filepath)
    # This is the top-level launcher even when the startup dialog already created the
    # QApplication, so the editor must now enter the main Qt event loop.
    return app.run(start_event_loop=True)
