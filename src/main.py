import cppCalculations
import customtkinter as ctk
import time
import numpy as np
from PIL import Image, ImageTk
import ctypes
from pathlib import Path

from startMenu import show_start_menu


screenWidth = 800
screenHeight = 600

movementAccumulator = 0.0
fixedDelta = 1.0 / 120.0

mesh = cppCalculations.createMesh(screenWidth, screenHeight)

lastTime = time.perf_counter()
keys = {}

# Color framebuffer: [height, width, RGB]
framebuffer = np.zeros(
    (screenHeight, screenWidth, 3),
    dtype=np.uint8
)

# Z-buffer: one float depth per pixel.
depthbuffer = np.full(
    (screenHeight, screenWidth),
    np.inf,
    dtype=np.float32
)


def render(app):

    startTime = time.time()

    framebuffer.fill(0)
    depthbuffer.fill(np.inf)

    mesh.renderToFramebuffer(
        framebuffer,
        depthbuffer
    )

    renderTime = time.time()

    image = Image.fromarray(
        framebuffer,
        "RGB"
    )

    canvasWidth = max(
        1,
        app.canvas.winfo_width()
    )

    canvasHeight = max(
        1,
        app.canvas.winfo_height()
    )

    image = image.resize(
        (
            canvasWidth,
            canvasHeight
        ),
        Image.Resampling.NEAREST
    )

    app.tk_image = ImageTk.PhotoImage(
        image
    )

    app.canvas.itemconfig(
        app.canvas_image,
        image=app.tk_image
    )

    displayTime = time.time()

    print(
        f"Render time: "
        f"{(renderTime - startTime) * 1000:.2f} ms"
    )

    print(
        f"Display time: "
        f"{(displayTime - renderTime) * 1000:.2f} ms"
    )

    return True

def openApplication():
    global lastTime
    global movementAccumulator

    simuO = ctk.CTk()
    simuO.title("SimuO")
    simuO.geometry(f"{screenWidth}x{screenHeight}")

    # ---------------------------------------------------------
    # START MENU
    # ---------------------------------------------------------

    # Looks for simuo_logo.png in the same folder as main.py.
    logo_path = "Images\simuo_logo.png"

    # These get changed by the menu callbacks.
    startup = {
        "action": None,
        "filepath": None
    }

    def new_project():
        startup["action"] = "new"

    def import_project(filepath):
        startup["action"] = "import"
        startup["filepath"] = filepath

    # Make sure the root window exists before the Toplevel is created.
    simuO.update_idletasks()

    menu = show_start_menu(
        parent=simuO,
        logo_path=logo_path,
        on_new=new_project,
        on_import=import_project,
    )

    # IMPORTANT:
    # Stop here until the startup menu is closed.
    simuO.wait_window(menu)

    # If the user closed the menu without choosing anything,
    # close the application instead of starting the simulator.
    if startup["action"] is None:
        simuO.destroy()
        return False

    if startup["action"] == "new":
        print("Starting new .simuO build")

    elif startup["action"] == "import":
        print("Selected .simuO project:")
        print(startup["filepath"])

        # Later, call your .simuO parser here, for example:
        #
        # loadSimuOProject(startup["filepath"])

    # ---------------------------------------------------------
    # INITIALIZE WORLD
    # ---------------------------------------------------------

    print("On user create status... " + str(onUserCreate()))

    # ---------------------------------------------------------
    # RENDER CANVAS
    # ---------------------------------------------------------

    simuO.canvas = ctk.CTkCanvas(
        simuO,
        width=screenWidth,
        height=screenHeight,
        bg="black"
    )
    simuO.canvas.pack(fill="both", expand=True)

    print("SimuO canvas created")

    # Create ONE Canvas image object and reuse it every frame.
    simuO.canvas_image = simuO.canvas.create_image(
        0,
        0,
        anchor="nw"
    )
    
    initial_image = Image.fromarray(framebuffer, "RGB")

    simuO.tk_image = ImageTk.PhotoImage(initial_image)

    simuO.canvas_image = simuO.canvas.create_image(
        0,
        0,
        anchor="nw",
        image=simuO.tk_image
    )
    simuO.display_width = screenWidth
    simuO.display_height = screenHeight 
    
    def on_canvas_resize(event):
        simuO.display_width = event.width
        simuO.display_height = event.height

    simuO.canvas.bind("<Configure>", on_canvas_resize)
    print("Canvas image created")

    # ---------------------------------------------------------
    # KEYBOARD INPUT
    # ---------------------------------------------------------

    def on_key_press(event):
        keys[event.keysym] = True

    def on_key_release(event):
        keys[event.keysym] = False

    # ---------------------------------------------------------
    # MOUSE CAMERA
    # ---------------------------------------------------------

    mouse_sensitivity = 0.002
    right_mouse_down = False

    def get_canvas_center_screen():
        center_x = (
            simuO.canvas.winfo_rootx()
            + simuO.canvas.winfo_width() // 2
        )

        center_y = (
            simuO.canvas.winfo_rooty()
            + simuO.canvas.winfo_height() // 2
        )

        return center_x, center_y

    def center_mouse():
        center_x, center_y = get_canvas_center_screen()

        ctypes.windll.user32.SetCursorPos(
            center_x,
            center_y
        )

    def on_right_mouse_down(event):
        nonlocal right_mouse_down

        right_mouse_down = True

        simuO.canvas.config(cursor="none")
        simuO.canvas.grab_set()

        center_mouse()

    def on_mouse_move(event):
        if not right_mouse_down:
            return

        center_x, center_y = get_canvas_center_screen()

        delta_x = event.x_root - center_x
        delta_y = event.y_root - center_y

        # Ignore the event caused by recentering the mouse.
        if abs(delta_x) <= 1 and abs(delta_y) <= 1:
            return

        mesh.rotateCamera(
            -delta_x * mouse_sensitivity,
            -delta_y * mouse_sensitivity
        )

        center_mouse()

    def on_right_mouse_up(event):
        nonlocal right_mouse_down

        right_mouse_down = False

        simuO.canvas.config(cursor="")

        try:
            simuO.canvas.grab_release()
        except Exception:
            pass

    simuO.bind("<KeyPress>", on_key_press)
    simuO.bind("<KeyRelease>", on_key_release)

    simuO.canvas.bind("<ButtonPress-3>", on_right_mouse_down)
    simuO.canvas.bind("<Motion>", on_mouse_move)
    simuO.canvas.bind("<ButtonRelease-3>", on_right_mouse_up)

    simuO.focus_set()

    print("Successfully receiving user inputs")

    # Make sure the canvas has its real size before the first frame.
    simuO.update_idletasks()

    print("Initial Draw Status... " + str(render(simuO)))

    # Reset timing AFTER the startup menu has closed.
    # Otherwise the time spent in the menu becomes one giant elapsedTime.
    lastTime = time.perf_counter()
    movementAccumulator = 0.0

    # ---------------------------------------------------------
    # MAIN LOOP
    # ---------------------------------------------------------

    def updateLoop():
        global lastTime
        global movementAccumulator

        currentTime = time.perf_counter()
        elapsedTime = currentTime - lastTime
        lastTime = currentTime

        # Prevent giant simulation jumps.
        elapsedTime = min(elapsedTime, 0.1)

        movementAccumulator += elapsedTime

        while movementAccumulator >= fixedDelta:
            onUserUpdate(fixedDelta)
            movementAccumulator -= fixedDelta

        # Do NOT call onUserUpdate(elapsedTime) again here.
        # The fixed-step loop above already updates movement.

        render(simuO)

        simuO.after(10, updateLoop)

    updateLoop()
    simuO.mainloop()

    return True


def loadObjectFile(filename):
    vertices = []
    triangles = []

    with open(filename, "r") as file:
        for line in file:
            data = line.split()

            if not data:
                continue

            if data[0] == "v":
                vertices.append([
                    float(data[1]),
                    float(data[2]),
                    float(data[3])
                ])

            elif data[0] == "f":
                v1 = vertices[int(data[1].split("/")[0]) - 1]
                v2 = vertices[int(data[2].split("/")[0]) - 1]
                v3 = vertices[int(data[3].split("/")[0]) - 1]

                triangles.append(v1 + v2 + v3)

    return triangles


def onUserCreate():
    # LOAD OBJECT FILE
    objectData = loadObjectFile("axis.obj")
    mesh.loadMesh(objectData)

    # Projection matrix
    mesh.loadProjectionMatrix()

    return True


def onUserUpdate(elapsedTime):
    speed = 5 * elapsedTime

    forward = 0.0
    right = 0.0

    if keys.get("w"):
        forward += speed

    if keys.get("s"):
        forward -= speed

    if keys.get("d"):
        right += speed

    if keys.get("a"):
        right -= speed

    mesh.moveCameraRelative(
        forward,
        right
    )

    return True


print("closing application status..." + str(openApplication()))
