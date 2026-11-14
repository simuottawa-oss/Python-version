"""Validated, pickleable SI inputs and numerical result containers."""
from dataclasses import dataclass, field
import math
from uuid import uuid4
import numpy as np


def finite(value, label):
    if isinstance(value, (bool, np.bool_)) or not isinstance(value, (int, float, np.number)) or not math.isfinite(value):
        raise ValueError(f"{label} must be a finite number")
    return float(value)


def selection(value):
    items = tuple(value)
    if not items or any(type(i) is not int or i < 0 for i in items) or len(set(items)) != len(items):
        raise ValueError("A boundary selection needs unique source triangle indices")
    return tuple(sorted(items))


@dataclass(frozen=True)
class Material:
    young_modulus: float
    poisson_ratio: float
    density: float | None = None
    name: str = "Custom"
    preset_id: str | None = None

    def __post_init__(self):
        if not isinstance(self.name, str) or not self.name.strip() or (self.preset_id is not None and not isinstance(self.preset_id, str)):
            raise ValueError("Invalid material identity")
        if finite(self.young_modulus, "Young's modulus") <= 0:
            raise ValueError("Young's modulus must be positive (Pa)")
        if not -1 < finite(self.poisson_ratio, "Poisson ratio") < .5:
            raise ValueError("Poisson ratio must be strictly between -1 and 0.5")
        if self.density is not None and finite(self.density, "Density") <= 0:
            raise ValueError("Density must be positive (kg/m³)")

    @property
    def lame(self):
        e, n = self.young_modulus, self.poisson_ratio
        return e*n/((1+n)*(1-2*n)), e/(2*(1+n))


@dataclass(frozen=True)
class MeshSettings:
    target_size: float
    feature_angle: float = 40.

    def __post_init__(self):
        if finite(self.target_size, "Element size") <= 0:
            raise ValueError("Element size must be positive (m)")
        if not 1 <= finite(self.feature_angle, "Feature angle") <= 90:
            raise ValueError("Feature angle must be between 1 and 90 degrees")


@dataclass(frozen=True)
class SurfaceLoad:
    triangles: tuple[int, ...]
    kind: str = "force"
    value: tuple[float, ...] = (0., 0., 0.)
    identifier: str = field(default_factory=lambda: uuid4().hex)
    name: str = ""

    def __post_init__(self):
        if not isinstance(self.identifier, str) or not self.identifier or not isinstance(self.name, str):
            raise ValueError("Invalid load identity")
        object.__setattr__(self, "triangles", selection(self.triangles))
        if self.kind not in ("force", "pressure"):
            raise ValueError("Load must be a total force or inward-positive pressure")
        values = tuple(finite(x, "Load") for x in self.value)
        if len(values) != (3 if self.kind == "force" else 1):
            raise ValueError("Force needs XYZ values (N); pressure needs one value (Pa)")
        object.__setattr__(self, "value", values)


@dataclass(frozen=True)
class PointLoad:
    source_triangle: int
    barycentric: tuple[float, float, float]
    force: tuple[float, float, float]
    identifier: str = field(default_factory=lambda: uuid4().hex)
    name: str = "Point Force"

    def __post_init__(self):
        if type(self.source_triangle) is not int or self.source_triangle < 0:
            raise ValueError("Invalid source triangle for point load")
        bary = tuple(finite(v, "Point location") for v in self.barycentric)
        force = tuple(finite(v, "Point force") for v in self.force)
        if len(bary) != 3 or min(bary) < 0 or max(bary) > 1 or abs(sum(bary)-1) > 1e-10:
            raise ValueError("A point load must lie on a source triangle")
        if len(force) != 3:
            raise ValueError("Point force needs XYZ components (N)")
        if not isinstance(self.identifier, str) or not self.identifier or not isinstance(self.name, str):
            raise ValueError("Invalid point load identity")
        object.__setattr__(self, "barycentric", bary)
        object.__setattr__(self, "force", force)


def point_load_key(loads):
    return tuple(sorted((load.identifier, load.source_triangle, tuple(load.barycentric)) for load in loads))


@dataclass(frozen=True)
class SupportCondition:
    kind: str
    triangles: tuple[int, ...] = ()
    source_triangle: int | None = None
    barycentric: tuple[float, ...] = ()
    identifier: str = field(default_factory=lambda: uuid4().hex)
    name: str = ""

    def __post_init__(self):
        object.__setattr__(self, "triangles", tuple(self.triangles))
        object.__setattr__(self, "barycentric", tuple(self.barycentric))
        if self.kind not in ("fixed_face", "pinned_face", "fixed_point"):
            raise ValueError("Unknown support type")
        if not isinstance(self.identifier, str) or not self.identifier or not isinstance(self.name, str):
            raise ValueError("Invalid support identity")
        if self.kind == "fixed_point":
            anchor = PointLoad(self.source_triangle, self.barycentric, (0., 0., 0.))
            if self.triangles:
                raise ValueError("A fixed point cannot also select faces")
            object.__setattr__(self, "barycentric", anchor.barycentric)
        else:
            object.__setattr__(self, "triangles", selection(self.triangles))
            if self.source_triangle is not None or self.barycentric:
                raise ValueError("Face supports cannot also select a point")


def all_supports(setup):
    """Retain the Python API for legacy face-clamp tuples."""
    legacy = tuple(SupportCondition("fixed_face", triangles=triangles,
                    identifier=f"legacy-clamp-{i}",
                    name=setup.support_names[i] if setup.support_names else f"Fixed Face {i+1}")
                   for i, triangles in enumerate(setup.supports))
    return (*legacy, *setup.support_conditions)


def point_targets(setup):
    return (*setup.point_loads, *(s for s in all_supports(setup) if s.kind == "fixed_point"))


@dataclass(frozen=True)
class BeamConfiguration:
    clamp: tuple[int, ...]
    free_end: tuple[int, ...]

    def __post_init__(self):
        object.__setattr__(self, "clamp", selection(self.clamp))
        object.__setattr__(self, "free_end", selection(self.free_end))


@dataclass(frozen=True)
class AnalysisSetup:
    geometry_path: str
    geometry_fingerprint: str
    units: str
    material: Material
    mesh: MeshSettings
    supports: tuple[tuple[int, ...], ...] = ()
    loads: tuple[SurfaceLoad, ...] = ()
    gravity: tuple[float, float, float] = (0., 0., 0.)
    beam: BeamConfiguration | None = None
    point_loads: tuple[PointLoad, ...] = ()
    support_names: tuple[str, ...] = ()
    support_conditions: tuple[SupportCondition, ...] = ()

    def __post_init__(self):
        if not isinstance(self.geometry_path, str) or not self.geometry_path:
            raise ValueError("Choose a geometry file")
        if not isinstance(self.geometry_fingerprint, str) or len(self.geometry_fingerprint) != 64:
            raise ValueError("Invalid geometry fingerprint")
        if self.units not in ("m", "mm", "cm", "in"):
            raise ValueError("Unsupported import units")
        if not isinstance(self.material, Material) or not isinstance(self.mesh, MeshSettings):
            raise ValueError("Invalid material or mesh settings")
        object.__setattr__(self, "supports", tuple(selection(s) for s in self.supports))
        object.__setattr__(self, "loads", tuple(self.loads))
        if any(not isinstance(v, SurfaceLoad) for v in self.loads):
            raise ValueError("Invalid surface load")
        object.__setattr__(self, "point_loads", tuple(self.point_loads))
        object.__setattr__(self, "support_names", tuple(self.support_names))
        object.__setattr__(self, "support_conditions", tuple(self.support_conditions))
        if any(not isinstance(s, SupportCondition) for s in self.support_conditions):
            raise ValueError("Invalid support condition")
        if any(not isinstance(v, PointLoad) for v in self.point_loads):
            raise ValueError("Invalid point load")
        ids = [v.identifier for v in (*self.loads, *self.point_loads, *self.support_conditions)]
        if len(ids) != len(set(ids)):
            raise ValueError("Condition identifiers must be unique")
        if self.support_names and (len(self.support_names) != len(self.supports) or any(not isinstance(v, str) for v in self.support_names)):
            raise ValueError("Invalid support names")
        gravity = tuple(finite(x, "Gravity") for x in self.gravity)
        if len(gravity) != 3:
            raise ValueError("Gravity needs XYZ acceleration (m/s²)")
        object.__setattr__(self, "gravity", gravity)
        if any(gravity) and self.material.density is None:
            raise ValueError("Gravity requires a density")
        if self.beam is not None and not isinstance(self.beam, BeamConfiguration):
            raise ValueError("Invalid beam configuration")


@dataclass
class Geometry:
    points: np.ndarray
    triangles: np.ndarray
    shells: tuple[tuple[int, ...], ...]
    depths: tuple[int, ...]
    path: str
    fingerprint: str
    units: str
    density: float | None = None

    @property
    def dimensions(self):
        return np.ptp(self.points, axis=0)

    @property
    def volume(self):
        t = self.points[self.triangles] - self.points.mean(axis=0)
        return float(np.einsum("ij,ij->i", t[:, 0], np.cross(t[:, 1], t[:, 2])).sum()/6)


@dataclass(frozen=True)
class SurfacePatch:
    triangles: tuple[int, ...]
    label: str


@dataclass
class SolidMesh:
    points: np.ndarray
    tetrahedra: np.ndarray
    boundary_triangles: np.ndarray
    boundary_patch: np.ndarray
    patches: tuple[SurfacePatch, ...]
    geometry_fingerprint: str
    settings: MeshSettings
    point_anchors: tuple = ()
    point_nodes: dict[str, int] = field(default_factory=dict)
    source_points: np.ndarray | None = None
    source_triangles: np.ndarray | None = None

    def selected_boundary(self, triangles):
        chosen = set(triangles)
        members = set()
        indices = []
        for i, patch in enumerate(self.patches):
            source = set(patch.triangles)
            if source & chosen:
                if not source <= chosen:
                    raise ValueError("Surface patches changed; reassign boundary selections")
                members.update(source)
                indices.extend(np.flatnonzero(self.boundary_patch == i))
        if members != chosen or not indices:
            raise ValueError("Surface patches changed; reassign boundary selections")
        return np.asarray(indices, dtype=int)


@dataclass
class AnalysisResult:
    displacement: np.ndarray
    stress: np.ndarray  # (elements, quadrature points, 3, 3), unaveraged Pa
    von_mises: np.ndarray
    averaged_stress: np.ndarray  # continuous P1 projection at mesh vertices
    averaged_von_mises: np.ndarray
    reactions: np.ndarray  # (all displacement nodes, 3), N
    dof_points: np.ndarray
    solution: np.ndarray
    residual_error: float
    force_error: float
    moment_error: float
    applied_force: np.ndarray
    applied_moment: np.ndarray
    beam_stations: np.ndarray | None = None
    beam_moments: np.ndarray | None = None
    beam_message: str = ""
    root_reaction: np.ndarray = field(default_factory=lambda: np.zeros(6))
    support_reactions: dict = field(default_factory=dict)
