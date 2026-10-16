class SceneObject:
    """Represent a single mesh instance inside the simulation scene.

    Attributes:
        name: Human-readable label for the object.
        meshPath: Path to the OBJ model used by this object.
        position: [x, y, z] world position.
        rotation: [x, y, z] Euler rotation in degrees.
        scale: [x, y, z] scale factors.
        velocity: Current linear velocity.
        acceleration: Current linear acceleration.
        angularVelocity: Current rotational velocity.
    """

    def __init__(self, name="Object", meshPath=None):
        """Create a new scene object.

        Args:
            name: Display name for the object.
            meshPath: File path to the mesh asset for this object.
        """
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
        """Set the object's world-space position.

        Args:
            x: X coordinate.
            y: Y coordinate.
            z: Z coordinate.
        """
        self.position = [x, y, z]

    def setRotation(self, x, y, z):
        """Set the object's Euler rotation angles in degrees.

        Args:
            x: Rotation around the X axis.
            y: Rotation around the Y axis.
            z: Rotation around the Z axis.
        """
        self.rotation = [x, y, z]

    def setVelocity(self, x, y, z):
        """Set the object's linear velocity vector.

        Args:
            x: Velocity along X.
            y: Velocity along Y.
            z: Velocity along Z.
        """
        self.velocity = [x, y, z]

    def setAcceleration(self, x, y, z):
        """Set the object's linear acceleration vector.

        Args:
            x: Acceleration along X.
            y: Acceleration along Y.
            z: Acceleration along Z.
        """
        self.acceleration = [x, y, z]


class Scene:
    """Container for all objects in the active simulation scene."""

    def __init__(self):
        """Initialize an empty scene.

        Returns:
            Scene: A scene container with no objects.
        """
        self.filepath = None
        self.objects = []
        self.dirty = False

    def addObject(self, obj):
        """Append an object to the scene.

        Args:
            obj: A SceneObject instance to add.
        """
        self.objects.append(obj)

    def sceneHasObjects(self):
        """Check whether the scene contains any objects.

        Returns:
            bool: True if at least one object exists, otherwise False.
        """
        for sceneObject in self.objects:
            return True

        return False
