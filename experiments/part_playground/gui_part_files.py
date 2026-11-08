"""Desktop check of File → Save SimuO Part and Export menu actions."""
import json
from pathlib import Path
import tempfile
import tkinter as tk
from unittest.mock import patch

from part import load_part
import viewer


def main():
    errors, completed = [], []
    mainloop = tk.Tk.mainloop
    sample = Path(__file__).with_name("aluminum_cube.simuOPart")
    with tempfile.TemporaryDirectory(prefix="SimuO part menu ") as folder:
        folder = Path(folder)

        def find(menu, label):
            for i in range(menu.index("end")+1):
                if menu.type(i) in ("command", "cascade") and menu.entrycget(i, "label") == label:
                    return i
            raise AssertionError(f"Menu item missing: {label}")

        def loop(root, *args):
            def callback_error(*exc):
                errors.append(str(exc[1]))
            root.report_callback_exception = callback_error

            def check():
                try:
                    menu = root.nametowidget(root.cget("menu"))
                    file_menu = root.nametowidget(menu.entrycget(find(menu, "File"), "menu"))
                    export_menu = root.nametowidget(file_menu.entrycget(find(file_menu, "Export"), "menu"))
                    for label, extension in (("OBJ…", ".obj"), ("STL…", ".stl")):
                        destination = folder / ("mesh"+extension)
                        with patch("tkinter.filedialog.asksaveasfilename", return_value=str(destination)):
                            export_menu.invoke(find(export_menu, label))
                        assert destination.is_file() and destination.stat().st_size > 0
                    destination = folder / "native.simuOPart"
                    with patch("tkinter.filedialog.asksaveasfilename", return_value=str(destination)):
                        file_menu.invoke(find(file_menu, "Save SimuO Part…"))
                    assert load_part(destination).mass == load_part(sample).mass
                    assert json.loads(destination.read_text()) == json.loads(sample.read_text())
                    print("PASS File → Export → OBJ/STL and separate Save SimuO Part", flush=True)
                    before = sorted(folder.iterdir())
                    with patch("tkinter.filedialog.asksaveasfilename", return_value=""):
                        export_menu.invoke(find(export_menu, "OBJ…"))
                        file_menu.invoke(find(file_menu, "Save SimuO Part…"))
                    assert sorted(folder.iterdir()) == before
                    for target, label in ((export_menu, "STL…"), (file_menu, "Save SimuO Part…")):
                        with patch("tkinter.filedialog.asksaveasfilename", return_value=str(folder / "missing" / "file")), patch("tkinter.messagebox.showerror") as warning:
                            target.invoke(find(target, label))
                            warning.assert_called_once()
                    assert not errors, errors
                    completed.append(True)
                    print("PASS canceled dialogs and failed writes preserve files and show errors", flush=True)
                except BaseException as exc:
                    errors.append(str(exc))
                finally:
                    root.destroy()
            root.after(250, check)
            mainloop(root, *args)

        with patch.object(tk.Tk, "mainloop", loop):
            viewer.launch(sample)
    assert completed and not errors, errors


if __name__ == "__main__":
    main()
