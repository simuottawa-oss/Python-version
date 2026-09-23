"""Custom startup menu for the SimuO application.

This module provides the modal welcome dialog used before a new project or an
existing project is opened.
"""

from pathlib import Path

import customtkinter as ctk
from tkinter import filedialog
from PIL import Image


class SimuOStartMenu(ctk.CTkToplevel):
    """Modal window that lets the user start a new scene or import an existing one."""

    def __init__(
        self,
        parent,
        logo_path=None,
        on_new=None,
        on_import=None,
        title="SimuO",
        width=520,
        height=610,
    ):
        """Create the startup dialog window.

        Args:
            parent: Parent tkinter window.
            logo_path: Optional path to the application logo image.
            on_new: Callback executed when the user chooses a new scene.
            on_import: Callback executed after selecting a project file.
            title: Window title text.
            width: Initial window width.
            height: Initial window height.
        """
        super().__init__(parent)

        self.parent = parent
        self.on_new = on_new
        self.on_import = on_import

        self.window_width = width
        self.window_height = height

        self.title(title)

        self.minsize(480, 560)
        self.resizable(False, False)

        self.configure(
            fg_color="#1f1f1f"
        )

        self.transient(parent)
        self.grab_set()

        self.protocol(
            "WM_DELETE_WINDOW",
            self._close
        )

        self._build_ui(logo_path)

        # Wait until Tkinter has calculated the window size,
        # then center it on the monitor.
        self.after_idle(
            self._center_on_screen
        )


    def _build_ui(self, logo_path):
        """Build the dialog contents, including the logo and action buttons.

        Args:
            logo_path: Optional path to the logo image file.
        """

        panel = ctk.CTkFrame(
            self,
            corner_radius=10,
            fg_color="#252525",
            border_width=1,
            border_color="#343434",
        )

        panel.pack(
            fill="both",
            expand=True,
            padx=14,
            pady=14,
        )

        # -----------------------------------------------------
        # LOGO
        # -----------------------------------------------------

        if logo_path:

            logo_path = Path(logo_path)

            if logo_path.exists():

                logo_image = Image.open(
                    logo_path
                ).convert("RGBA")

                max_width = 390
                max_height = 270

                ratio = min(
                    max_width / logo_image.width,
                    max_height / logo_image.height,
                    1.0,
                )

                display_size = (
                    max(
                        1,
                        int(
                            logo_image.width
                            * ratio
                        )
                    ),
                    max(
                        1,
                        int(
                            logo_image.height
                            * ratio
                        )
                    ),
                )

                self.logo_ctk_image = ctk.CTkImage(
                    light_image=logo_image,
                    dark_image=logo_image,
                    size=display_size,
                )

                logo_label = ctk.CTkLabel(
                    panel,
                    text="",
                    image=self.logo_ctk_image,
                )

                logo_label.pack(
                    pady=(18, 10)
                )

            else:

                self._build_text_logo(
                    panel
                )

        else:

            self._build_text_logo(
                panel
            )

        # -----------------------------------------------------
        # TITLE
        # -----------------------------------------------------

        title_label = ctk.CTkLabel(
            panel,
            text="SimuO",
            font=ctk.CTkFont(
                size=24,
                weight="bold"
            ),
            text_color="#f2f2f2",
        )

        title_label.pack(
            pady=(0, 2)
        )

        subtitle = ctk.CTkLabel(
            panel,
            text="3D Physics Simulator",
            font=ctk.CTkFont(
                size=12
            ),
            text_color="#9c9c9c",
        )

        subtitle.pack(
            pady=(0, 14)
        )

        # -----------------------------------------------------
        # SEPARATOR
        # -----------------------------------------------------

        separator = ctk.CTkFrame(
            panel,
            height=1,
            fg_color="#3a3a3a",
        )

        separator.pack(
            fill="x",
            padx=34,
            pady=(0, 14),
        )

        # -----------------------------------------------------
        # BUTTONS
        # -----------------------------------------------------

        button_frame = ctk.CTkFrame(
            panel,
            fg_color="transparent",
        )

        button_frame.pack(
            fill="x",
            padx=34,
            pady=(0, 8),
        )

        new_button = ctk.CTkButton(
            button_frame,
            text="New Scene",
            command=self._new_project,
            height=38,
            corner_radius=6,

            fg_color="#3f3f3f",
            hover_color="#525252",

            border_width=1,
            border_color="#5a5a5a",

            text_color="#f5f5f5",

            font=ctk.CTkFont(
                size=13,
                weight="bold"
            ),
        )

        new_button.pack(
            fill="x",
            pady=(0, 8)
        )

        import_button = ctk.CTkButton(
            button_frame,
            text="Import Scene",
            command=self._import_project,
            height=38,
            corner_radius=6,

            fg_color="#3f3f3f",
            hover_color="#525252",

            border_width=1,
            border_color="#5a5a5a",

            text_color="#f5f5f5",

            font=ctk.CTkFont(
                size=13,
                weight="bold"
            ),
        )

        import_button.pack(
            fill="x"
        )

    def _build_text_logo(
        self,
        parent
    ):
        """Create a fallback text-based logo when no image asset is available.

        Args:
            parent: Parent widget container to attach the label to.
        """

        placeholder = ctk.CTkLabel(
            parent,
            text="SimuO",

            width=390,
            height=240,

            corner_radius=8,

            fg_color="#161616",

            font=ctk.CTkFont(
                size=42,
                weight="bold"
            ),

            text_color="#f2f2f2",
        )

        placeholder.pack(
            pady=(18, 10)
        )


    def _center_on_screen(self):
        """Center the dialog on the active monitor."""

        self.update_idletasks()

        screen_width = (
            self.winfo_screenwidth()
        )

        screen_height = (
            self.winfo_screenheight()
        )

        x = (
            screen_width
            - self.window_width
        ) // 2

        y = (
            screen_height
            - self.window_height
        ) // 2

        self.geometry(
            f"{self.window_width}"
            f"x{self.window_height}"
            f"+{x}"
            f"+{y}"
        )


    def _new_project(self):
        """Handle the user selecting a new blank scene."""

        callback = self.on_new

        self._close()

        if callback:
            callback()


    def _import_project(self):
        """Open a file chooser and trigger the import callback with the selected project.

        Returns:
            None: The method exits early if the user cancels the dialog.
        """

        filename = filedialog.askopenfilename(
            parent=self,

            title="Import SimuO Project",

            filetypes=[
                (
                    "SimuO Projects",
                    "*.simuO"
                ),
                (
                    "All Files",
                    "*.*"
                ),
            ],
        )

        if not filename:
            return

        callback = self.on_import

        self._close()

        if callback:
            callback(
                filename
            )


    def _close(self):
        """Close the modal window and release any grabbed input state."""

        try:
            self.grab_release()

        except Exception:
            pass

        self.destroy()


def showStartMenu(
    parent,
    logo_path=None,
    on_new=None,
    on_import=None,
):
    """Construct and return the startup menu.

    Args:
        parent: Parent widget that owns the dialog.
        logo_path: Optional logo image path.
        on_new: Callback for new project creation.
        on_import: Callback for importing a project file.

    Returns:
        SimuOStartMenu: The configured startup dialog instance.
    """

    return SimuOStartMenu(
        parent=parent,
        logo_path=logo_path,
        on_new=on_new,
        on_import=on_import,
    )


# ---------------------------------------------------------
# STANDALONE TEST
# ---------------------------------------------------------

if __name__ == "__main__":

    ctk.set_appearance_mode(
        "dark"
    )

    root = ctk.CTk()

    root.title(
        "SimuO Menu Preview"
    )

    root.geometry(
        "900x650"
    )

    root.configure(
        fg_color="#191919"
    )


    def new_project():
        """Preview callback for choosing a new scene."""

        print(
            "New .simuO build selected"
        )


    def import_project(filepath):
        """Preview callback for importing a project file.

        Args:
            filepath: Path of the project to import.
        """

        print(
            "Imported:",
            filepath
        )


    logo_path = (
        Path(__file__).resolve().parent
        / "Images"
        / "simuo_logo.png"
    )


    root.after(
        100,
        lambda: showStartMenu
(
            parent=root,
            logo_path=logo_path,
            on_new=new_project,
            on_import=import_project,
        ),
    )

    root.mainloop()