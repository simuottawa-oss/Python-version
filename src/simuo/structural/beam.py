"""Straight prismatic cantilever checks and FEM section-traction integration."""
import itertools
import numpy as np

from .postprocessing import constitutive
from .models import all_supports


def beam_frame(mesh, setup):
    beam = setup.beam
    root_ids = mesh.selected_boundary(beam.clamp)
    tip_ids = mesh.selected_boundary(beam.free_end)
    triangles = mesh.points[mesh.boundary_triangles]
    crosses = np.cross(triangles[:, 1]-triangles[:, 0], triangles[:, 2]-triangles[:, 0])
    areas = np.linalg.norm(crosses, axis=1)/2
    root = np.average(triangles[root_ids].mean(axis=1), axis=0, weights=areas[root_ids])
    tip = np.average(triangles[tip_ids].mean(axis=1), axis=0, weights=areas[tip_ids])
    axis = tip-root
    length = float(np.linalg.norm(axis))
    if length <= np.linalg.norm(np.ptp(mesh.points, axis=0))*1e-9:
        raise ValueError("Beam ends must be distinct parallel sections")
    axis /= length
    x = (triangles-root)@axis
    tolerance = length*1e-7
    if np.max(np.abs(x[root_ids])) > tolerance or np.max(np.abs(x[tip_ids]-length)) > tolerance:
        raise ValueError("Beam ends must be planar and parallel")
    all_root = set(np.flatnonzero(np.max(np.abs(x), axis=1) < tolerance))
    all_tip = set(np.flatnonzero(np.max(np.abs(x-length), axis=1) < tolerance))
    if set(root_ids) != all_root or set(tip_ids) != all_tip:
        raise ValueError("Select each complete beam end, including every end patch")
    conditions = all_supports(setup)
    if any(s.kind != "fixed_face" for s in conditions):
        raise ValueError("Beam diagrams require one complete fixed end; point/pinned supports retain solid stress analysis")
    fixed = set(int(i) for s in conditions for i in mesh.selected_boundary(s.triangles))
    if fixed != all_root:
        raise ValueError("Beam diagrams require exactly one complete end clamp and no other supports")
    sides = np.array(sorted(set(range(len(triangles)))-all_root-all_tip), dtype=int)
    normals = crosses/(2*areas[:, None])
    if (not len(sides) or np.max(np.abs(normals[sides]@axis)) > 1e-6 or
            x.min() < -tolerance or x.max() > length+tolerance or
            not np.isclose(areas[root_ids].sum(), areas[tip_ids].sum(), rtol=1e-6)):
        raise ValueError("Beam diagrams require a straight, constant cross-section solid")
    y = np.array([0., 1., 0.])
    y -= np.dot(y, axis)*axis
    if np.linalg.norm(y) < 1e-6:
        y = np.array([0., 0., 1.])
        y -= np.dot(y, axis)*axis
    y /= np.linalg.norm(y)
    return root, np.stack((axis, y, np.cross(axis, y))), length


def displacement_gradient(points, vertices, coefficients):
    """Evaluate P2 displacement gradients at arbitrary points inside one tetrahedron."""
    jacobian = (vertices[1:]-vertices[0]).T
    inverse = np.linalg.inv(jacobian)
    reference = (points-vertices[0])@inverse.T
    barycentric = np.column_stack((1-reference.sum(axis=1), reference))
    gradients = np.vstack((-inverse.sum(axis=0), inverse))
    shape = [(4*barycentric[:, i, None]-1)*gradients[i] for i in range(4)]
    for i, j in ((0, 1), (1, 2), (0, 2), (0, 3), (1, 3), (2, 3)):
        shape.append(4*(barycentric[:, i, None]*gradients[j]+barycentric[:, j, None]*gradients[i]))
    return np.einsum("ic,iqd->qcd", coefficients, np.asarray(shape))


def section_moments(mesh, result, material, root, axes, length):
    from .solver import make_basis
    basis = make_basis(mesh)
    vertices = mesh.points[mesh.tetrahedra]
    x = (vertices-root)@axes[0]
    stations = np.linspace(0., length, 101)[1:-1]
    moments = np.zeros((99, 2))
    quadrature = np.array([[2/3, 1/6, 1/6], [1/6, 2/3, 1/6], [1/6, 1/6, 2/3]])
    for station_index, station in enumerate(stations):
        origin = root+station*axes[0]
        candidates = np.flatnonzero((x.min(axis=1) < station) & (x.max(axis=1) >= station))
        total_area = 0.
        moment = np.zeros(3)
        for element in candidates:
            v = vertices[element]
            d = x[element]-station
            polygon = []
            for a, b in itertools.combinations(range(4), 2):
                if d[a] == 0:
                    polygon.append(v[a])
                if d[b] == 0:
                    polygon.append(v[b])
                if d[a]*d[b] < 0:
                    polygon.append(v[a]+d[a]/(d[a]-d[b])*(v[b]-v[a]))
            if len(polygon) < 3:
                continue
            polygon = np.unique(np.asarray(polygon), axis=0)
            if len(polygon) < 3:
                continue
            center = polygon.mean(axis=0)
            transverse = (polygon-center)@axes[1:].T
            polygon = polygon[np.argsort(np.arctan2(transverse[:, 1], transverse[:, 0]))]
            coefficients = result.solution[basis.element_dofs[:, element]].reshape(10, 3)
            for i in range(1, len(polygon)-1):
                triangle = polygon[[0, i, i+1]]
                area = np.linalg.norm(np.cross(triangle[1]-triangle[0], triangle[2]-triangle[0]))/2
                if area <= length*length*1e-20:
                    continue
                points = quadrature@triangle
                stress = constitutive(displacement_gradient(points, v, coefficients), material)
                traction = stress@axes[0]
                moment += area*np.cross(points-origin, traction).mean(axis=0)
                total_area += area
        if total_area <= 0 or not np.isfinite(moment).all():
            raise ValueError("A beam section could not be integrated")
        moments[station_index] = axes[1:]@moment
    return stations, moments
