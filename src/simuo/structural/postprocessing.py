"""Tensor stress recovery and a continuous projection for averaged display."""
import numpy as np
from scipy.sparse.linalg import splu
from skfem import Basis, ElementTetP1, LinearForm, asm
from skfem.models.poisson import mass


def von_mises(stress):
    s = np.asarray(stress)
    deviator = s - np.trace(s, axis1=-2, axis2=-1)[..., None, None]*np.eye(3)/3
    return np.sqrt(np.maximum(0., 1.5*np.einsum("...ij,...ij->...", deviator, deviator)))


def constitutive(gradient, material):
    strain = (gradient + gradient.swapaxes(-2, -1))/2
    lam, mu = material.lame
    return 2*mu*strain + lam*np.trace(strain, axis1=-2, axis2=-1)[..., None, None]*np.eye(3)


def recover_stress(basis, solution, material):
    gradient = basis.interpolate(solution).grad.transpose(2, 3, 0, 1)
    stress = constitutive(gradient, material)
    scalar = Basis(basis.mesh, ElementTetP1(), quadrature=basis.quadrature)
    factor = splu(asm(mass, scalar).tocsc())
    averaged = np.zeros((scalar.N, 3, 3))
    @LinearForm
    def project(v, w):
        return w.tensor*v
    for i in range(3):
        for j in range(i, 3):
            averaged[:, i, j] = factor.solve(asm(project, scalar, tensor=stress[:, :, i, j]))
            averaged[:, j, i] = averaged[:, i, j]
    vm, display = von_mises(stress), von_mises(averaged)
    if not all(np.isfinite(a).all() for a in (stress, vm, averaged, display)):
        raise ValueError("Nonfinite recovered stress")
    return stress, vm, averaged, display


def normalized_field(values, maximum=None):
    values = np.asarray(values, dtype=np.float64)
    if not np.isfinite(values).all() or np.any(values < 0):
        raise ValueError("Stress display needs finite nonnegative values")
    if maximum is None:
        maximum = float(values.max()) if values.size else 0.
    elif isinstance(maximum, bool) or not np.isfinite(maximum) or maximum <= 0:
        raise ValueError("Stress maximum must be finite and positive")
    return np.clip(values/maximum, 0, 1) if maximum > 0 else np.zeros_like(values), maximum


STRESS_COLORS = ((0., (0., 0., 1.)), (1/3, (0., 1., 0.)),
                 (2/3, (1., 1., 0.)), (1., (1., 0., 0.)))


def stress_scale(values, mode="yield", material=None, custom_maximum=None):
    """Resolve the actual maximum and its visible meaning, including fallbacks."""
    if mode in ("yield", "uts"):
        attribute, name = (("yield_strength", "Material yield") if mode == "yield" else
                           ("ultimate_tensile_strength", "Material UTS (reference)"))
        maximum = getattr(material, attribute, None)
        if maximum is not None:
            return float(maximum), name
        return normalized_field(values)[1], f"Automatic range — {name.lower()} not supplied"
    if mode == "custom":
        return normalized_field(values, custom_maximum)[1], "Custom maximum"
    if mode == "auto":
        return normalized_field(values)[1], "Automatic range"
    raise ValueError("Unknown stress scale")


def gradient_texture(size=257):
    """Shared blue → green → yellow → red lookup."""
    x = np.linspace(0, 1, size)
    positions, colors = zip(*STRESS_COLORS)
    return np.round(255*np.column_stack([np.interp(x, positions, channel) for channel in np.asarray(colors).T])).astype(np.uint8)


def deformed_points(points, displacement, mode="auto", custom_scale=1.):
    """Return display-only coordinates, magnification and actual peak displacement."""
    points = np.asarray(points, dtype=np.float64)
    displacement = np.asarray(displacement, dtype=np.float64)
    if (points.ndim != 2 or points.shape[1] != 3 or displacement.shape != points.shape or
            not np.isfinite(points).all() or not np.isfinite(displacement).all()):
        raise ValueError("Deformation preview needs matching finite XYZ positions and displacements")
    peak = float(np.hypot.reduce(displacement, axis=1).max()) if len(points) else 0.
    if mode == "auto":
        diagonal = float(np.hypot.reduce(np.ptp(points, axis=0))) if len(points) else 0.
        scale = max(1., .1*diagonal/peak) if peak > 0 else 1.
    elif mode == "true":
        scale = 1.
    elif mode == "custom":
        if isinstance(custom_scale, bool) or not np.isfinite(custom_scale) or custom_scale <= 0:
            raise ValueError("Deformation magnification must be finite and positive")
        scale = float(custom_scale)
    else:
        raise ValueError("Unknown deformation magnification mode")
    with np.errstate(over="ignore", invalid="ignore"):
        displayed = points+scale*displacement
    if not np.isfinite(scale) or not np.isfinite(displayed).all():
        raise ValueError("Deformation magnification is too large to display")
    return displayed, scale, peak
