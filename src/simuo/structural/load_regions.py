"""Planar circular load footprints shared by the UI and consistent P2 assembly.

Circles are deterministic inscribed 256-gons. Clipping is performed in a
radius-scaled local plane, independently of the volume mesh resolution.
"""
from dataclasses import dataclass
import numpy as np


@dataclass
class LoadRegion:
    triangles: np.ndarray
    area: float
    centroid: np.ndarray
    center: np.ndarray
    normal: np.ndarray


def surface_region(points, triangles, selection):
    selected = np.asarray(selection, dtype=int)
    if not len(selected) or selected.min() < 0 or selected.max() >= len(triangles):
        raise ValueError("Selected load face changed; reassign the load")
    vertices = points[triangles[selected]]
    crosses = np.cross(vertices[:, 1]-vertices[:, 0], vertices[:, 2]-vertices[:, 0])
    areas = np.linalg.norm(crosses, axis=1)/2
    area = float(areas.sum())
    if not np.isfinite(area) or area <= 0:
        raise ValueError("Selected load area is empty")
    centroid = np.average(vertices.mean(axis=1), weights=areas, axis=0)
    normal = crosses.sum(axis=0)/(2*area)
    return LoadRegion(vertices, area, centroid, centroid, normal)


def area_frame(points, triangles, load):
    region = surface_region(points, triangles, load.triangles)
    if load.source_triangle not in load.triangles:
        raise ValueError("Area center must belong to its selected face")
    anchor = points[triangles[load.source_triangle]]
    center = np.asarray(load.barycentric)@anchor
    normal = np.cross(anchor[1]-anchor[0], anchor[2]-anchor[0])
    normal /= np.linalg.norm(normal)
    tolerance = np.linalg.norm(np.ptp(points, axis=0))*1e-8
    if np.max(np.abs((region.triangles-center)@normal)) > tolerance:
        raise ValueError("Area requires a planar face; use Face mode for curved surfaces")
    edges = np.roll(anchor, -1, axis=0)-anchor
    x = edges[np.argmax(np.linalg.norm(edges, axis=1))]
    x = x/np.linalg.norm(x)
    axes = np.stack((x, np.cross(normal, x)))
    return center, axes, normal


def _clip_triangle(triangle):
    """Intersect a radius-one regular polygon with one local-plane triangle."""
    if np.any(triangle.min(axis=0) > 1.) or np.any(triangle.max(axis=0) < -1.):
        return np.empty((0, 2))
    # Every triangle vertex in the polygon's incircle implies full coverage.
    if np.max(np.linalg.norm(triangle, axis=1)) <= np.cos(np.pi/256):
        return triangle
    angles = np.arange(256)*(2*np.pi/256)
    polygon = np.column_stack((np.cos(angles), np.sin(angles)))
    orientation = np.linalg.det(np.stack((triangle[1]-triangle[0], triangle[2]-triangle[0])))
    if abs(orientation) < 1e-25:
        return np.empty((0, 2))
    if orientation < 0:
        triangle = triangle[::-1]
    for start, end in zip(triangle, np.roll(triangle, -1, axis=0)):
        if len(polygon) < 3:
            return np.empty((0, 2))
        edge = end-start
        distances = edge[0]*(polygon[:, 1]-start[1])-edge[1]*(polygon[:, 0]-start[0])
        following = np.roll(polygon, -1, axis=0)
        next_distances = np.roll(distances, -1)
        inside = distances >= 0
        crossing = inside != np.roll(inside, -1)
        # Keep the vertex and then its outgoing intersection, in cyclic order.
        candidates = np.empty((2*len(polygon), 2))
        candidates[::2] = polygon
        denominator = distances-next_distances
        fractions = np.divide(distances, denominator, out=np.zeros_like(distances), where=crossing)
        candidates[1::2] = polygon+fractions[:, None]*(following-polygon)
        polygon = candidates[np.column_stack((inside, crossing)).ravel()]
    return polygon


def clipped_triangles(vertices, center, axes, radius):
    """Yield (input triangle index, physical clipped subtriangle)."""
    local = (vertices-center)@axes.T/radius
    for index, triangle in enumerate(local):
        polygon = _clip_triangle(triangle)
        if len(polygon) < 3:
            continue
        physical = center+radius*(polygon@axes)
        for i in range(1, len(physical)-1):
            child = physical[[0, i, i+1]]
            if np.linalg.norm(np.cross(child[1]-child[0], child[2]-child[0])) > radius*radius*1e-20:
                yield index, child


def area_region(points, triangles, load):
    center, axes, normal = area_frame(points, triangles, load)
    vertices = points[triangles[list(load.triangles)]]
    clipped = np.asarray([child for _, child in clipped_triangles(vertices, center, axes, load.radius)])
    if not len(clipped):
        raise ValueError("Area footprint is empty; choose a center on the face and a positive radius")
    areas = np.linalg.norm(np.cross(clipped[:, 1]-clipped[:, 0], clipped[:, 2]-clipped[:, 0]), axis=1)/2
    area = float(areas.sum())
    if not np.isfinite(area) or area <= 0:
        raise ValueError("Area footprint is empty")
    return LoadRegion(clipped, area, np.average(clipped.mean(axis=1), weights=areas, axis=0), center, normal)


def assemble_area_force(basis, mesh, load):
    """Integrate constant traction against the six P2 shapes on each clipped facet."""
    center, axes, normal = area_frame(mesh.source_points, mesh.source_triangles, load)
    selected = mesh.selected_boundary(load.triangles)
    faces = mesh.boundary_triangles[selected]
    vertices = mesh.points[faces]
    pieces = list(clipped_triangles(vertices, center, axes, load.radius))
    if not pieces:
        raise ValueError("Area footprint has no mesh boundary coverage")
    areas = np.asarray([np.linalg.norm(np.cross(t[1]-t[0], t[2]-t[0]))/2 for _, t in pieces])
    area = float(areas.sum())
    reference = area_region(mesh.source_points, mesh.source_triangles, load)
    if not np.isclose(area, reference.area, rtol=1e-8, atol=0):
        raise ValueError("Mesh does not cover the Area footprint; regenerate it")
    traction = np.asarray(load.value)/area if load.kind == "force" else -load.value[0]*normal
    edge_lookup = {tuple(edge): i for i, edge in enumerate(np.sort(basis.mesh.edges.T, axis=1))}
    force = np.zeros(basis.N)
    quadrature = np.array([[2/3, 1/6, 1/6], [1/6, 2/3, 1/6], [1/6, 1/6, 2/3]])
    for (index, child), weight in zip(pieces, areas):
        triangle = vertices[index]
        coordinates = quadrature@child
        uv = np.linalg.lstsq((triangle[1:]-triangle[0]).T, (coordinates-triangle[0]).T, rcond=None)[0].T
        bary = np.column_stack((1-uv.sum(axis=1), uv))
        shapes = np.column_stack((bary*(2*bary-1), *(4*bary[:, a]*bary[:, b] for a, b in ((0, 1), (1, 2), (0, 2)))))
        integrals = weight*shapes.mean(axis=0)
        face = faces[index]
        edges = [edge_lookup[tuple(sorted((int(face[a]), int(face[b]))))] for a, b in ((0, 1), (1, 2), (0, 2))]
        dofs = np.column_stack((basis.nodal_dofs[:, face], basis.edge_dofs[:, edges]))
        for axis in range(3):
            np.add.at(force, dofs[axis], integrals*traction[axis])
    return force
