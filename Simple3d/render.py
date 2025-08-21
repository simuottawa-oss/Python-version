import instance
import math
import tkinter as tk
from tkinter import *


camera = instance.instance(0.5,0.75,-1)
points = []
edges = []
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

          if coordinates and coordinates[0] == "l":
               pointOne = int(coordinates[1])
               pointTwo = int(coordinates[2])
               edge = (pointOne,pointTwo)
               edges.append(edge)
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
         
     
root.bind("<Key>", moveCamera)
