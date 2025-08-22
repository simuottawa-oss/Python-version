import instance
import math
import tkinter as tk
from tkinter import *


camera = instance.instance(0.5,0.75,-1)

points = []
edges = []
objects = []
faces = []
textureCoordinates = []
normals = []

scale = 1000

root = tk.Tk()
root.title("Object Renderer")
canvas = tk.Canvas(root, height = 1000, width = 1000)
canvas.pack()

canvas_middle_width = int(canvas['width'])/2
canvas_middle_height = int(canvas['height'])/2


def initRender(filename):
     lines = open(filename)

     for line in lines:
          coordinates = line.split()
          if coordinates and coordinates[0] == "v":
               x = float(coordinates[1])
               y = float(coordinates[2])
               z = float(coordinates[3])
               point = instance.instance(x,y,z)
               points.append(point)

          elif coordinates and coordinates[0] == "l":
               pointOne = int(coordinates[1])
               pointTwo = int(coordinates[2])
               edge = (pointOne,pointTwo)
               edges.append(edge)

          elif coordinates and coordinates[0] == "o":
               objects.append(' '.join(coordinates[1:]))

          elif coordinates and coordinates[0] == "vt":
               textureCoordinates.append((float(coordinates[1]), float(coordinates[2])))

          elif coordinates and coordinates[0] == "vn":
               x = float(coordinates[1])
               y = float(coordinates[2])
               z = float(coordinates[3])
               normals.append((x,y,z))

          elif coordinates and coordinates[0] == "f":
               face = []
               for tripleVertice in coordinates[1:]:
                    vertices = tripleVertice.split("/")
                    if vertices[0] != "":
                         v = int(vertices[0])
                    else:
                         v = None

                    if len(vertices) > 1 and vertices[1] != "":
                         vt = int(vertices[1]) 
                    else:
                         vt = None

                    if len(vertices) > 2 and vertices[2] != "":
                         vn = int(vertices[2]) 
                    else:
                         vn = None

                    face.append((v,vt,vn))
               faces.append(face)
                    
     reDraw()
                
def calculateScreenCoord(x,y,z):

    nearplane = camera.getZ()  + 0.1

    w = 1
    aspect = 5
    
    fov = 60
    z -= nearplane
    if (z == 0):
         return "NaN","NaN"
    x *= (nearplane/ aspect*math.tan(math.radians(fov/2))) / (1 + nearplane/z) 
    y *= (nearplane/math.tan(fov/2))/(1 + nearplane/z)
    return x,y

def moveCamera(event):
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
     canvas.delete("all")
     for point in points:
          x = point.getX() - camera.getX()
          y = point.getY() - camera.getY()
          z = point.getZ() - camera.getZ()

          screen_x, screen_y = calculateScreenCoord(x,y,z)

          screen_x*=scale
          screen_y*=scale
          point.setScreenCoords(screen_x, screen_y)

          centered_x = canvas_middle_width + screen_x
          centered_y = canvas_middle_height - screen_y

          radius = 5
          canvas.create_oval(centered_x-radius, centered_y-radius, centered_x+radius, centered_y+radius, fill="blue")
     
     for line in edges:
          centered_x1 = canvas_middle_width+points[line[0]].getScreenX()
          centered_y1 = canvas_middle_height-points[line[0]].getScreenY()
          centered_x2 = canvas_middle_width+points[line[1]].getScreenX()
          centered_y2 = canvas_middle_height-points[line[1]].getScreenY()
                    
          canvas.create_line(centered_x1, centered_y1, centered_x2, centered_y2, fill = "white")
     
     for face in faces:
          screenPoints = []
          texturePoints = []

          for triplet in face:
               
               if triplet[0] is not None:
                    vertex = points[triplet[0]]
                    screenPoints.append(canvas_middle_width+vertex.getScreenX())
                    screenPoints.append(canvas_middle_height-vertex.getScreenY())
               
               # Currently doesn't do anything
               if triplet[1] is not None:
                    (u, v) = textureCoordinates[triplet[1]]
                    texturePoints.append((u, v))
               
               # Currently doesn't do anything
               if triplet[2] is not None:
                    (x, y, z) = normals[triplet[2]]


          if len(screenPoints) > 2:
               canvas.create_polygon(screenPoints, outline="white", fill = "gray", stipple="gray25")


root.bind("<Key>", moveCamera)
