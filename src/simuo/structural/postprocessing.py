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


def normalized_field(values):
    values = np.asarray(values, dtype=np.float64)
    if not np.isfinite(values).all() or np.any(values < 0):
        raise ValueError("Stress display needs finite nonnegative values")
    maximum = float(values.max()) if values.size else 0.
    return values/maximum if maximum > 0 else np.zeros_like(values), maximum


def gradient_texture(size=257):
    """Linear green → yellow → red lookup; includes the exact midpoint."""
    x = np.linspace(0, 1, size)
    return np.round(255*np.column_stack((np.minimum(2*x, 1), np.minimum(2*(1-x), 1), np.zeros(size)))).astype(np.uint8)
