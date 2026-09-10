class SceneObject:
    def __init__(
        self,
        name="Object",
        meshPath=None
    ):
        self.name = name
        self.meshPath = meshPath

        self.position = [0.0, 0.0, 0.0]
        self.rotation = [0.0, 0.0, 0.0]
        self.scale = [1.0, 1.0, 1.0]
    def setPosition(
        self,
        x,
        y,
        z
    ):
        self.position = [x, y, z]
        


class Scene:
    
    def __init__(self):
        self.filepath = None
        self.objects = []
        self.dirty = False
    def addObject(
        self,
        obj
    ):
        self.objects.append(
            obj
        )