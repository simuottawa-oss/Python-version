import instance
import math
import tkinter as tk
from tkinter import *


camera = instance.instance(0.5,0.75,-1)
points = []
edges = []
scale = 800

root = tk.Tk()
root.title("Object Renderer")
canvas = tk.Canvas(root, height = 600, width = 800)
canvas.pack()
topLeft = instance.instance(400, 400, 400)
topRight = instance.instance(880, 1040, 400)
botLeft = instance.instance(400, 400, -200)
midPoint = instance.instance(640, 720, 100)
camPoint = instance.instance(680, 690, 100)
xMult = 4
yMult = -3
zMult = 0
constant = 400
width = 800
height = 600



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

     initX = x
     initY = y
     initZ = z
     k = (constant - xMult*x - yMult*y - zMult*z) / (xMult*(camPoint.getX() - x) + yMult*(camPoint.getY() - y) + zMult*(camPoint.getZ() - z))
     
     if (k == 0): 
          print("point " + str(initX) + " " + str(initY) + " " + str(initZ) + " is not visible")
          return "NaN","NaN"
     
     x = (camPoint.getX() - x) * k + x
     y = (camPoint.getY() - y) * k + y
     z = (camPoint.getZ() - z) * k + z

     cosu = ((topRight.getX() - topLeft.getX()) * (x - topLeft.getX()) + 
            (topRight.getY() - topLeft.getY()) * (y - topLeft.getY()) + 
            (topRight.getZ() - topLeft.getZ()) * (z - topLeft.getZ())) / \
            ((((x - topLeft.getX())**2 + 
             (y - topLeft.getY())**2 + 
             (z - topLeft.getZ())**2)**0.5)*width)
    
     cosv = ((botLeft.getX() - topLeft.getX()) * (x - topLeft.getX()) + 
            (botLeft.getY() - topLeft.getY()) * (y - topLeft.getY()) + 
            (botLeft.getZ() - topLeft.getZ()) * (z - topLeft.getZ())) / \
            ((((x - topLeft.getX())**2 + 
             (y - topLeft.getY())**2 + 
             (z - topLeft.getZ())**2)**0.5)*height)

     if (cosu < 0 or cosv < 0): 
          print("point " + str(initX) + " " + str(initY) + " " + str(initZ) + " is not visible")
          return "NaN","NaN"
     else:

          m = ((((x - topLeft.getX())**2 + 
          (y - topLeft.getY())**2 + 
          (z - topLeft.getZ())**2)**0.5)*cosu)

          n = ((((x - topLeft.getX())**2 + 
          (y - topLeft.getY())**2 + 
          (z - topLeft.getZ())**2)**0.5)*cosv)

          m = int(m)
          n = int(n)

          return m, n

     
         


     '''nearplane = camera.getZ()  + 0.1

     aspect = 20
    
     fov = 60
     z -= nearplane
     if (z == 0):
       return "NaN","NaN"
     x *= (nearplane * ((1 / (aspect*math.tan(math.radians(fov/2)))))) / z 
     y *= (nearplane * ((1/math.tan(fov/2))))/z
     return x,y'''

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
        
        x = point.getX()
        y = point.getY()
        z = point.getZ()

        '''
        x = point.getX() - camera.getX()
        y = point.getY() - camera.getY()
        z = point.getZ() - camera.getZ()
        '''

        screen_x, screen_y = calculateScreenCoord(x,y,z)

        point.setScreenCoords(screen_x, screen_y)

        '''
        screen_x*=scale
        screen_y*=scale

        centered_x = canvas_middle_width + screen_x
        centered_y = canvas_middle_height - screen_y
        '''
        
        radius = 5

        canvas.create_oval(screen_x-radius, screen_y-radius, screen_x+radius, screen_y+radius, fill="blue")
    
    for line in edges:
        '''
        centered_x1 = canvas_middle_width+points[line[0]].getScreenX()
        centered_y1 = canvas_middle_height-points[line[0]].getScreenY()
        centered_x2 = canvas_middle_width+points[line[1]].getScreenX()
        centered_y2 = canvas_middle_height-points[line[1]].getScreenY()
        '''
        centered_x1 = points[line[0]].getScreenX()
        centered_y1 = points[line[0]].getScreenY()
        centered_x2 = points[line[1]].getScreenX()
        centered_y2 = points[line[1]].getScreenY()
        
                
        canvas.create_line(centered_x1, centered_y1, centered_x2, centered_y2, fill = "white")
         
     
root.bind("<Key>", moveCamera)
