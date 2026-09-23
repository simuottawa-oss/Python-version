"""Entry point for the SimuO application.

This module decides whether the user starts a new scene or imports an existing
one, then launches the main window.
"""

import customtkinter as ctk
from pathlib import Path

from startMenu import showStartMenu
from simuO import App


def startup_menu():
    """Show the startup menu and return the user's next action.

    Returns:
        tuple[str | None, str | None]: A (action, filepath) pair. The action is
        "new" or "import"; filepath is only filled for imports.
    """
    root = ctk.CTk()

    # Hide the empty main CTk window.
    # We only want the startup menu visible.
    root.withdraw()

    startup = {
        "action": None,
        "filepath": None
    }

    def new_project():
        startup["action"] = "new"

    def import_project(filepath):
        startup["action"] = "import"
        startup["filepath"] = filepath

    logo_path = (
        Path(__file__).resolve().parent.parent
        / "Images"
        / "simuo_logo.png"
    )

    menu = showStartMenu(
        parent=root,
        logo_path=logo_path,
        on_new=new_project,
        on_import=import_project,
    )

    # Wait until the startup menu closes.
    root.wait_window(menu)

    root.destroy()

    return (
        startup["action"],
        startup["filepath"]
    )


def main():
    """Launch the SimuO app according to the startup selection.

    Returns:
        None: The function starts the Qt application and returns when the event
        loop is running.
    """
    action, filepath = startup_menu()

    if action is None:
        return

    if action == "new":
        print("Creating new SimuO build")

        app = App()

    elif action == "import":
        print("Opening project:", filepath)

        app = App(projectPath=filepath)
    app.run()


if __name__ == "__main__":
    main()