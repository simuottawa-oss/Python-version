"""Validated SI JSON parts: v1 boxes, v2 sketches and v3 feature solids."""
from dataclasses import dataclass
import json
import math
from pathlib import Path
import re


def number(value, label, minimum=None, maximum=None):
    """Validate a finite numeric scalar, excluding booleans, against optional inclusive
    bounds.

    Args:
        value (int or float): Finite numeric value; booleans are rejected.
        label (str): Field name used in validation error messages.
        minimum (float, optional): Inclusive lower bound; None leaves it unbounded.
        maximum (float, optional): Inclusive upper bound; None leaves it unbounded.

    Returns:
        float: Converted value; raises ValueError for invalid numbers or bounds
        violations.
    """
    try:
        valid = not isinstance(value, bool) and isinstance(value, (int, float)) and math.isfinite(value)
    except OverflowError:
        valid = False
    if not valid:
        raise ValueError(f"{label} must be a finite number")
    if minimum is not None and value < minimum:
        raise ValueError(f"{label} must be >= {minimum}")
    if maximum is not None and value > maximum:
        raise ValueError(f"{label} must be <= {maximum}")
    return float(value)


def vector(value, label, positive=False):
    """Validate a JSON three-component numeric list, optionally requiring positive
    components.

    Args:
        value (list): Exactly three finite numeric components; booleans are rejected.
        label (str): Field name used in validation error messages.
        positive (bool): Require every component to be strictly positive when True.

    Returns:
        tuple: Three finite floats; raises ValueError for invalid input.
    """
    if not isinstance(value, list) or len(value) != 3:
        raise ValueError(f"{label} must contain three numbers")
    result = tuple(number(x, label) for x in value)
    if positive and any(x <= 0 for x in result):
        raise ValueError(f"{label} components must be positive")
    return result


def fields(value, label, required, optional=()):
    """Check that a JSON object contains all required keys and no unsupported keys.

    Args:
        value (dict): JSON object whose required and allowed keys are checked.
        label (str): Field name used in validation error messages.
        required (iterable): Keys that the JSON object must contain.
        optional (iterable): Additional allowed JSON keys; empty by default.

    Returns:
        dict: The original object, without copying; raises ValueError for a schema
        mismatch.
    """
    if not isinstance(value, dict):
        raise ValueError(f"{label} must be an object")
    missing = set(required) - value.keys()
    unknown = value.keys() - set(required) - set(optional)
    if missing or unknown:
        raise ValueError(f"{label}: missing {sorted(missing)}, unsupported {sorted(unknown)}")
    return value


def string(value, label):
    """Validate that a value is a nonempty string after whitespace checking.

    Args:
        value (str): String that must contain at least one non-whitespace character.
        label (str): Field name used in validation error messages.

    Returns:
        str: Original string, preserving whitespace; raises ValueError if invalid.
    """
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
    mass_source: str = "density"
    sketch: object = None
    features: object = None

    @property
    def volume(self):
        """Calculate unscaled volume from box dimensions, sketch area and thickness, or the
        feature union.

        Returns:
            float: Volume in cubic metres; draft geometry can have zero volume.
        """
        if self.features is not None:
            return self.features.volume
        if self.sketch is not None:
            return abs(self.sketch.signed_area)*self.sketch.thickness
        return math.prod(self.size)

    @property
    def inertia(self):
        """Estimate diagonal inertia with the bounding-box formula, exact for a uniform box
        and approximate for other geometry.

        Returns:
            tuple: Ixx, Iyy, Izz in kg m² using the part's unscaled dimensions and mass.
        """
        x, y, z = self.size
        return tuple(self.mass * v / 12 for v in (y*y + z*z, x*x + z*z, x*x + y*y))

    def vertices(self, position):
        """Translate geometry points by a supplied position without rotation or scaling.

        Args:
            position (sequence): XYZ translation in metres added to local geometry
                points.

        Returns:
            list: XYZ tuples in metres; box corners, sketch cap points, or feature mesh
            positions, without normals.
        """
        if self.features is not None:
            points = self.features.vertices.reshape(-1,6)[:,:3]
            return [tuple(p[i]+position[i] for i in range(3)) for p in points]
        if self.sketch is not None:
            cx,cy = self.sketch.centroid
            return [(position[0]+x-cx,position[1]+y-cy,position[2]+z)
                    for z in (-self.sketch.thickness/2,self.sketch.thickness/2)
                    for x,y in self.sketch.outline_points]
        x, y, z = (s / 2 for s in self.size)
        return [(position[0] + a, position[1] + b, position[2] + c)
                for a, b, c in [(-x,-y,-z),(x,-y,-z),(x,y,-z),(-x,y,-z),
                                (-x,-y,z),(x,-y,z),(x,y,z),(-x,y,z)]]


def load_part(path, allow_draft=False):
    """Parse and validate an SI JSON part, including geometry, material, derived mass, and
    initial state. Custom properties are inert metadata.

    Args:
        path (str or Path): Source or destination file path used by this operation.
        allow_draft (bool): Permit unfinished sketches or feature histories with no
            solid; False requires scene-importable geometry.

    Returns:
        Part: Validated frozen definition; malformed data raises ValueError and file
        errors propagate.
    """
    def unique_pairs(pairs):
        """Build a decoded JSON object while rejecting duplicate keys.

        Args:
            pairs (list): Decoded JSON key/value pairs before construction of an object.

        Returns:
            dict: Object made from the supplied pairs; duplicates raise ValueError.
        """
        result = {}
        for key, value in pairs:
            if key in result:
                raise ValueError(f"Duplicate JSON key: {key}")
            result[key] = value
        return result

    def invalid_constant(value):
        """Reject the JSON parser's non-finite constants such as NaN or Infinity.

        Args:
            value (object): Decoded value to validate; accepted type depends on the
                field contract.

        Returns:
            No return value: Always raises ValueError.
        """
        raise ValueError(f"Non-finite JSON constant: {value}")

    with Path(path).open(encoding="utf-8-sig") as stream:
        d = json.load(stream, object_pairs_hook=unique_pairs, parse_constant=invalid_constant,
                      parse_float=lambda value: number(float(value), "JSON number"))
    fields(d, "part", ["format", "version", "id", "name", "units", "coordinates",
                       "geometry", "appearance", "material", "physics", "initial_state"],
           ["description", "properties"])
    if d["format"] != ".simuOPart" or type(d["version"]) is not int or d["version"] not in (1,2,3):
        raise ValueError("Expected .simuOPart version 1 (box), 2 (sketch), or 3 (features)")
    if d["units"] != {"length": "m", "mass": "kg", "time": "s"}:
        raise ValueError("Only SI units (m, kg, s) are supported")
    if d["coordinates"] != {"handedness": "right", "up": "+Y"}:
        raise ValueError("Expected right-handed coordinates with +Y up")
    sketch = None
    features = None
    if d["version"] == 1:
        g = fields(d["geometry"], "geometry", ["type", "size"])
        if g["type"] != "box":
            raise ValueError("SimuO part v1 supports solid boxes only")
        size = vector(g["size"], "geometry.size", positive=True)
        volume = math.prod(size)
    elif d["version"] == 2:
        from simuo.parts.sketch_geometry import Sketch
        sketch = Sketch.from_geometry(d["geometry"])
        if not sketch.closed and not allow_draft:
            raise ValueError("This part is an unfinished sketch. Close its outline in the Part Editor before importing it.")
        xs = [p[0] for p in sketch.outline_points] or [0]
        ys = [p[1] for p in sketch.outline_points] or [0]
        size = (max(xs)-min(xs),max(ys)-min(ys),sketch.thickness)
        volume = abs(sketch.signed_area)*sketch.thickness
    else:
        from simuo.parts.feature_geometry import FeatureModel
        features = FeatureModel.from_geometry(d["geometry"])
        if not features.has_solid and not allow_draft:
            raise ValueError("This part has no solid. Extrude a closed sketch in the Part Editor before importing it.")
        size,volume = features.size,features.volume
    draft = (sketch is not None and not sketch.closed) or (features is not None and not features.has_solid)
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
        mass = density * volume
    elif p["mass_source"] == "explicit":
        mass = number(p.get("mass"), "physics.mass", minimum=0)
    else:
        raise ValueError("mass_source must be density or explicit")
    if (mass <= 0 and not draft) or not math.isfinite(mass):
        raise ValueError("Part mass must be positive and finite")
    try:
        inertia = [mass * (size[i]**2 + size[j]**2) / 12 for i, j in [(1,2),(0,2),(0,1)]]
    except OverflowError as error:
        raise ValueError("Box inertia exceeds the supported numerical range") from error
    if any(not math.isfinite(v) or (v <= 0 and not draft) for v in inertia):
        raise ValueError("Derived box inertia must be positive and finite")
    state = fields(d["initial_state"], "initial_state", ["position", "velocity"])
    position = vector(state["position"], "initial_state.position")
    velocity = vector(state["velocity"], "initial_state.velocity")
    if p["body_type"] == "static" and any(velocity):
        raise ValueError("Static parts must have zero initial velocity")
    properties = d.get("properties", {})
    if not isinstance(properties, dict) or any(":" not in k for k in properties):
        raise ValueError("properties must be an object with namespaced keys (e.g. demo:tag)")
    if "description" in d:
        string(d["description"], "description")
    return Part(string(d["id"], "id"), string(d["name"], "name"), size, a["color"],
                density, friction, restitution, p["body_type"], mass, position, velocity, properties,
                p["mass_source"], sketch, features)
