"""Sparse displacement reduction for fixed points, clamps and spherical face pins."""
from dataclasses import dataclass
import numpy as np
from scipy.linalg import null_space
from scipy.sparse import coo_matrix, vstack
from scipy.sparse.linalg import lsmr

from .models import all_supports, point_targets
from .meshing import bind_point_targets


def facet_indices(basis, mesh, selection):
    lookup = {tuple(face): i for i, face in enumerate(np.sort(basis.mesh.facets.T, axis=1))}
    return np.asarray([lookup[tuple(face)] for face in np.sort(mesh.boundary_triangles[mesh.selected_boundary(selection)], axis=1)], dtype=int)


def cross_matrix(r):
    """Matrix multiplying theta to give theta × r."""
    x, y, z = r
    return np.array([[0., z, -y], [-z, 0., x], [y, -x, 0.]])


@dataclass
class ConstraintSystem:
    transform: object
    remaining_modes: int
    support_nodes: dict
    pin_centers: dict
    supports: tuple
    fixed: np.ndarray
    reaction_matrix: object
    reaction_rows: tuple

    @property
    def reason(self):
        if not self.supports:
            return "Select at least one support: clamped faces, fixed points or pinned faces"
        if self.remaining_modes:
            return f"Insufficient restraints: {self.remaining_modes} rigid-body motions remain. Add another support."
        return ""


def build_constraints(basis, mesh, setup):
    supports = tuple(all_supports(setup))
    bindings = bind_point_targets(mesh, point_targets(setup))
    length = float(np.linalg.norm(np.ptp(mesh.points, axis=0)))
    origin = mesh.points.mean(axis=0)
    nodes, centers, fixed, pins = {}, {}, set(), []
    mode_rows = []
    positions = basis.doflocs.T

    def rigid_at(point):
        return np.column_stack((np.eye(3), cross_matrix((point-origin)/length)))

    for support in supports:
        if support.kind == "fixed_point":
            vertex = bindings[support.identifier]
            dofs = basis.nodal_dofs[:, vertex]
        else:
            facets = facet_indices(basis, mesh, support.triangles)
            dofs = basis.get_dofs(facets=facets).all()
        indices = np.unique(dofs//3)
        nodes[support.identifier] = indices
        if support.kind == "pinned_face":
            triangles = mesh.points[mesh.boundary_triangles[mesh.selected_boundary(support.triangles)]]
            areas = np.linalg.norm(np.cross(triangles[:, 1]-triangles[:, 0], triangles[:, 2]-triangles[:, 0]), axis=1)/2
            center = np.average(triangles.mean(axis=1), axis=0, weights=areas)
            centers[support.identifier] = center
            pins.append((support, dofs, center))
            mode_rows.extend(rigid_at(center))
        else:
            fixed.update(int(d) for d in dofs)
            for dof in dofs:
                mode_rows.append(rigid_at(positions[dof])[int(dof)%3])
    rank = np.linalg.matrix_rank(np.asarray(mode_rows).reshape(-1, 6), tol=1e-10) if mode_rows else 0
    # Pin boundary displacements are theta × (x-c). Handle shared nodes/fixed
    # nodes by reducing only the small set of pin rotation variables.
    rotation_count = 3*len(pins)
    reaction_rows, cr, cc, cv, rr, rc, rv = [], [], [], [], [], [], []
    for support in supports:
        if support.kind == "fixed_point":
            dofs = basis.nodal_dofs[:, bindings[support.identifier]]
        else:
            dofs = basis.get_dofs(facets=facet_indices(basis, mesh, support.triangles)).all()
        pin_index = next((i for i, (value, _, _) in enumerate(pins) if value.identifier == support.identifier), None)
        for dof in dofs:
            row = len(reaction_rows)
            reaction_rows.append((support.identifier, int(dof)))
            cr.append(row); cc.append(int(dof)); cv.append(1.)
            if pin_index is not None:
                expression = -cross_matrix((positions[dof]-centers[support.identifier])/length)[int(dof)%3]
                for axis in range(3):
                    rr.append(row); rc.append(3*pin_index+axis); rv.append(expression[axis])
    cu = coo_matrix((cv, (cr, cc)), shape=(len(reaction_rows), basis.N)).tocsr()
    ct = coo_matrix((rv, (rr, rc)), shape=(len(reaction_rows), rotation_count)).tocsr()
    reaction_matrix = vstack((cu.T, ct.T), format="csr")
    owners, compatibility = {}, []
    for pin, (support, dofs, center) in enumerate(pins):
        for dof in dofs:
            row = np.zeros(rotation_count)
            row[3*pin:3*pin+3] = cross_matrix((positions[dof]-center)/length)[int(dof)%3]
            if int(dof) in fixed:
                compatibility.append(row)
            elif int(dof) in owners:
                compatibility.append(row-owners[int(dof)])
            else:
                owners[int(dof)] = row
    free = np.array([d for d in range(basis.N) if d not in fixed and d not in owners], dtype=int)
    rotations = (null_space(np.asarray(compatibility), rcond=1e-10) if compatibility
                 else np.eye(rotation_count))
    rows = list(free)
    cols = list(range(len(free)))
    values = [1.]*len(free)
    for dof, expression in owners.items():
        expression = expression@rotations
        nonzero = np.flatnonzero(np.abs(expression) > 1e-14)
        rows.extend([dof]*len(nonzero))
        cols.extend(len(free)+nonzero)
        values.extend(expression[nonzero])
    transform = coo_matrix((values, (rows, cols)), shape=(basis.N, len(free)+rotations.shape[1])).tocsc()
    return ConstraintSystem(transform, 6-rank, nodes, centers, supports, np.asarray(sorted(fixed), dtype=int), reaction_matrix, tuple(reaction_rows))


def recover_support_reactions(constraints, basis, residual):
    # Least-norm constraint forces give consistent accounting at shared support
    # nodes, while the free pin rotation equations enforce zero joint moment.
    rhs = np.r_[residual, np.zeros(constraints.reaction_matrix.shape[0]-basis.N)]
    multipliers = lsmr(constraints.reaction_matrix, rhs, atol=1e-13, btol=1e-13, maxiter=5000)[0]
    result = {}
    dof_points = basis.doflocs.T[::3]
    for support in constraints.supports:
        indices = constraints.support_nodes[support.identifier]
        center = constraints.pin_centers.get(support.identifier, dof_points[indices].mean(axis=0))
        result[support.identifier] = {"force": np.zeros(3), "moment": np.zeros(3), "origin": center}
    for multiplier, (identifier, dof) in zip(multipliers, constraints.reaction_rows):
        force = np.zeros(3)
        force[dof%3] = multiplier
        value = result[identifier]
        value["force"] += force
        value["moment"] += np.cross(dof_points[dof//3]-value["origin"], force)
    return result


def restraint_reason(geometry, setup):
    """Cheap six-mode readiness check using source geometry, before any solve."""
    supports = all_supports(setup)
    if not supports:
        return "Select at least one support: clamped faces, fixed points or pinned faces"
    length = np.linalg.norm(geometry.dimensions)
    origin = geometry.points.mean(axis=0)
    rows = []
    for support in supports:
        if support.kind == "fixed_point":
            from .meshing import point_position
            positions = [point_position(geometry, support)]
        else:
            triangles = geometry.points[geometry.triangles[list(support.triangles)]]
            if support.kind == "pinned_face":
                areas = np.linalg.norm(np.cross(triangles[:, 1]-triangles[:, 0], triangles[:, 2]-triangles[:, 0]), axis=1)/2
                positions = [np.average(triangles.mean(axis=1), axis=0, weights=areas)]
            else:
                positions = triangles.reshape(-1, 3)
        for position in positions:
            rows.extend(np.column_stack((np.eye(3), cross_matrix((position-origin)/length))))
    modes = 6-np.linalg.matrix_rank(np.asarray(rows), tol=1e-10)
    return f"Insufficient restraints: {modes} rigid-body motions remain. Add another support." if modes else ""
