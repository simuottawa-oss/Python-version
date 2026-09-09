from pathlib import Path

import customtkinter as ctk
from tkinter import filedialog
from PIL import Image


class SimuOStartMenu(ctk.CTkToplevel):

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
            text="New .simuO Build",
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
            text="Import Project",
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

        # -----------------------------------------------------
        # HINT
        # -----------------------------------------------------

        hint = ctk.CTkLabel(
            panel,
            text=(
                "Import Project opens a "
                ".simuO file from your computer."
            ),
            font=ctk.CTkFont(
                size=10
            ),
            text_color="#777777",
        )

        hint.pack(
            pady=(10, 12)
        )


    def _build_text_logo(
        self,
        parent
    ):

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

        callback = self.on_new

        self._close()

        if callback:
            callback()


    def _import_project(self):

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

        try:
            self.grab_release()

        except Exception:
            pass

        self.destroy()


def show_start_menu(
    parent,
    logo_path=None,
    on_new=None,
    on_import=None,
):

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

        print(
            "New .simuO build selected"
        )


    def import_project(filepath):

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
        lambda: show_start_menu(
            parent=root,
            logo_path=logo_path,
            on_new=new_project,
            on_import=import_project,
        ),
    )

    root.mainloop()