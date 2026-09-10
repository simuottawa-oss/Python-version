class SceneObject:
    def __init__(self, name="Object", meshPath=None):
        self.name = name
        self.meshPath = meshPath

    # -------------------------------------------------
    # Static Properties
    # -------------------------------------------------

        self.position = [0.0, 0.0, 0.0]
        self.rotation = [0.0, 0.0, 0.0]
        self.scale = [1.0, 1.0, 1.0]

    # -------------------------------------------------
    # Dynamic Properties
    # -------------------------------------------------
    
        self.velocity = [0.0, 0.0, 0.0]
        self.acceleration = [0.0, 0.0, 0.0]
        self.angularVelocity = [0.0, 0.0, 0.0]

    # -------------------------------------------------
    # Static Functions
    # -------------------------------------------------

    def setPosition(self, x, y, z):
        self.position = [x, y, z]

    def setRotation(self, x, y, z):
        self.rotation = [x, y, z]

    def setVelocity(self, x, y, z):
        self.velocity = [x, y, z]

    def setAcceleration(self, x, y, z):
        self.acceleration = [x, y, z]


class Scene:
    def __init__(self):
        self.filepath = None
        self.objects = []
        self.dirty = False

    def addObject(self, obj):
        self.objects.append(obj)
    
    def sceneHasObjects(self):
        for sceneObject in self.objects:
            return True

        return False
