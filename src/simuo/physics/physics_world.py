"""Independent scene snapshot, simulated by MuJoCo in Y-up SI coordinates."""
import copy
from functools import lru_cache
import math
import operator
from xml.etree.ElementTree import Element, SubElement, tostring

import numpy as np

from simuo.project.scene import Scene
from simuo.project.transforms import rotation_matrix


def quaternion(rotation):
    """Convert editor Rx * Ry * Rz Euler degrees to MuJoCo (w, x, y, z)."""
    x, y, z = (math.radians(v)/2 for v in rotation)
    sx, sy, sz = math.sin(x), math.sin(y), math.sin(z)
    cx, cy, cz = math.cos(x), math.cos(y), math.cos(z)
    return (cx*cy*cz - sx*sy*sz, sx*cy*cz + cx*sy*sz,
            cx*sy*cz - sx*cy*sz, cx*cy*sz + sx*sy*cz)


def editor_rotation(matrix):
    """Convert a 3x3 matrix to editor Euler degrees; choose Z=0 at gimbal lock."""
    r = np.asarray(matrix).reshape(3, 3)
    y = math.asin(max(-1, min(1, r[0, 2])))
    if abs(math.cos(y)) > 1e-7:
        x, z = math.atan2(-r[1, 2], r[2, 2]), math.atan2(-r[0, 1], r[0, 0])
    else:
        x, z = math.atan2(r[2, 1], r[1, 1]), 0
    return [math.degrees(v) for v in (x, y, z)]


def state_vector(value, label, positive=False):
    """Validate a finite XYZ state vector, optionally requiring positive scale."""
    result = np.asarray(value, dtype=float)
    if result.shape != (3,) or not np.isfinite(result).all():
        raise ValueError(f"{label} must contain three finite numbers")
    if positive and np.any(result <= 0):
        raise ValueError(f"{label} must be positive for physics rendering")
    return result.tolist()


def _numbers(values):
    return " ".join(format(float(v), ".17g") for v in np.asarray(values).ravel())


@lru_cache(maxsize=128)
def contact_reference(restitution):
    """Approximate bounce using a damped oscillator in MuJoCo's direct format.

    The scene coefficient is a target, not an exact impact law: soft contact,
    timestep, geometry and simultaneous contacts affect measured restitution.
    Use the unilateral spring/damper restitution relation: contact ends when
    force reaches zero, rather than when the spring returns to zero compression.
    Zero bounce uses a small dissipative limit; one is undamped. Cap damping
    relative to our substep to avoid a single explicit contact impulse reversing
    a critically damped impact. Stiffness is constraint-normalized in s^-2.
    """
    target = max(.005, min(1.0, restitution))
    low, high = 0.0, 32.0
    for _ in range(48):
        ratio = (low + high)/2
        if abs(ratio-1) < 1e-10:
            rebound = math.exp(-2)
        elif ratio < 1:
            rebound = math.exp(-2*ratio*math.acos(ratio)/math.sqrt(1-ratio*ratio))
        else:
            rebound = math.exp(-2*ratio*math.acosh(ratio)/math.sqrt(ratio*ratio-1))
        if rebound > target:
            low = ratio
        else:
            high = ratio
    ratio = (low + high)/2 if restitution < 1 else 0
    stiffness = min(1e6, (1000/(2*ratio))**2) if ratio else 1e6
    return (-stiffness, -2*ratio*math.sqrt(stiffness))


class PhysicsWorld:
    """Own a private model/data pair and expose simulation through scene state.

    Dynamic objects have free joints. Kinematic objects are massless mocap
    bodies with prescribed translation and fixed orientation. Static meshes use
    thin triangle prisms so their concavities are not filled by a convex hull.
    """
    dt = 1/240
    substeps = 8
    surface_thickness = 1e-5  # metres, total thickness of a collision surface

    def __init__(self, source_scene, gravity=-9.81, floor=True):
        # Keep editing/importing available without loading the solver library.
        import mujoco
        self._mj = mujoco
        self.model = self.data = None
        self.closed = False
        self.gravity = gravity
        self.floor = floor
        self.scene = Scene()
        self.initial = []
        self.bodies = []
        self.masses = []
        self.legacy_count = 0
        self.steps = 0
        try:
            for source in source_scene.objects:
                if source.asset is None:
                    continue
                obj = copy.copy(source)
                for name in ("position", "rotation", "velocity", "acceleration", "angularVelocity", "scale"):
                    setattr(obj, name, state_vector(getattr(source, name), f"{source.name}: {name}", name == "scale"))
                self.scene.addObject(obj)
                self.initial.append({name: list(getattr(obj, name)) for name in
                                     ("position", "rotation", "velocity", "angularVelocity", "acceleration")})
            self._build()
        except BaseException:
            self.close()
            raise

    def _build(self):
        """Compile an in-memory MJCF model; never write generated scene assets."""
        self.set_gravity(self.gravity)
        root = Element("mujoco", model="SimuO playback")
        SubElement(root, "compiler", angle="radian", fusestatic="false")
        option = SubElement(root, "option", timestep=str(self.dt/self.substeps),
                            gravity=_numbers([0, self.gravity, 0]), integrator="implicitfast",
                            solver="Newton", iterations="80", cone="elliptic")
        SubElement(option, "flag", autoreset="disable")
        default = SubElement(root, "default")
        SubElement(default, "geom", condim="3", solimp="0.99 0.99 0.001",
                   solref=_numbers(contact_reference(0)), margin="0")
        assets = SubElement(root, "asset")
        world = SubElement(root, "worldbody")
        materials = {}  # geom name -> (friction, restitution)
        if self.floor:
            # MuJoCo planes face local +Z; rotate to face world +Y.
            SubElement(world, "geom", name="floor", type="plane", size="0 0 .1",
                       quat=_numbers([math.sqrt(.5), -math.sqrt(.5), 0, 0]))
            materials["floor"] = (1.0, 1.0)
        self.bodies = []
        self.masses = []
        self.legacy_count = 0
        for index, obj in enumerate(self.scene.objects):
            dynamic = obj.body_type == "dynamic"
            part = obj.part
            scale = np.asarray(obj.scale)
            mass = (part.mass * (float(np.prod(scale)) if part.mass_source == "density" else 1)
                    if part else 1.0) if dynamic else 0.0
            if not math.isfinite(mass) or (dynamic and mass <= 0):
                raise ValueError(f"{obj.name}: scaled mass must be finite and positive")
            self.masses.append(mass)
            self.legacy_count += part is None
            body = SubElement(world, "body", name=f"body_{index}",
                              pos=_numbers(obj.position), quat=_numbers(quaternion(obj.rotation)))
            if dynamic:
                SubElement(body, "freejoint", name=f"joint_{index}")
            elif obj.body_type == "kinematic":
                body.set("mocap", "true")
            friction = part.friction if part else .5
            box = part is not None and part.sketch is None and part.features is None
            if box:
                size = np.asarray(part.size)*scale
                if not np.isfinite(size).all() or np.any(size <= 0):
                    raise ValueError(f"{obj.name}: scaled size must be finite and positive")
                geoms = [SubElement(body, "geom", type="box", size=_numbers(size/2), mass=str(mass))]
            else:
                vertices = obj.asset.vertices.reshape(-1, 6)[:, :3].astype(float)*scale
                if not np.isfinite(vertices).all() or len(vertices) < 3:
                    raise ValueError(f"{obj.name}: collision mesh must contain finite triangles")
                geoms = self._mesh_geoms(assets, body, index, vertices, obj.body_type == "static", mass)
            for number, geom in enumerate(geoms):
                name = f"geom_{index}_{number}"
                geom.set("name", name)
                materials[name] = (friction, obj.restitution)
        self.model = self._mj.MjModel.from_xml_string(tostring(root, encoding="unicode"))
        self.data = self._mj.MjData(self.model)
        self._materials = np.empty((self.model.ngeom, 2))
        for name, material in materials.items():
            self._materials[self.model.geom(name).id] = material
        self._kinematic = {}
        for index, obj in enumerate(self.scene.objects):
            body = self.model.body(f"body_{index}").id
            self.bodies.append(body)
            if obj.body_type == "dynamic":
                dof = self.model.jnt_dofadr[self.model.body_jntadr[body]]
                self.data.qvel[dof:dof+3] = obj.velocity
                # Free-joint angular velocity is local; the scene stores world XYZ.
                self.data.qvel[dof+3:dof+6] = rotation_matrix(obj.rotation).T @ obj.angularVelocity
            elif obj.body_type == "kinematic":
                self._kinematic[body] = obj
        self._mj.mj_forward(self.model, self.data)
        self._accelerated = [(body, np.asarray(obj.acceleration)*mass)
                             for obj, body, mass in zip(self.scene.objects, self.bodies, self.masses)
                             if mass and any(obj.acceleration)]

    def _mesh_geoms(self, assets, body, index, vertices, static, mass):
        """Use moving convex hulls, or two-sided triangle prisms for static meshes."""
        if not static:
            points = np.unique(vertices, axis=0)
            if len(points) < 3:
                raise ValueError("Moving collision mesh has no nondegenerate surface")
            center = points.mean(axis=0)
            points = points - center
            _, spans, axes = np.linalg.svd(points, full_matrices=False)
            tolerance = spans[0] * 4 * np.finfo(np.float32).eps
            if spans[1] <= tolerance:
                raise ValueError("Moving collision mesh has no nondegenerate surface")
            if spans[2] <= tolerance:
                # MuJoCo needs a solid hull. Give planar surfaces thickness along
                # their normal in the collision model only.
                offset = axes[-1] * self.surface_thickness/2
                points = np.concatenate([points-offset, points+offset])
            chunks = [(center, points)]
        else:
            chunks = []
            for triangle in vertices.reshape(-1, 3, 3):
                normal = np.cross(triangle[1]-triangle[0], triangle[2]-triangle[0])
                length = np.linalg.norm(normal)
                if length <= 1e-15:
                    continue
                offset = normal/length * self.surface_thickness/2
                center = triangle.mean(axis=0)
                points = triangle - center
                chunks.append((center, np.concatenate([points-offset, points+offset])))
        if not chunks:
            raise ValueError("Collision mesh has no nondegenerate triangles")
        geoms = []
        for number, (center, points) in enumerate(chunks):
            name = f"mesh_{index}_{number}"
            # Keep thin hulls near zero before MuJoCo converts their vertices to
            # float32. Otherwise a large local OBJ offset can erase their thickness.
            SubElement(assets, "mesh", name=name, vertex=_numbers(points))
            geoms.append(SubElement(body, "geom", type="mesh", mesh=name,
                                    pos=_numbers(center), mass=str(mass)))
        return geoms

    @property
    def time(self):
        """Elapsed simulation seconds, independent of wall-clock playback speed."""
        return self.steps*self.dt

    def set_gravity(self, value):
        """Set finite world-Y acceleration, preserving current scene state."""
        if not math.isfinite(value):
            raise ValueError("Gravity must be finite")
        self.gravity = value
        if self.model is not None:
            self.model.opt.gravity[:] = [0, value, 0]

    def _prepare_contacts(self):
        """Combine scene materials and include prescribed mocap contact velocity.

        MuJoCo has no restitution coefficient. Contact parameters are set before
        rebuilding the constraint rows. Mocap bodies have no velocity DOFs, so
        add their prescribed velocity/acceleration to the constraint reference.
        No process-global callbacks are installed; worlds remain independent.
        """
        m, d, mj = self.model, self.data, self._mj
        if not d.ncon:
            return
        # The bindings expose contact fields as array views. Assign materials in
        # batches rather than looping over every constraint in Python.
        contacts = d.contact
        first, second = self._materials[contacts.geom1], self._materials[contacts.geom2]
        contacts.friction[:, :2] = np.maximum(1e-5, first[:, 0]*second[:, 0])[:, None]
        bounce = first[:, 1]*second[:, 1]
        for coefficient in np.unique(bounce):
            contacts.solref[bounce == coefficient] = contact_reference(float(coefficient))
        contacts.solreffriction[:] = contact_reference(0)
        mj.mj_makeConstraint(m, d)
        mj.mj_island(m, d)
        mj.mj_projectConstraint(m, d)
        mj.mj_referenceConstraint(m, d)
        if not self._kinematic:
            return
        for contact in d.contact:
            address = contact.efc_address
            if address < 0:
                continue
            velocity = np.zeros(3)
            acceleration = np.zeros(3)
            for sign, geom in ((-1, contact.geom1), (1, contact.geom2)):
                obj = self._kinematic.get(m.geom_bodyid[geom])
                if obj is not None:
                    velocity += sign*np.asarray(obj.velocity)
                    acceleration += sign*np.asarray(obj.acceleration)
            if np.any(velocity) or np.any(acceleration):
                frame = contact.frame.reshape(3, 3)
                rows = slice(address, address+3)  # elliptic condim=3
                change = frame @ velocity
                d.efc_vel[rows] += change
                d.efc_aref[rows] -= d.efc_KBIP[rows, 1]*change + frame @ acceleration

    def step(self, count=1):
        """Advance fixed outer steps, applying additional acceleration in world XYZ."""
        if self.closed:
            raise RuntimeError("Physics world is closed")
        count = operator.index(count)
        if count < 0:
            raise ValueError("Step count must be nonnegative")
        m, d, mj = self.model, self.data, self._mj
        h = self.dt/self.substeps
        for _ in range(count):
            for _ in range(self.substeps):
                d.xfrc_applied[:] = 0
                for body, force in self._accelerated:
                    d.xfrc_applied[body, :3] = force
                for body, obj in self._kinematic.items():
                    d.mocap_pos[m.body_mocapid[body]] = obj.position
                mj.mj_step1(m, d)
                self._prepare_contacts()
                mj.mj_step2(m, d)
                for body, obj in self._kinematic.items():
                    velocity, acceleration = np.asarray(obj.velocity), np.asarray(obj.acceleration)
                    obj.position = (np.asarray(obj.position) + velocity*h + acceleration*h*h/2).tolist()
                    obj.velocity = (velocity + acceleration*h).tolist()
                    d.mocap_pos[m.body_mocapid[body]] = obj.position
                if not np.isfinite(d.qpos).all() or not np.isfinite(d.qvel).all():
                    raise RuntimeError("Physics produced non-finite state")
                for warning in range(int(mj.mjtWarning.mjNWARNING)):
                    if d.warning[warning].number:
                        name = mj.mjtWarning(warning).name
                        raise RuntimeError(f"MuJoCo simulation warning: {name}")
            self.steps += 1
        self.sync()

    def sync(self):
        """Copy dynamic poses and world-frame velocities into the playback scene."""
        if self.closed:
            raise RuntimeError("Physics world is closed")
        m, d = self.model, self.data
        for obj, body, mass in zip(self.scene.objects, self.bodies, self.masses):
            if not mass:
                continue
            joint = m.body_jntadr[body]
            pos, dof = m.jnt_qposadr[joint], m.jnt_dofadr[joint]
            matrix = np.empty(9)
            self._mj.mju_quat2Mat(matrix, d.qpos[pos+3:pos+7])
            obj.position = d.qpos[pos:pos+3].tolist()
            obj.rotation = editor_rotation(matrix)
            obj.velocity = d.qvel[dof:dof+3].tolist()
            obj.angularVelocity = (matrix.reshape(3, 3) @ d.qvel[dof+3:dof+6]).tolist()

    def reset(self):
        """Restore initial scene motion and rebuild, including a changed floor flag."""
        if self.closed:
            raise RuntimeError("Physics world is closed")
        self.steps = 0
        for obj, state in zip(self.scene.objects, self.initial):
            for name, value in state.items():
                setattr(obj, name, list(value))
        self._build()

    def close(self):
        """Release native model/data references; safe to call more than once."""
        self.data = self.model = None
        self.closed = True
