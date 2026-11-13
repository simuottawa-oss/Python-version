"""Indexed geometry import, shell topology, orientation and material connectivity."""
from pathlib import Path
import hashlib
import struct
import numpy as np

from .models import Geometry
from simuo.parts.part_assets import load_obj_geometry, box_vertices
from simuo.parts.part_format import load_part

SCALES = {"m": 1., "mm": .001, "cm": .01, "in": .0254}


def check_intersections(points, indices):
    """Reject triangle intersections except their shared topological edges/vertices."""
    from scipy.spatial import cKDTree
    triangles = points[indices]
    low, high = triangles.min(axis=1), triangles.max(axis=1)
    centers = (low+high)/2
    radii = np.linalg.norm(high-low, axis=1)/2
    tree = cKDTree(centers)
    tolerance = 1e-11

    def allowed(point, common):
        if not len(common):
            return False
        if len(common) == 1:
            return np.linalg.norm(point-common[0]) < tolerance
        edge = common[1]-common[0]
        u = np.dot(point-common[0], edge)/np.dot(edge, edge)
        return -tolerance <= u <= 1+tolerance and np.linalg.norm(point-common[0]-u*edge) < tolerance

    def in_triangle(point, t):
        a, b, c = t
        u, v, w = b-a, c-a, point-a
        uu, vv, uv = np.dot(u, u), np.dot(v, v), np.dot(u, v)
        determinant = uu*vv-uv*uv
        s = (vv*np.dot(w, u)-uv*np.dot(w, v))/determinant
        r = (uu*np.dot(w, v)-uv*np.dot(w, u))/determinant
        return s >= -tolerance and r >= -tolerance and s+r <= 1+tolerance

    for i, a in enumerate(triangles):
        candidates = np.asarray(tree.query_ball_point(centers[i], radii[i]+radii.max()+tolerance), dtype=int)
        candidates = candidates[(candidates > i) & np.all(high[candidates] >= low[i]-tolerance, axis=1) & np.all(low[candidates] <= high[i]+tolerance, axis=1)]
        for j in candidates:
            b = triangles[j]
            common = points[np.intersect1d(indices[i], indices[j])]
            na = np.cross(a[1]-a[0], a[2]-a[0]); na /= np.linalg.norm(na)
            nb = np.cross(b[1]-b[0], b[2]-b[0]); nb /= np.linalg.norm(nb)
            da, db = (b-a[0])@na, (a-b[0])@nb
            if np.all(da > tolerance) or np.all(da < -tolerance) or np.all(db > tolerance) or np.all(db < -tolerance):
                continue
            if np.max(np.abs(da)) <= tolerance and np.max(np.abs(db)) <= tolerance:
                # Coplanar triangles: test vertices and edge crossings in a stable 2D projection.
                axis = np.argmax(np.abs(na))
                aa, bb = np.delete(a, axis, axis=1), np.delete(b, axis, axis=1)
                for t, other in ((a, b), (b, a)):
                    for point in t:
                        if in_triangle(point, other) and not allowed(point, common):
                            raise ValueError("Self-intersecting or touching surface triangles")
                    if in_triangle(t.mean(axis=0), other):
                        raise ValueError("Overlapping coplanar triangles")
                for ia in range(3):
                    for ib in range(3):
                        u, v = aa[(ia+1)%3]-aa[ia], bb[(ib+1)%3]-bb[ib]
                        matrix = np.column_stack((u, -v))
                        if abs(np.linalg.det(matrix)) <= 1e-16:
                            continue
                        s, r = np.linalg.solve(matrix, bb[ib]-aa[ia])
                        if -tolerance <= s <= 1+tolerance and -tolerance <= r <= 1+tolerance:
                            point = a[ia]+s*(a[(ia+1)%3]-a[ia])
                            if not allowed(point, common):
                                raise ValueError("Intersecting coplanar triangles")
            else:
                for t, other, distances in ((a, b, db), (b, a, da)):
                    for k in range(3):
                        end = (k+1)%3
                        if abs(distances[k]) <= tolerance:
                            point = t[k]
                        elif distances[k]*distances[end] < 0:
                            point = t[k]+distances[k]/(distances[k]-distances[end])*(t[end]-t[k])
                        else:
                            continue
                        if in_triangle(point, other) and not allowed(point, common):
                            raise ValueError("Self-intersecting or touching surface triangles")


def fingerprint(path, units):
    return hashlib.sha256(Path(path).read_bytes() + b"\0" + units.encode("ascii")).hexdigest()


def read_stl(path):
    data = Path(path).read_bytes()
    # Binary STL can legally have an ASCII 'solid' header.
    if len(data) >= 84 and len(data) == 84 + 50*struct.unpack_from("<I", data, 80)[0]:
        count = struct.unpack_from("<I", data, 80)[0]
        records = np.frombuffer(data, dtype=np.dtype([("normal", "<f4", 3), ("vertices", "<f4", (3, 3)), ("attribute", "<u2")]), count=count, offset=84)
        return records["vertices"].astype(np.float64).reshape(-1, 3)
    try:
        tokens = data.decode("utf-8-sig").split()
        if not tokens or tokens[0].lower() != "solid":
            raise ValueError("Expected ASCII or binary STL")
        # Parse each facet strictly; names may occur after solid/endsolid.
        triangles = []
        i = 1
        while i < len(tokens) and tokens[i].lower() not in ("facet", "endsolid"):
            i += 1
        while i < len(tokens) and tokens[i].lower() == "facet":
            if tokens[i+1].lower() != "normal":
                raise ValueError("Missing STL facet normal")
            if not np.isfinite([float(x) for x in tokens[i+2:i+5]]).all():
                raise ValueError("Nonfinite STL normal")
            i += 5
            if [x.lower() for x in tokens[i:i+2]] != ["outer", "loop"]:
                raise ValueError("Missing STL outer loop")
            i += 2
            for _ in range(3):
                if tokens[i].lower() != "vertex":
                    raise ValueError("An STL facet needs three vertices")
                triangles.append([float(x) for x in tokens[i+1:i+4]])
                i += 4
            if [x.lower() for x in tokens[i:i+2]] != ["endloop", "endfacet"]:
                raise ValueError("Unterminated STL facet")
            i += 2
        if i >= len(tokens) or tokens[i].lower() != "endsolid" or not triangles:
            raise ValueError("Unterminated or empty STL")
        return np.asarray(triangles, dtype=np.float64)
    except (UnicodeError, IndexError, OverflowError) as error:
        raise ValueError("Malformed STL") from error


def inside(point, triangles):
    """Winding/solid-angle containment, independent of shell orientation."""
    a, b, c = np.moveaxis(triangles-point, 1, 0)
    la, lb, lc = (np.linalg.norm(x, axis=1) for x in (a, b, c))
    numerator = np.einsum("ij,ij->i", a, np.cross(b, c))
    denominator = la*lb*lc + np.einsum("ij,ij->i", a, b)*lc + np.einsum("ij,ij->i", b, c)*la + np.einsum("ij,ij->i", c, a)*lb
    return abs(np.arctan2(numerator, denominator).sum()) > np.pi


def validate_surface(points, triangles):
    points = np.asarray(points, dtype=np.float64)
    triangles = np.asarray(triangles, dtype=np.int64)
    if points.ndim != 2 or points.shape[1] != 3 or triangles.ndim != 2 or triangles.shape[1] != 3 or not len(triangles):
        raise ValueError("Expected a nonempty indexed triangle surface")
    if not np.isfinite(points).all() or np.any(triangles < 0) or np.any(triangles >= len(points)):
        raise ValueError("Invalid surface coordinates or indices")
    # Weld exact duplicates only; never close gaps or replace geometry by a hull.
    points, inverse = np.unique(points[triangles].reshape(-1, 3), axis=0, return_inverse=True)
    triangles = inverse.reshape(-1, 3)
    scale = float(np.linalg.norm(np.ptp(points, axis=0)))
    if not scale > 0 or not np.isfinite(scale):
        raise ValueError("Degenerate geometry")
    p = (points-points.mean(axis=0))/scale
    tri = p[triangles]
    if np.any(np.linalg.norm(np.cross(tri[:, 1]-tri[:, 0], tri[:, 2]-tri[:, 0]), axis=1) <= 1e-14):
        raise ValueError("Degenerate surface triangle")
    if len(np.unique(np.sort(triangles, axis=1), axis=0)) != len(triangles):
        raise ValueError("Duplicate surface triangle")
    edges = {}
    for i, t in enumerate(triangles):
        for a, b in zip(t, np.roll(t, -1)):
            edges.setdefault(tuple(sorted((a, b))), []).append((i, 1 if a < b else -1))
    if any(len(v) != 2 for v in edges.values()):
        raise ValueError("Surface must be closed and manifold: every edge needs two triangles")
    neighbors = [[] for _ in triangles]
    for (a, da), (b, db) in edges.values():
        neighbors[a].append((b, -da*db))
        neighbors[b].append((a, -da*db))
    signs = np.zeros(len(triangles), dtype=int)
    shells = []
    for first in range(len(triangles)):
        if signs[first]:
            continue
        signs[first] = 1
        queue, shell = [first], []
        while queue:
            item = queue.pop()
            shell.append(item)
            for other, relation in neighbors[item]:
                expected = signs[item]*relation
                if signs[other] and signs[other] != expected:
                    raise ValueError("Surface is not orientable")
                if not signs[other]:
                    signs[other] = expected
                    queue.append(other)
        shells.append(tuple(sorted(shell)))
    triangles[signs < 0] = triangles[signs < 0][:, [0, 2, 1]]
    check_intersections(p, triangles)
    depths = []
    for shell in shells:
        t = p[triangles[list(shell)]]
        volume = np.einsum("ij,ij->i", t[:, 0], np.cross(t[:, 1], t[:, 2])).sum()/6
        if abs(volume) < 1e-14:
            raise ValueError("Surface encloses no measurable volume")
        if volume < 0:
            triangles[list(shell)] = triangles[list(shell)][:, [0, 2, 1]]
        point = p[triangles[shell[0], 0]]
        depths.append(sum(inside(point, p[triangles[list(other)]]) for other in shells if other is not shell))
    if depths.count(0) != 1 or any(d > 1 for d in depths):
        raise ValueError("Analyze one connected material body at a time")
    for shell, depth in zip(shells, depths):
        if depth % 2:
            triangles[list(shell)] = triangles[list(shell)][:, [0, 2, 1]]
    # The kernel checks manifold vertex links. It does not repair invalid input.
    import manifold3d as m
    solid = m.Manifold(m.Mesh64(p, triangles.astype(np.uint64)))
    if solid.status() != m.Error.NoError or solid.is_empty():
        raise ValueError("Invalid manifold solid")
    # Reject intersecting shells and self-intersections using the kernel's
    # explicit geometric validation, when available in the pinned backend.
    if hasattr(solid, "is_valid") and not solid.is_valid():
        raise ValueError("Invalid or self-intersecting surface")
    return points, triangles, tuple(shells), tuple(depths)


def load_geometry(path, units="m"):
    path = Path(path).resolve()
    if units not in SCALES:
        raise ValueError("Choose metres, millimetres, centimetres or inches")
    density = None
    if path.suffix.lower() == ".stl":
        points = read_stl(path)
        indices = np.arange(len(points)).reshape(-1, 3)
    elif path.suffix.lower() in (".obj", ".simuopart"):
        native = path.suffix.lower() == ".simuopart" and path.read_text(encoding="utf-8-sig").lstrip().startswith(("{", "["))
        if native:
            if units != "m":
                raise ValueError("Native parts use metres")
            part = load_part(path)
            density = part.density
            if part.features is not None:
                points, indices = part.features.analysis_points, part.features.analysis_triangles
            else:
                if part.sketch is not None:
                    from simuo.parts.sketch_geometry import prism_vertices
                    flat = prism_vertices(part.sketch, dtype=np.float64)
                else:
                    flat = box_vertices(part, dtype=np.float64)
                points = flat.reshape(-1, 6)[:, :3]
                indices = np.arange(len(points)).reshape(-1, 3)
        else:
            points, indices = load_obj_geometry(path)
    else:
        raise ValueError("Import a .simuOPart, OBJ or STL solid")
    points, indices, shells, depths = validate_surface(points*SCALES[units], indices)
    return Geometry(points, indices, shells, depths, str(path), fingerprint(path, units), units, density)
