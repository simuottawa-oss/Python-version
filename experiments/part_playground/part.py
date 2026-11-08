"""Independent SI-unit part loader and intentionally limited box/floor physics."""
from dataclasses import dataclass, field
import json
import math
from pathlib import Path
import re


def number(value, label, minimum=None, maximum=None):
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
        raise ValueError(f"{label} must be a finite number")
    if minimum is not None and value < minimum:
        raise ValueError(f"{label} must be >= {minimum}")
    if maximum is not None and value > maximum:
        raise ValueError(f"{label} must be <= {maximum}")
    return float(value)


def vector(value, label, positive=False):
    if not isinstance(value, list) or len(value) != 3:
        raise ValueError(f"{label} must contain three numbers")
    result = tuple(number(x, label) for x in value)
    if positive and any(x <= 0 for x in result):
        raise ValueError(f"{label} components must be positive")
    return result


def fields(value, label, required, optional=()):
    if not isinstance(value, dict):
        raise ValueError(f"{label} must be an object")
    missing = set(required) - value.keys()
    unknown = value.keys() - set(required) - set(optional)
    if missing or unknown:
        raise ValueError(f"{label}: missing {sorted(missing)}, unsupported {sorted(unknown)}")
    return value


def string(value, label):
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{label} must be a nonempty string")
    return value


@dataclass(frozen=True)
class Part:
    id: str
    name: str
    size: tuple
    color: str
    density: float
    friction: float
    restitution: float
    body_type: str
    mass: float
    position: tuple
    velocity: tuple
    properties: dict

    @property
    def volume(self):
        return math.prod(self.size)

    @property
    def inertia(self):
        """Diagonal inertia about the geometric center, in kg m²."""
        x, y, z = self.size
        return tuple(self.mass * v / 12 for v in (y*y + z*z, x*x + z*z, x*x + y*y))

    def vertices(self, position):
        x, y, z = (s / 2 for s in self.size)
        return [(position[0] + a, position[1] + b, position[2] + c)
                for a, b, c in [(-x,-y,-z),(x,-y,-z),(x,y,-z),(-x,y,-z),
                                (-x,-y,z),(x,-y,z),(x,y,z),(-x,y,z)]]


def load_part(path):
    """Fail closed on unsupported physical semantics; properties are inert metadata."""
    def unique_pairs(pairs):
        result = {}
        for key, value in pairs:
            if key in result:
                raise ValueError(f"Duplicate JSON key: {key}")
            result[key] = value
        return result

    def invalid_constant(value):
        raise ValueError(f"Non-finite JSON constant: {value}")

    with Path(path).open(encoding="utf-8") as stream:
        d = json.load(stream, object_pairs_hook=unique_pairs, parse_constant=invalid_constant)
    fields(d, "part", ["format", "version", "id", "name", "units", "coordinates",
                       "geometry", "appearance", "material", "physics", "initial_state"],
           ["description", "properties"])
    if d["format"] != ".simuOPart" or type(d["version"]) is not int or d["version"] != 1:
        raise ValueError("Expected .simuOPart version 1")
    if d["units"] != {"length": "m", "mass": "kg", "time": "s"}:
        raise ValueError("Only SI units (m, kg, s) are supported")
    if d["coordinates"] != {"handedness": "right", "up": "+Y"}:
        raise ValueError("Expected right-handed coordinates with +Y up")
    g = fields(d["geometry"], "geometry", ["type", "size"])
    if g["type"] != "box":
        raise ValueError("This prototype supports solid boxes only")
    size = vector(g["size"], "geometry.size", positive=True)
    a = fields(d["appearance"], "appearance", ["color"])
    if not isinstance(a["color"], str) or not re.fullmatch(r"#[0-9a-fA-F]{6}", a["color"]):
        raise ValueError("appearance.color must be #RRGGBB")
    m = fields(d["material"], "material", ["name", "density", "friction", "restitution"])
    string(m["name"], "material.name")
    density = number(m["density"], "material.density", minimum=0)
    if density == 0:
        raise ValueError("material.density must be positive")
    friction = number(m["friction"], "material.friction", minimum=0)
    restitution = number(m["restitution"], "material.restitution", minimum=0, maximum=1)
    p = fields(d["physics"], "physics", ["body_type", "mass_source", "collider"], ["mass"])
    if p["body_type"] not in ("dynamic", "static") or p["collider"] != "geometry":
        raise ValueError("Expected dynamic/static body and collider=geometry")
    if p["mass_source"] == "density":
        if "mass" in p:
            raise ValueError("density mass source cannot also specify mass")
        mass = density * math.prod(size)
    elif p["mass_source"] == "explicit":
        mass = number(p.get("mass"), "physics.mass", minimum=0)
    else:
        raise ValueError("mass_source must be density or explicit")
    if mass <= 0 or not math.isfinite(mass):
        raise ValueError("Part mass must be positive and finite")
    inertia = [mass * (size[i]**2 + size[j]**2) / 12 for i, j in [(1,2),(0,2),(0,1)]]
    if any(not math.isfinite(v) or v <= 0 for v in inertia):
        raise ValueError("Derived box inertia must be positive and finite")
    state = fields(d["initial_state"], "initial_state", ["position", "velocity"])
    position = vector(state["position"], "initial_state.position")
    velocity = vector(state["velocity"], "initial_state.velocity")
    if position[1] < size[1] / 2:
        raise ValueError("Initial box overlaps the demo floor at y=0")
    if p["body_type"] == "static" and any(velocity):
        raise ValueError("Static parts must have zero initial velocity")
    properties = d.get("properties", {})
    if not isinstance(properties, dict) or any(":" not in k for k in properties):
        raise ValueError("properties must be an object with namespaced keys (e.g. demo:tag)")
    if "description" in d:
        string(d["description"], "description")
    return Part(string(d["id"], "id"), string(d["name"], "name"), size, a["color"],
                density, friction, restitution, p["body_type"], mass, position, velocity, properties)


@dataclass
class Simulation:
    part: Part
    position: list = field(init=False)
    velocity: list = field(init=False)
    time: float = field(init=False, default=0)
    steps: int = field(init=False, default=0)
    gravity: float = -9.81
    dt: float = 1 / 240

    def __post_init__(self):
        self.reset()

    def reset(self):
        self.position = list(self.part.position)
        self.velocity = list(self.part.velocity)
        self.time = 0
        self.steps = 0

    def step(self):
        """Semi-implicit Euler, floor impulse, then Coulomb tangential friction.

        Axis-aligned, translation-only body; floor material uses part coefficients
        directly. Not a general rigid-body solver.
        """
        if self.part.body_type == "dynamic":
            self.velocity[1] += self.gravity * self.dt
            for i in range(3):
                self.position[i] += self.velocity[i] * self.dt
            floor_height = self.part.size[1] / 2
            if self.position[1] <= floor_height:
                self.position[1] = floor_height
                incoming = min(self.velocity[1], 0)
                outgoing = -incoming * self.part.restitution
                # Suppress sub-step chatter without hiding ordinary impacts.
                if outgoing < abs(self.gravity) * self.dt * 2:
                    outgoing = 0
                self.velocity[1] = outgoing
                impulse_per_mass = outgoing - incoming
                speed = math.hypot(self.velocity[0], self.velocity[2])
                if speed:
                    scale = max(0, 1 - self.part.friction * impulse_per_mass / speed)
                    self.velocity[0] *= scale
                    self.velocity[2] *= scale
        self.steps += 1
        self.time = self.steps * self.dt
