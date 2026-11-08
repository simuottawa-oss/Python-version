"""Custom startup menu for the SimuO application.

This module provides the modal welcome dialog used before a new project or an
existing project is opened.
"""
from pathlib import Path

import customtkinter as ctk
from tkinter import filedialog
from PIL import Image
from simuo.resources.paths import resource_path


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
        height=710,
        on_new_part=None,
        on_open_part=None,
    ):
        """Build a fixed-size startup chooser with optional logo and scene/part action
        callbacks.

        Args:
            parent (widget, optional): Owning Qt or Tk widget; None creates an
                independent Qt widget.
            logo_path (str or Path, optional): Logo image location; missing/omitted
                images use a text placeholder.
            on_new (callable, optional): No-argument callback for creating a scene.
            on_import (callable, optional): Callback receiving the selected scene path.
            title (str): Window or confirmation-dialog title.
            width (int): Widget/window width in logical pixels.
            height (int): Widget/window height in logical pixels.
            on_new_part (callable, optional): No-argument callback for creating an
                editable part.
            on_open_part (callable, optional): Callback receiving the selected part
                path.

        Returns:
            None. Creates a Tk toplevel and schedules centering and modal capture after
            mapping.
        """
        super().__init__(parent)

        self.parent = parent
        self.on_new = on_new
        self.on_import = on_import
        self.on_new_part = on_new_part
        self.on_open_part = on_open_part

        self.window_width = width
        self.window_height = height

        self.title(title)

        self.minsize(480, 560)
        self.resizable(False, False)

        self.configure(
            fg_color="#1f1f1f"
        )

        # A transient of a withdrawn root can remain invisible on Linux.
        # X11 also requires the window to be mapped before taking a grab.
        self.bind("<Map>", self._grab_when_visible, add="+")

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


    def _grab_when_visible(self, event):
        """Acquire modal input capture only once this startup toplevel is mapped and
        viewable.

        Args:
            event (Tk event): Map event; capture is taken only for this toplevel when
                visible.

        Returns:
            None. Ignores map events from child widgets.
        """
        if event.widget is self and self.winfo_viewable():
            self.grab_set()

    def _build_ui(self, logo_path):

        """Create the logo/title panel and scene/part buttons, falling back to a text logo
        if no image exists.

        Args:
            logo_path (str or Path, optional): Logo image location; missing/omitted
                images use a text placeholder.

        Returns:
            None. Builds and packs child widgets.
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

        ctk.CTkLabel(button_frame,text="PART EDITOR",text_color="#a8c5d6").pack(pady=(12,4))
        for text,callback in (("New Part",self._new_part),("Open Part…",self._open_part)):
            ctk.CTkButton(button_frame,text=text,command=callback,height=38,
                          fg_color="#3f3f3f",hover_color="#525252",
                          border_width=1,border_color="#5a5a5a",text_color="#f5f5f5").pack(fill="x",pady=(0,8))

    def _new_part(self):
        """Close the chooser and invoke the optional no-argument new-part callback.

        Returns:
            None. Calls the callback only if supplied.
        """
        callback = self.on_new_part
        self._close()
        if callback:
            callback()

    def _open_part(self):
        """Prompt for a part file, then close the chooser and invoke its optional open-part
        callback.

        Returns:
            None. Cancellation leaves the chooser open.
        """
        filename = filedialog.askopenfilename(parent=self,title="Open SimuO Part",
                                              filetypes=[("SimuO Parts","*.simuOPart")])
        if filename:
            callback = self.on_open_part
            self._close()
            if callback:
                callback(filename)

    def _build_text_logo(
        self,
        parent
    ):

        """Create a styled text placeholder when the image logo is unavailable.

        Args:
            parent (widget, optional): Owning Qt or Tk widget; None creates an
                independent Qt widget.

        Returns:
            None. Packs a label into the supplied parent.
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

        """Calculate screen-centered geometry using configured startup-window dimensions.

        Returns:
            None. Moves and sizes the toplevel after idle layout.
        """
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

        """Close the chooser and invoke the optional no-argument new-scene callback.

        Returns:
            None.
        """
        callback = self.on_new

        self._close()

        if callback:
            callback()


    def _import_project(self):

        """Prompt for a scene file, then close the chooser and pass its path to the
        optional import callback.

        Returns:
            None. Cancellation leaves the chooser open.
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
                    "*"
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

        """Release modal capture if possible and destroy the startup toplevel.

        Returns:
            None. Suppresses capture-release errors during closure.
        """
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
    on_new_part=None,
    on_open_part=None,
):

    """Construct a startup chooser attached to the supplied Tk parent.

    Args:
        parent (widget, optional): Owning Qt or Tk widget; None creates an independent
            Qt widget.
        logo_path (str or Path, optional): Logo image location; missing/omitted images
            use a text placeholder.
        on_new (callable, optional): No-argument callback for creating a scene.
        on_import (callable, optional): Callback receiving the selected scene path.
        on_new_part (callable, optional): No-argument callback for creating an editable
            part.
        on_open_part (callable, optional): Callback receiving the selected part path.

    Returns:
        SimuOStartMenu: New chooser window; this helper does not start or wait on an
        event loop.
    """
    return SimuOStartMenu(
        parent=parent,
        logo_path=logo_path,
        on_new=on_new,
        on_import=on_import,
        on_new_part=on_new_part,
        on_open_part=on_open_part,
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

        """Print the new-scene selection for the standalone menu preview.

        Returns:
            None. Writes preview feedback to stdout.
        """
        print(
            "New .simuO build selected"
        )


    def import_project(filepath):

        """Print the imported scene path for the standalone menu preview.

        Args:
            filepath (str or Path): Selected scene or part file path.

        Returns:
            None. Writes preview feedback to stdout.
        """
        print(
            "Imported:",
            filepath
        )


    logo_path = resource_path("Images", "simuo_logo.png")


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
