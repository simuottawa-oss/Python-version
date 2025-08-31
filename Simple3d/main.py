import tkinter as tk
from tkinter import *
from tkinter import filedialog
import render as rd
from turtle import *

# new window
def newWindow():
    
    # Root
    root = tk.Tk()
    root.title("3d areodynamics simulator")
    root.geometry("1000x1000") 
    
    # Button to quit
    quit = tk.Button(root, text="Quit", command=root.destroy)
    quit.place(relx=0,rely=0)

    # Button to add filed
    fileSelect = tk.Button(root, text="Select File", command=open_file)
    fileSelect.place(relx=0.5,rely=0.5,anchor=tk.CENTER)
    
    # Run and exit
    root.mainloop()
    return root

def open_file():
    
    filename = filedialog.askopenfilename(title = "Select a File")
    if len(filename)>0:
        
        print(f"Selected file: {filename}")
        
        rd.initRender(filename)

newWindow()