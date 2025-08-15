
import instance
import math
import turtle
from turtle import *


camera = instance.instance(0.5,0.75,-1)
points = []
scale = 1000
screen = turtle.Screen()
my_turtle = turtle.Turtle()
my_turtle.penup()

def initRender(filename):
        
        lines = open(filename)

        i = 0
        for line in lines:
            coordinates = line.split()
            if coordinates[0] == "v":
                x = float(coordinates[1]) + camera.getX()
                y = float(coordinates[2]) -  camera.getY()
                z = float(coordinates[3])
                screen_x, screen_y = calculateScreenCoord(x,y,z)
                point = instance.instance(x,y,z)

                points.append(point)
                if screen_x != "NaN":
                    screen_x*=scale
                    screen_y*=scale


                    point.setScreenCoords(screen_x,screen_y)
                    my_turtle.hideturtle()
                    my_turtle.goto(screen_x, screen_y)
                    my_turtle.dot(10,"blue")
            if coordinates[0] == "l":
                pointOne = int(coordinates[1])
                pointTwo = int(coordinates[2])
                
                my_turtle.penup()
                my_turtle.teleport(points[pointOne].getScreenX(),points[pointOne].getScreenY()) 
                my_turtle.pendown()
                
                my_turtle.goto(points[pointTwo].getScreenX(),points[pointTwo].getScreenY())
                
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
    
