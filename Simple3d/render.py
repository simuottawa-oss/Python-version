import instance
import math
import tkinter as tk
from tkinter import *


camera = instance.instance(0,0,-3)

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

global xDeg
global yDeg
xDeg = 0
yDeg = 0


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
               for vertexTriplet in coordinates[1:]:
                    vertexIndices = vertexTriplet.split("/")
                    if vertexIndices[0] != "":
                         v = int(vertexIndices[0])
                    else:
                         v = None

                    if len(vertexIndices) > 1 and vertexIndices[1] != "":
                         vt = int(vertexIndices[1]) 
                    else:
                         vt = None

                    if len(vertexIndices) > 2 and vertexIndices[2] != "":
                         vn = int(vertexIndices[2]) 
                    else:
                         vn = None

                    face.append((v,vt,vn))
               faces.append(face)
                    
     reDraw()
                
def calculateScreenCoord(x,y,z):

    h = canvas_middle_height/scale
    fov = 60
    screenDist = (h/(2*math.tan(math.radians(fov/2))))
    screen_x = (x * screenDist) / z
    screen_y = (y * screenDist) / z
    return screen_x,screen_y

def moveCamera(event):
    global xDeg, yDeg




    


    '''step = 0.1

    if event.keysym == 'w':
         camera.setZ(camera.getZ() + step)
         reDraw()
    elif event.keysym == 's':
         camera.setZ(camera.getZ() - step)
         reDraw()'''
    if event.keysym == 'a':
         if xDeg == 0:
              xDeg = 359
         else:
              xDeg -= 1
         reDraw()
    elif event.keysym == 'd':
         if xDeg == 359:
              xDeg = 0
         else:
              xDeg += 1
         reDraw()
    elif event.keysym == 'q':
         if yDeg == 0:
              yDeg = 359
         else:
              yDeg -= 1
         reDraw()
    elif event.keysym == 'e':
         if yDeg == 359:
              yDeg = 0
         else:
              yDeg += 1
         reDraw()

def reDraw():
     canvas.delete("all")
     for point in points:

          '''
          x = point.getX() - camera.getX()
          y = point.getY() - camera.getY()
          z = point.getZ() - camera.getZ()
          '''
          x = point.getX()
          y = point.getY()
          z = point.getZ()

          '''if xDeg != 0:
               angle = math.radians(xDeg)
               tempX = x
               tempZ = z
               x = tempX*math.cos(angle) - tempZ*math.sin(angle)
               z = tempX*math.sin(angle) + tempZ*math.cos(angle)
          if yDeg != 0:
               angle = math.radians(yDeg)
               tempY = y
               tempZ = z
               y = tempY*math.cos(angle) - tempZ*math.sin(angle)
               z = tempY*math.sin(angle) + tempZ*math.cos(angle)
          '''
          
          '''
          x *= (math.cos(math.radians(xDeg)) - z*math.sin(math.radians(yDeg)))
          z *= (math.cos(math.radians(xDeg)) + x*math.sin(math.radians(yDeg)))
          y *= (math.cos(math.radians(yDeg)) - z*math.sin(math.radians(xDeg)))
          '''
          if xDeg != 0:
               tempX = x
               x = x*math.cos(math.radians(xDeg)) + z*math.sin(math.radians(xDeg))
               z = z*math.cos(math.radians(xDeg)) - tempX*math.sin(math.radians(xDeg))
          if yDeg != 0:
               tempY = y
               y = y*math.cos(math.radians(yDeg)) + z*math.sin(math.radians(yDeg))
               z = z*math.cos(math.radians(yDeg)) - tempY*math.sin(math.radians(yDeg))

          z -= camera.getZ()
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

          for vertexTriplet in face:
               
               if vertexTriplet[0] is not None:
                    vertex = points[vertexTriplet[0]]
                    screenPoints.append(canvas_middle_width+vertex.getScreenX())
                    screenPoints.append(canvas_middle_height-vertex.getScreenY())
               
               # Currently doesn't do anything
               if vertexTriplet[1] is not None:
                    (u, v) = textureCoordinates[vertexTriplet[1]]
                    texturePoints.append((u, v))
               
               # Currently doesn't do anything
               if vertexTriplet[2] is not None:
                    (x, y, z) = normals[vertexTriplet[2]]


          if len(screenPoints) > 2:
               canvas.create_polygon(screenPoints, outline="white", fill = "gray")


root.bind("<Key>", moveCamera)
