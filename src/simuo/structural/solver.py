"""Quadratic vector displacement on linear tetrahedra, integrated SI loads."""
import warnings
import numpy as np
from scipy.sparse.linalg import MatrixRankWarning, splu
from skfem import Basis, FacetBasis, ElementTetP1, ElementTetP2, ElementVector, LinearForm, MeshTet, asm
from skfem.helpers import dot
from skfem.models.elasticity import linear_elasticity

from .meshing import validate_mesh
from .models import AnalysisResult, point_load_key
from .postprocessing import recover_stress


def make_basis(mesh):
    fem = MeshTet(mesh.points.T, mesh.tetrahedra.T, sort_t=False)
    return Basis(fem, ElementVector(ElementTetP2()), intorder=4)


def boundary_facets(basis, mesh, selection):
    lookup = {tuple(face): i for i, face in enumerate(np.sort(basis.mesh.facets.T, axis=1))}
    return np.asarray([lookup[tuple(face)] for face in np.sort(mesh.boundary_triangles[mesh.selected_boundary(selection)], axis=1)], dtype=int)


def solve_analysis(mesh, setup, progress=lambda text: None):
    from .geometry import fingerprint
    if fingerprint(setup.geometry_path, setup.units) != setup.geometry_fingerprint:
        raise ValueError("Geometry changed; import it again and reassign boundaries")
    if mesh.geometry_fingerprint != setup.geometry_fingerprint or mesh.settings != setup.mesh:
        raise ValueError("Mesh is out of date; generate it again")
    if mesh.point_anchors != point_load_key(setup.point_loads):
        raise ValueError("Point load locations changed; generate the mesh again")
    validate_mesh(mesh)
    progress("Assembling quadratic elasticity")
    basis = make_basis(mesh)
    lam, mu = setup.material.lame
    stiffness = asm(linear_elasticity(lam, mu), basis).tocsc()
    force = np.zeros(basis.N)
    for load in setup.loads:
        facets = boundary_facets(basis, mesh, load.triangles)
        fb = FacetBasis(basis.mesh, basis.elem, facets=facets, intorder=4)
        if load.kind == "force":
            area = fb.dx.sum()
            if not np.isfinite(area) or area <= 0:
                raise ValueError("Selected load area is empty")
            traction = np.asarray(load.value)/area
            @LinearForm
            def surface(v, w):
                return np.einsum("i,i...->...", traction, v)
        else:
            pressure = load.value[0]
            @LinearForm
            def surface(v, w):
                return -pressure*dot(w.n, v)
        force += asm(surface, fb)
    for load in setup.point_loads:
        node = mesh.point_nodes.get(load.identifier)
        if node is None or not 0 <= node < len(mesh.points):
            raise ValueError("Point load is missing its mesh node")
        force[basis.nodal_dofs[:, node]] += np.asarray(load.force)
    if any(setup.gravity):
        acceleration = setup.material.density*np.asarray(setup.gravity)
        @LinearForm
        def gravity(v, w):
            return np.einsum("i,i...->...", acceleration, v)
        force += asm(gravity, basis)
    if not setup.supports:
        raise ValueError("Select at least one fully clamped surface patch")
    fixed = np.unique(np.concatenate([basis.get_dofs(facets=boundary_facets(basis, mesh, s)).all() for s in setup.supports]))
    # Check the six rigid displacement modes at constrained components.
    positions = basis.doflocs.T
    center = mesh.points.mean(axis=0)
    length = np.linalg.norm(np.ptp(mesh.points, axis=0))
    rigid = np.empty((len(fixed), 6))
    for row, dof in enumerate(fixed):
        component = dof % 3
        rigid[row, :3] = np.eye(3)[component]
        rigid[row, 3:] = np.cross(np.eye(3), (positions[dof]-center)/length)[:, component]
    if np.linalg.matrix_rank(rigid, tol=1e-10) < 6:
        raise ValueError("Insufficient restraints: rigid-body motion remains")
    free = np.setdiff1d(np.arange(basis.N), fixed)
    solution = np.zeros(basis.N)
    progress("Solving sparse displacement system")
    try:
        with warnings.catch_warnings():
            warnings.simplefilter("error", MatrixRankWarning)
            if len(free) == 0:
                factor = None
            else:
                factor = splu(stiffness[free][:, free])
            if factor is not None:
                solution[free] = factor.solve(force[free])
            # Iterative refinement uses the original, uncondensed system.
            for _ in range(2 if factor is not None else 0):
                solution[free] += factor.solve((force-stiffness@solution)[free])
    except (RuntimeError, MatrixRankWarning) as error:
        raise ValueError("Singular stiffness system; check geometry and restraints") from error
    if not np.isfinite(solution).all():
        raise ValueError("Solver returned nonfinite displacements")
    residual = stiffness@solution-force
    reaction = np.zeros(basis.N)
    reaction[fixed] = residual[fixed]
    forces = force.reshape(-1, 3)
    reactions = reaction.reshape(-1, 3)
    dof_points = positions[::3]
    offsets = dof_points-center
    scale_force = max(float(np.linalg.norm(forces, axis=1).sum()), np.finfo(float).tiny)
    scale_moment = scale_force*length
    residual_error = float(np.linalg.norm(residual[free])/scale_force)
    force_error = float(np.linalg.norm((forces+reactions).sum(axis=0))/scale_force)
    moment_error = float(np.linalg.norm(np.cross(offsets, forces+reactions).sum(axis=0))/scale_moment)
    if max(residual_error, force_error, moment_error) > 1e-8 or not np.isfinite([residual_error, force_error, moment_error]).all():
        raise ValueError(f"Solution failed residual/equilibrium checks ({residual_error:.3g}, {force_error:.3g}, {moment_error:.3g})")
    progress("Recovering and projecting stress tensors")
    stress, vm, averaged, averaged_vm = recover_stress(basis, solution, setup.material)
    result = AnalysisResult(solution[basis.nodal_dofs].T, stress, vm, averaged, averaged_vm,
                            reactions, dof_points, solution, residual_error, force_error, moment_error,
                            forces.sum(axis=0), np.cross(offsets, forces).sum(axis=0))
    root = np.average(mesh.points, axis=0)
    if setup.beam:
        from .beam import beam_frame, section_moments
        try:
            root, axes, length = beam_frame(mesh, setup)
            progress("Integrating 99 interior beam sections")
            result.beam_stations, result.beam_moments = section_moments(mesh, result, setup.material, root, axes, length)
        except ValueError as error:
            result.beam_message = str(error)
    result.root_reaction = np.r_[reactions.sum(axis=0), np.cross(dof_points-root, reactions).sum(axis=0)]
    if fingerprint(setup.geometry_path, setup.units) != setup.geometry_fingerprint:
        raise ValueError("Geometry changed during solving; import it again")
    return result
