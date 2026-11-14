from pathlib import Path
from uuid import uuid4

from simuo.parts.part_assets import load_asset
from simuo.parts.part_format import number, vector
from simuo.materials import MaterialDefinition, inherited_material


BODY_TYPES = ("static", "dynamic", "kinematic")


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

    def __init__(self, name="Object", meshPath=None, identifier=None):
        """Initialize instance transform and motion state, optionally loading an asset and
        applying its spawn position, velocity, and default name.

        Args:
            name (str): Instance label; the default Object is replaced with the part
                name or asset stem.
            meshPath (str or Path, optional): Asset file to load; None creates an
                instance without geometry.

        Returns:
            None.
        """
        self.name = name
        self.identifier = identifier if isinstance(identifier, str) and identifier else uuid4().hex
        # Editor controls are independent of simulation state.
        self.editor_visible = True
        self.selection_locked = False
        self._group_visible = True
        self._group_locked = False
        self._isolated_out = False

        self.meshPath = meshPath

    # -------------------------------------------------
    # Static Properties
    # -------------------------------------------------

        self.position = [0.0, 0.0, 0.0]
        self.rotation = [0.0, 0.0, 0.0]
        self.scale = [1.0, 1.0, 1.0]
        self.localMin = None
        self.localMax = None

    # -------------------------------------------------
    # Dynamic Properties
    # -------------------------------------------------
    
        self.velocity = [0.0, 0.0, 0.0]
        self.acceleration = [0.0, 0.0, 0.0]
        self.angularVelocity = [0.0, 0.0, 0.0]
        self._restitution = None
        self._body_type = None
        self._material_override = None

        self.asset = None
        self.part = None
        if meshPath is not None:
            self.asset = load_asset(meshPath)
            self.part = self.asset.part
            points = self.asset.vertices.reshape(-1, 6)[:, :3]
            self.localMin = points.min(axis=0)
            self.localMax = points.max(axis=0)
            if self.part is not None:
                self.position = list(self.part.position)
                self.velocity = list(self.part.velocity)
            if name == "Object":
                self.name = self.part.name if self.part else Path(meshPath).stem

    # -------------------------------------------------
    # Static Functions
    # -------------------------------------------------

    @property
    def material_override(self):
        return self._material_override

    @material_override.setter
    def material_override(self, value):
        if value is not None and not isinstance(value, MaterialDefinition):
            raise ValueError("Invalid object material assignment")
        self._material_override = value

    @property
    def material(self):
        return self._material_override or inherited_material(self.part)

    @property
    def viewport_visible(self):
        return self.editor_visible and self._group_visible and not self._isolated_out

    @property
    def viewport_locked(self):
        return self.selection_locked or self._group_locked

    def setPosition(self, x, y, z):
        """Replace the instance's XYZ position without validating or marking its scene
        dirty.

        Args:
            x (float): X position component in metres.
            y (float): Y position component in metres.
            z (float): Z position component in metres.

        Returns:
            None. Stores a new position list.
        """
        self.position = [x, y, z]

    def setRotation(self, x, y, z):
        """Replace the instance's Euler angles without validating or marking its scene
        dirty.

        Args:
            x (float): X euler angle in degrees.
            y (float): Y euler angle in degrees.
            z (float): Z euler angle in degrees.

        Returns:
            None. Stores a new rotation list; rendering uses Rx * Ry * Rz.
        """
        self.rotation = [x, y, z]

    def setVelocity(self, x, y, z):
        """Replace the instance's starting linear velocity without validation.

        Args:
            x (float): X linear velocity component in m/s.
            y (float): Y linear velocity component in m/s.
            z (float): Z linear velocity component in m/s.

        Returns:
            None. Stores a new velocity list.
        """
        self.velocity = [x, y, z]

    @property
    def restitution(self):
        """Resolve bounce from the instance override, then the part default, then the
        legacy default.

        Returns:
            float: Effective restitution, defaulting to 0 for legacy meshes.
        """
        if self._restitution is not None:
            return self._restitution
        return self.part.restitution if self.part is not None else 0.0

    @restitution.setter
    def restitution(self, value):
        """Validate and store an instance bounce override without changing the part
        definition.

        Args:
            value (float): Finite instance bounce coefficient in [0, 1].

        Returns:
            None. Raises ValueError for values outside [0, 1] or non-finite numbers.
        """
        self._restitution = number(value, "Bounce", minimum=0, maximum=1)

    @property
    def body_type(self):
        """Resolve body behavior from the instance override or part definition.

        Returns:
            str: static, dynamic, or kinematic; legacy meshes default to static.
        """
        if self._body_type is not None:
            return self._body_type
        return self.part.body_type if self.part is not None else "static"

    @body_type.setter
    def body_type(self, value):
        """Store a validated instance body-type override.

        Args:
            value (str): Static, dynamic, or kinematic.

        Returns:
            None. Raises ValueError for unsupported body types.
        """
        if value not in BODY_TYPES:
            raise ValueError("Body type must be static, dynamic, or kinematic")
        self._body_type = value

    def setPhysicsProperties(self, bounce, velocity, body_type=None, acceleration=None):
        """Validate all requested physics edits before applying instance overrides and
        velocity. Does not mark the containing scene dirty.

        Args:
            bounce (float): Finite restitution coefficient between 0 and 1.
            velocity (list): Three finite starting linear velocity components in m/s.
            body_type (str, optional): Overrides the instance body type.
            acceleration (list, optional): Three finite acceleration components in m/s².

        Returns:
            None. Updates bounce, velocity, and optional body type; validation failures
            leave state unchanged.
        """
        bounce = number(bounce, "Bounce", minimum=0, maximum=1)
        velocity = vector(velocity, "Velocity")
        if body_type is not None and body_type not in BODY_TYPES:
            raise ValueError("Body type must be static, dynamic, or kinematic")
        if acceleration is not None:
            acceleration = vector(acceleration, "Acceleration")
        self.restitution = bounce
        self.velocity = list(velocity)
        if acceleration is not None:
            self.acceleration = list(acceleration)
        if body_type is not None:
            self.body_type = body_type

    def setAcceleration(self, x, y, z):
        """Replace the instance's additional acceleration without validation.

        Args:
            x (float): X additional acceleration component in m/s².
            y (float): Y additional acceleration component in m/s².
            z (float): Z additional acceleration component in m/s².

        Returns:
            None. Stores a new acceleration list used as force divided by mass during
            physics.
        """
        self.acceleration = [x, y, z]


class SceneGroup:
    """An organizational folder; membership never changes object transforms."""

    def __init__(self, name="Group", identifier=None):
        self.identifier = identifier if isinstance(identifier, str) and identifier else uuid4().hex
        self.name = name
        self.members = []
        self.expanded = True
        self.editor_visible = True
        self.selection_locked = False


class Scene:
    """Container for all objects in the active simulation scene."""

    def __init__(self):
        """Initialize an empty scene.

        Returns:
            Scene: A scene container with no objects.
        """
        self.filepath = None
        self.objects = []
        self.groups = []
        self.root_order = []
        self.dirty = False

    def addObject(self, obj):
        """Append an object to the scene.

        Args:
            obj: A SceneObject instance to add.
        """
        if any(existing.identifier == obj.identifier for existing in self.objects):
            obj.identifier = uuid4().hex
        self.objects.append(obj)
        self.root_order.append(obj.identifier)

    def normalize_hierarchy(self):
        """Repair old/malformed organization without losing any objects."""
        identifiers = {obj.identifier for obj in self.objects}
        used = set(identifiers)
        members = set()
        for group in self.groups:
            if group.identifier in used:
                group.identifier = uuid4().hex
            used.add(group.identifier)
            cleaned = []
            for key in group.members:
                if isinstance(key, str) and key in identifiers and key not in members:
                    cleaned.append(key)
                    members.add(key)
            group.members = cleaned
        valid = used - members
        roots = []
        for key in [*self.root_order, *(group.identifier for group in self.groups),
                    *(obj.identifier for obj in self.objects)]:
            if isinstance(key, str) and key in valid and key not in roots:
                roots.append(key)
        self.root_order = roots

    def sceneHasObjects(self):
        """Check whether the scene contains any objects.

        Returns:
            bool: True if at least one object exists, otherwise False.
        """
        for sceneObject in self.objects:
            return True

        return False
