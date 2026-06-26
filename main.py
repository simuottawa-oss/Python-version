import sys
import time
from pathlib import Path

import customtkinter as ctk


PROJECT_ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(PROJECT_ROOT / "src"))

from simple3d import cppCalculations

screenWidth = 800
screenHeight = 600
mesh = cppCalculations.createMesh(screenWidth, screenHeight)
lastTime = time.time()
keys = {}
MODELS_DIR = PROJECT_ROOT / "assets" / "models"
# FOR TESTING
wireframeColor = "Black"

def rgbtohex(r,g,b):
    return f'#{int(r):02x}{int(g):02x}{int(b):02x}'


def render(app):
    app.canvas.delete("all")
    polygons = mesh.projectMesh()
    for poly in polygons:
        if (poly[6] < 0):
            continue
        color = rgbtohex(poly[6],poly[6],poly[6])
        
        # Solid fill
        app.canvas.create_polygon(poly[0], poly[1], poly[2], poly[3], poly[4], poly[5], outline=color, fill=color, width=1)
        
        # Wireframe for debugging
        #app.canvas.create_polygon(poly[0], poly[1], poly[2], poly[3], poly[4], poly[5], outline=wireframeColor, fill="", width=1)
    return True
    
def openApplication():
    

    simuO = ctk.CTk()
    simuO.title = "SimuO"
    simuO.geometry(str(screenWidth) + "x" + str(screenHeight))
    
    print("On user create status... " + str(onUserCreate()))
    simuO.canvas = ctk.CTkCanvas(simuO, width=screenWidth, height=screenHeight, bg="black")
    simuO.canvas.pack(fill="both", expand=True)
    print("SimuO canvas created")

    def on_key_press(event):
        keys[event.keysym] = True

    def on_key_release(event):
        keys[event.keysym] = False

    simuO.bind("<KeyPress>", on_key_press)
    simuO.bind("<KeyRelease>", on_key_release)
    simuO.focus_set() 
    print("Successfully receiving user inputs")
    
    print("Initial Draw Status... " + str(render(simuO)))
    def updateLoop():
        global lastTime
        currentTime = time.time()
        elapsedTime = currentTime - lastTime
        lastTime = currentTime
        onUserUpdate(elapsedTime)
        render(simuO)
        if elapsedTime > 0.1: elapsedTime = 0.016
        simuO.after(60, updateLoop) 
    updateLoop()
    simuO.mainloop()
    return True

def loadObjectFile(filename):
    vertices = []
    triangles = []
    with open(filename, 'r') as file:

        for line in file:
            data = line.split()
            if not data: continue # Skip empty lines

            if data[0] == 'v':
                vertices.append([float(data[1]),float(data[2]),float(data[3])])
            elif data[0] == 'f':
                v1 = vertices[int(data[1].split('/')[0])-1]
                v2 = vertices[int(data[2].split('/')[0])-1]
                v3 = vertices[int(data[3].split('/')[0])-1]
                
                # Combine into a flat list of 9 floats: [x1,y1,z1, x2,y2,z2, x3,y3,z3]
                triangles.append(v1 + v2 + v3)
    return triangles
def onUserCreate():
    
    # EXAMPLE CODE: Define Cube Mesh
    #mesh.loadCubeMesh()
    
    # LOAD OBJECT FILE
    objectData = loadObjectFile(MODELS_DIR / "teapot.obj")
    mesh.loadMesh(objectData)
    
    #   Projection Matrix
    mesh.loadProjectionMatrix()

    return True

def onUserUpdate(elapsedTime):
    mesh.updateTheta(elapsedTime)
    speed = 5.0 * elapsedTime

    if keys.get("w"):
        mesh.moveCamera(0, 0, speed)
    if keys.get("s"):
        mesh.moveCamera(0, 0, -speed)
    if keys.get("a"):
        mesh.moveCamera(-speed, 0, 0)
    if keys.get("d"):
        mesh.moveCamera(speed, 0, 0)
    if keys.get("Left"):
        mesh.rotateCamera(1*elapsedTime,0)
    if keys.get("Right"):
        mesh.rotateCamera(-1*elapsedTime,0)
    return True


if __name__ == "__main__":
    print("closing application status..." + str(openApplication()))

