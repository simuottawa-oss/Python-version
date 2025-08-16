import instance
import math
import tkinter as tk
from tkinter import *


camera = instance.instance(0.5,0.75,-1)
points = []
scale = 1000

root = tk.Tk()
root.title("Object Renderer")
canvas = tk.Canvas(root,height = 1000, width = 1000)
canvas.pack()

canvas_middle_width = int(canvas['width'])/2
canvas_middle_height = int(canvas['height'])/2

def initRender(filename):
        
        lines = open(filename)

        i = 0
        for line in lines:
            coordinates = line.split()
            if coordinates and coordinates[0] == "v":
                x = float(coordinates[1]) + camera.getX()
                y = float(coordinates[2]) -  camera.getY()
                z = float(coordinates[3])
                screen_x, screen_y = calculateScreenCoord(x,y,z)
                point = instance.instance(x,y,z)

                points.append(point)
                if screen_x != "NaN":
                    screen_x*=scale
                    screen_y*=scale
                    point.setScreenCoords(screen_x, screen_y)

                    centered_x = canvas_middle_width+screen_x
                    centered_y = canvas_middle_height-screen_y

                    radius = 5
                    circle = canvas.create_oval(centered_x-radius, centered_y+radius, centered_x+radius, centered_y-radius, fill="blue")

            if coordinates and coordinates[0] == "l":
                pointOne = int(coordinates[1])
                pointTwo = int(coordinates[2])

                centered_x1 = canvas_middle_width+points[pointOne].getScreenX()
                centered_y1 = canvas_middle_height-points[pointOne].getScreenY()
                centered_x2 = canvas_middle_width+points[pointTwo].getScreenX()
                centered_y2 = canvas_middle_height-points[pointTwo].getScreenY()
                
                line = canvas.create_line(centered_x1, centered_y1, centered_x2, centered_y2, fill = "white")
                
def calculateScreenCoord(x,y,z):

    nearplane = camera.getZ()  + 0.1
    farplane = nearplane + 10
    w = 1
    aspect = 20
    
    fov = 60
    z -= nearplane
    if (z == 0):
         return "NaN","NaN"
    x *= (nearplane * ((1 / (aspect*math.tan(math.radians(fov/2)))))) / z 
    y *= (nearplane * ((1/math.tan(fov/2))))/z
    return x,y
    
