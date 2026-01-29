import cppCalculations 
import customtkinter as ctk
meshCube = cppCalculations.createMesh()

# Setup
def openApplication():

    simuO = ctk.CTk()

    simuO.title = "SimuO"
    simuO.geometry("800x600")
    
    
    
    print("On user create status... " + str(onUserCreate()))
    simuO.mainloop()
    return True

        
def onUserCreate():
    meshCube.setTris([
        
        # South
        [0.0,0.0,0.0,0.0,1.0,0.0,1.0,1.0,0.0],
    ])
    return True

def onUserUpdate(elapsedTime):
    return True


print("opening application status..." + str(openApplication()))



