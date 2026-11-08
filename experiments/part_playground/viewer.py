#!/usr/bin/env python3
"""Standalone part lab. Run --help for GUI and headless rendering options."""
import argparse
import json
import math
from pathlib import Path
import sys
import time

from part import load_part, Simulation
from render import Camera, scene, write_svg
from part_export import save_part, export_obj, export_stl

HERE = Path(__file__).resolve().parent


def launch(part_path, smoke_test=False):
    import tkinter as tk
    from tkinter import filedialog, messagebox

    try:
        root = tk.Tk()
    except tk.TclError as error:
        raise ValueError(f"Cannot open desktop display: {error}. Use --render output.svg for headless rendering.") from error
    root.geometry("1280x800")
    root.minsize(900, 600)
    root.configure(bg="#2b2b2b")
    root.option_add("*Font", "Sans 10")
    root.option_add("*Button.background", "#343434")
    root.option_add("*Button.foreground", "#eeeeee")
    root.option_add("*Button.activeBackground", "#484848")
    root.option_add("*Button.activeForeground", "#ffffff")
    root.option_add("*Button.highlightBackground", "#292929")
    root.option_add("*Button.highlightColor", "#aaaaaa")
    root.option_add("*Menu.background", "#222222")
    root.option_add("*Menu.foreground", "#eeeeee")
    root.option_add("*Menu.activeBackground", "#444444")
    root.option_add("*Menu.activeForeground", "#ffffff")
    root.option_add("*Menu.tearOff", False)
    part = load_part(part_path)
    part_document = Path(part_path).read_text(encoding="utf-8-sig")
    simulation = Simulation(part)
    camera = Camera(part)
    running = False
    accumulator = 0
    last_time = time.perf_counter()
    dragging = None
    workspace = tk.Frame(root, bg="#2b2b2b")
    workspace.pack(fill="both", expand=True)
    controls = tk.Frame(workspace, bg="#292929", padx=8, pady=8)
    controls.pack(side="left", fill="y")
    inspector = tk.Frame(workspace, bg="#222222", width=280, padx=16, pady=16)
    inspector.pack(side="right", fill="y")
    inspector.pack_propagate(False)
    viewport = tk.Frame(workspace, bg="#2e2e33")
    viewport.pack(side="left", fill="both", expand=True)
    canvas = tk.Canvas(viewport, bg="#2e2e33", highlightthickness=0)
    status = tk.StringVar()
    detail = tk.StringVar()
    play_label = tk.StringVar(value="Play")

    def toggle():
        nonlocal running, accumulator
        running = not running
        accumulator = 0
        play_label.set("Pause" if running else "Play")

    def reset():
        nonlocal running, accumulator
        running = False
        accumulator = 0
        simulation.reset()
        play_label.set("Play")

    def step():
        if not running:
            simulation.step()

    def frame_part():
        nonlocal camera
        camera = Camera(part)

    def show_controls():
        messagebox.showinfo(
            "SimuO Part Controls",
            "Drag to orbit · Scroll to zoom\n"
            "Space: Play / Pause · R: Reset · F: Frame part\n"
            "Ctrl+O: Open Part · Ctrl+S: Save SimuO Part\n\n"
            "File → Export offers OBJ, STL and SVG. OBJ/STL export local geometry in metres.\n"
            "Save SimuO Part preserves the part definition and physical properties; playback does not change it.\n\n"
            "Step advances a paused simulation by 1/240 second.\n"
            "The floor is at y=0; this viewer simulates translation only.",
            parent=root,
        )

    def open_part():
        nonlocal part, part_document, simulation, camera, running, accumulator
        path = filedialog.askopenfilename(initialdir=HERE, filetypes=[("SimuO part", "*.simuOPart"), ("JSON", "*.json")])
        if not path:
            return
        try:
            candidate = load_part(path)
            candidate_document = Path(path).read_text(encoding="utf-8-sig")
        except (ValueError, OSError, OverflowError) as error:
            messagebox.showerror("Cannot load part", str(error))
            return
        part = candidate
        part_document = candidate_document
        simulation = Simulation(part)
        camera = Camera(part)
        running = False
        accumulator = 0
        play_label.set("Play")
        update_details()

    def save_simuo_part():
        path = filedialog.asksaveasfilename(
            parent=root, title="Save SimuO Part", defaultextension=".simuOPart",
            initialfile="part.simuOPart", filetypes=[("SimuO part", "*.simuOPart")],
        )
        if not path:
            return
        destination = Path(path)
        if destination.suffix.lower() != ".simuopart":
            destination = destination.with_suffix(".simuOPart")
        try:
            save_part(destination, part_document)
        except (OSError, ValueError) as error:
            messagebox.showerror("Cannot save part", str(error), parent=root)

    def export_geometry(kind):
        suffix = "." + kind
        path = filedialog.asksaveasfilename(
            parent=root, title=f"Export {kind.upper()}", defaultextension=suffix,
            initialfile="part" + suffix, filetypes=[(f"{kind.upper()} mesh", "*" + suffix)],
        )
        if not path:
            return
        destination = Path(path)
        if destination.suffix.lower() != suffix:
            destination = destination.with_suffix(suffix)
        try:
            (export_obj if kind == "obj" else export_stl)(destination, part)
        except (OSError, ValueError) as error:
            messagebox.showerror("Cannot export mesh", str(error), parent=root)

    def export():
        path = filedialog.asksaveasfilename(defaultextension=".svg", initialfile="part-preview.svg",
                                          filetypes=[("SVG image", "*.svg")])
        if path:
            try:
                write_svg(path, part, simulation, camera)
            except OSError as error:
                messagebox.showerror("Cannot save image", str(error))

    def update_details():
        root.title(f"SimuO Part — {part.name}")
        inertia = ", ".join(f"{v:.4g}" for v in part.inertia)
        detail.set(f"{part.name}\n\n"
                   f"Geometry\nBox · {part.body_type}\n"
                   f"Size: {' × '.join(f'{v:g}' for v in part.size)} m\n\n"
                   f"Material\nDensity: {part.density:g} kg/m³\n"
                   f"Mass: {part.mass:.4g} kg\nFriction: {part.friction:g}\n"
                   f"Bounce: {part.restitution:g}\n\n"
                   f"Inertia (kg·m²)\n{inertia}\n\n"
                   f"Custom properties\n{json.dumps(part.properties, ensure_ascii=False, indent=2)}")

    menus = tk.Menu(root)
    root.configure(menu=menus)
    file_menu = tk.Menu(menus)
    file_menu.add_command(label="Open Part…", accelerator="Ctrl+O", command=open_part)
    file_menu.add_command(label="Save SimuO Part…", accelerator="Ctrl+S", command=save_simuo_part)
    export_menu = tk.Menu(file_menu)
    export_menu.add_command(label="OBJ…", command=lambda: export_geometry("obj"))
    export_menu.add_command(label="STL…", command=lambda: export_geometry("stl"))
    export_menu.add_command(label="SVG Image…", accelerator="Ctrl+Shift+S", command=export)
    file_menu.add_cascade(label="Export", menu=export_menu)
    file_menu.add_separator()
    file_menu.add_command(label="Close", command=root.destroy)
    menus.add_cascade(label="File", menu=file_menu)
    test_menu = tk.Menu(menus)
    test_menu.add_command(label="Play / Pause", accelerator="Space", command=toggle)
    test_menu.add_command(label="Reset", accelerator="R", command=reset)
    test_menu.add_command(label="Step 1/240 s", command=step)
    menus.add_cascade(label="Test", menu=test_menu)
    view_menu = tk.Menu(menus)
    view_menu.add_command(label="Frame Part", accelerator="F", command=frame_part)
    show_properties = tk.BooleanVar(value=True)
    view_menu.add_checkbutton(label="Part properties", variable=show_properties,
                             command=lambda: arrange_panels(root.winfo_width()))
    menus.add_cascade(label="View", menu=view_menu)
    help_menu = tk.Menu(menus)
    help_menu.add_command(label="Controls", command=show_controls)
    menus.add_cascade(label="Help", menu=help_menu)

    def tool_button(text, callback, **options):
        button = tk.Button(controls, text=text, command=callback, relief="flat",
                           borderwidth=1, width=12, padx=5, pady=9, **options)
        button.pack(fill="x", pady=(0, 8))
        return button

    tool_button("Open part…", open_part)
    tool_button("Save part…", save_simuo_part)
    tk.Frame(controls, bg="#444444", height=1).pack(fill="x", pady=(2, 12))
    tool_button("", toggle, textvariable=play_label)
    tool_button("Step 1/240 s", step)
    tool_button("Reset", reset)
    tool_button("Frame part", frame_part)
    tk.Frame(controls, bg="#444444", height=1).pack(fill="x", pady=(2, 12))
    tool_button("Save SVG…", export)
    tk.Label(inspector, text="Part properties", bg="#222222", fg="#eeeeee",
             font=("Sans", 12, "bold"), anchor="w").pack(fill="x", pady=(0, 16))
    tk.Label(inspector, textvariable=detail, bg="#222222", fg="#cccccc", justify="left",
             anchor="nw", wraplength=245).pack(fill="both", expand=True)
    canvas.pack(fill="both", expand=True)
    status_label = tk.Label(root, textvariable=status, bg="#222222", fg="#eeeeee", padx=14, pady=8,
                            anchor="w", justify="left")
    status_label.pack(fill="x")
    controls_label = tk.Label(root, text="Drag to orbit · scroll to zoom · Space to play/pause · R to reset · Help → Controls",
                              bg="#2b2b2b", fg="#aaaaaa", pady=6, padx=14, anchor="w", justify="left")
    controls_label.pack(fill="x")

    def arrange_panels(width):
        # Keep the model usable when a desktop tiles the window below its
        # requested minimum size. Restore the inspector as space permits.
        if width >= 900 and show_properties.get():
            if not inspector.winfo_manager():
                inspector.pack(side="right", fill="y", before=viewport)
        else:
            inspector.pack_forget()
        status_label.configure(wraplength=max(200, width-28))
        controls_label.configure(wraplength=max(200, width-28))

    root.bind("<Configure>", lambda event: arrange_panels(event.width) if event.widget is root else None)
    update_details()

    def press(event):
        nonlocal dragging
        dragging = (event.x, event.y)

    def drag(event):
        nonlocal dragging
        if dragging:
            camera.yaw -= (event.x-dragging[0])*0.008
            camera.pitch = max(0.08, min(1.4, camera.pitch+(event.y-dragging[1])*0.008))
            dragging = (event.x, event.y)

    def zoom(factor):
        camera.distance = max(max(part.size)*2, min(camera.distance*factor, 100))

    canvas.bind("<ButtonPress-1>", press)
    canvas.bind("<B1-Motion>", drag)
    canvas.bind("<Button-4>", lambda event: zoom(0.9))
    canvas.bind("<Button-5>", lambda event: zoom(1.1))
    canvas.bind("<MouseWheel>", lambda event: zoom(0.9 if event.delta > 0 else 1.1))
    root.bind("<space>", lambda event: toggle())
    root.bind("r", lambda event: reset())
    root.bind("f", lambda event: frame_part())
    root.bind("<Control-o>", lambda event: open_part())
    root.bind("<Control-s>", lambda event: save_simuo_part())
    root.bind("<Control-Shift-S>", lambda event: export())
    root.bind("<Escape>", lambda event: root.destroy())
    frames = 0

    def frame():
        nonlocal last_time, accumulator, frames
        now = time.perf_counter()
        elapsed = min(now-last_time, 0.1)
        last_time = now
        if running:
            accumulator += elapsed
            while accumulator >= simulation.dt:
                simulation.step()
                accumulator -= simulation.dt
        canvas.delete("all")
        for kind, coords, fill, extra in scene(part, simulation, camera,
                                              max(canvas.winfo_width(), 10), max(canvas.winfo_height(), 10)):
            if kind == "line":
                canvas.create_line(*coords, fill=fill, width=extra)
            else:
                canvas.create_polygon(*coords, fill=fill, outline=extra, width=1)
        speed = math.sqrt(sum(v*v for v in simulation.velocity))
        status.set(f"{'RUNNING' if running else 'PAUSED'}   |   t = {simulation.time:.3f} s   |   center y = {simulation.position[1]:.3f} m   |   speed = {speed:.3f} m/s")
        frames += 1
        if smoke_test and frames >= 40:
            assert len(canvas.find_all()) >= 6, "No cube faces rendered"
            assert simulation.steps > 0, "Simulation did not advance"
            print(f"GUI smoke test passed: {frames} frames, {simulation.steps} physics steps, {len(canvas.find_all())} canvas primitives")
            root.destroy()
            return
        root.after(16, frame)

    if smoke_test:
        toggle()
    root.after(20, frame)
    root.mainloop()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("part", nargs="?", type=Path, default=HERE / "aluminum_cube.simuOPart")
    parser.add_argument("--render", type=Path, metavar="OUTPUT.svg", help="Render an SVG without a display or dependencies")
    parser.add_argument("--seconds", type=float, default=0, help="Simulate this duration before headless render (0–60 seconds)")
    parser.add_argument("--smoke-test", action="store_true", help="Open GUI, advance physics, draw 40 frames, then exit")
    args = parser.parse_args()
    try:
        part = load_part(args.part)
        if not math.isfinite(args.seconds) or not 0 <= args.seconds <= 60:
            raise ValueError("--seconds must be between 0 and 60")
        if args.render:
            if args.render.suffix.lower() != ".svg":
                raise ValueError("--render output must have an .svg extension")
            simulation = Simulation(part)
            for _ in range(round(args.seconds / simulation.dt)):
                simulation.step()
            write_svg(args.render, part, simulation, Camera(part))
            print(f"Rendered {args.render} | {part.mass:.4g} kg | t={simulation.time:.3f}s")
        else:
            launch(args.part, args.smoke_test)
    except (ValueError, OSError, OverflowError) as error:
        parser.exit(1, f"Part lab: {error}\n")


if __name__ == "__main__":
    main()
