import instance
import math
import tkinter as tk
from tkinter import *

# Creates a camera at position (0.5,0.75,-1)
camera = instance.instance(-500,-500,-500/(2*(3**0.5)/3))

# Lists storing parsed OBJ model data
points = [] # List of instance objects representing 3D vertices
edges = [] # List of (v1, v2) pairs of vertex indices representing edges
objects = [] # List of named objects in the OBJ file
faces = [] # List of faces, which are each a list of (vertex, texture, normal) index triplets
textureCoordinates = [] # List of (u, v) texture coordinates
normals = [] # List of (x, y, z) unit vectors representing normals for lighting

scale = 1000

# Initializing tkinter canvas
root = tk.Tk()
root.title("Object Renderer")
canvas = tk.Canvas(root, height = 1000, width = 1000)
canvas.pack()

canvas_middle_width = int(canvas['width'])/2
canvas_middle_height = int(canvas['height'])/2










def initRender(filename):
     '''
     Parses and stores data from OBJ files. Extracts Vertices (v), Edges (l),
     Objects (o), Texture coordinates (vt), Normals (vn), and Faces (f).
     Stores the data in global lists, then calls reDraw() for rendering.
     '''
     lines = open(filename)

     for line in lines:
          coordinates = line.split()
          if coordinates and coordinates[0] == "v":
               # Store vertex coordinates (x, y, z) in points
               x = float(coordinates[1])
               y = float(coordinates[2])
               z = float(coordinates[3])
               point = instance.instance(x,y,z)
               points.append(point)

          elif coordinates and coordinates[0] == "l":
               # Store edge represented by two vertex indices (v1, v2) in edges
               pointOne = int(coordinates[1]) # Index of vertex 1
               pointTwo = int(coordinates[2]) # Index of vertex 2
               edge = (pointOne,pointTwo)
               edges.append(edge)

          elif coordinates and coordinates[0] == "o":
               # Store object name in objects
               objects.append(' '.join(coordinates[1:]))

          elif coordinates and coordinates[0] == "vt":
               # Store texture coordinate (u, v) in textureCoordinates
               u = float(coordinates[1])
               v = float(coordinates[2])
               textureCoordinates.append((u, v))

          elif coordinates and coordinates[0] == "vn":
               # Store normal vector (x, y, z) in normals
               x = float(coordinates[1])
               y = float(coordinates[2])
               z = float(coordinates[3])
               normals.append((x,y,z))

          elif coordinates and coordinates[0] == "f":
               # Store face as a list of vertex triplets (v, vt, vn) in faces
               # v = vertex index, vt = texture coordinate index, vn = normal index
               face = []
               for vertexTriplet in coordinates[1:]:
                    vertexIndices = vertexTriplet.split("/")

                    # Vertex index
                    if vertexIndices[0] != "":
                         v = int(vertexIndices[0])
                    else:
                         v = None

                    # Texture coordinate index
                    if len(vertexIndices) > 1 and vertexIndices[1] != "":
                         vt = int(vertexIndices[1]) 
                    else:
                         vt = None

                    # Normal vector index
                    if len(vertexIndices) > 2 and vertexIndices[2] != "":
                         vn = int(vertexIndices[2]) 
                    else:
                         vn = None

                    face.append((v,vt,vn))
               faces.append(face)
                    
     reDraw()
                
def calculateScreenCoord(x,y,z):
     '''
     Projects 3D camera-space coordinates into 2D screen space.
     '''
     fov = 60
     screenDist = (canvas_middle_height/(2*math.tan(math.radians(fov/2))))
     screen_x = (x* screenDist) / z
     screen_y = (y * screenDist) / z

     return screen_x, screen_y
    
    
    
    
    
    
    
    
     '''nearplane = camera.getZ()  + 0.1

     aspect = 5
     
     fov = 60
     z -= nearplane
     if (z == 0):
          return "NaN","NaN"
     x *= (nearplane/ aspect*math.tan(math.radians(fov/2))) / (1 + nearplane/z) 
     y *= (nearplane/math.tan(fov/2))/(1 + nearplane/z)
     return x,y'''

def moveCamera(event):
    '''
    Uses keyboard input to move the camera.
    W/S changes the Z coordinates.
    A/D changes the X coordinates.
    Q/E changes the Y coordinates.
    '''
    step = 0.1
    if event.keysym == 'w':
         camera.setZ(camera.getZ() + step)
         reDraw()
    elif event.keysym == 's':
         camera.setZ(camera.getZ() - step)
         reDraw()
    elif event.keysym == 'a':
         camera.setX(camera.getX() - step)
         reDraw()
    elif event.keysym == 'd':
         camera.setX(camera.getX() + step)
         reDraw()
    elif event.keysym == 'q':
         camera.setY(camera.getY() - step)
         reDraw()
    elif event.keysym == 'e':
         camera.setY(camera.getY() + step)
         reDraw()

def reDraw():
     '''
     Clears the canvas and redraws all vertices, edges, and faces based on the current camera position.
     '''
     canvas.delete("all")

     # Drawing vertices
     for point in points:
          # Transform vertex coordinates relative to the camera
          x = point.getX() - camera.getX()
          y = point.getY() - camera.getY()
          z = point.getZ() - camera.getZ()

          # Project 3D point into 2D screen coordinates
          screen_x, screen_y = calculateScreenCoord(x,y,z)

          # Scale the screen coordinates for display
          point.setScreenCoords(screen_x, screen_y)

          # Translate the screen coordinates so the model can be centered on the canvas
          centered_x = canvas_middle_width + screen_x
          centered_y = canvas_middle_height - screen_y

          # Draw vertex as blue circle
          radius = 5
          canvas.create_oval(centered_x-radius, centered_y-radius, centered_x+radius, centered_y+radius, fill="blue")
     
     # Draw edges/lines
     for edge in edges:
          # Translate screen coordinates of both edge endpoints to center them on the canvas
          centered_x1 = canvas_middle_width+points[edge[0]].getScreenX()
          centered_y1 = canvas_middle_height-points[edge[0]].getScreenY()
          centered_x2 = canvas_middle_width+points[edge[1]].getScreenX()
          centered_y2 = canvas_middle_height-points[edge[1]].getScreenY()
          
          # Render edge as black line
          canvas.create_line(centered_x1, centered_y1, centered_x2, centered_y2, fill = "black")
     
     # Draw faces
     for face in faces:
          screenPoints = [] # List of (x, y) screen coordinates

          for vertexTriplet in face:
               # vertexTriplet (v, vt, vn)
               # v = vertex index, vt = texture coordinate index, vn = normal index

               # Convert vertex index into 2D screen coordinates
               if vertexTriplet[0] is not None:
                    vertex = points[vertexTriplet[0]]
                    screenPoints.append(canvas_middle_width+vertex.getScreenX())
                    screenPoints.append(canvas_middle_height-vertex.getScreenY())
               
               # Get texture coordinates (u, v) from the index (Currently doesn't do anything)
               if vertexTriplet[1] is not None:
                    (u, v) = textureCoordinates[vertexTriplet[1]]
               
               # Get normal vector (x, y, z) from the index (Currently doesn't do anything)
               if vertexTriplet[2] is not None:
                    (x, y, z) = normals[vertexTriplet[2]]

          # Draw the face
          if len(screenPoints) > 2:
               canvas.create_polygon(screenPoints, outline="black", fill = "gray")


root.bind("<Key>", moveCamera)