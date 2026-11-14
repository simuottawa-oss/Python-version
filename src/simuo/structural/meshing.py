"""Gmsh discrete surfaces (tutorial t13), including nested cavity loops."""
from contextlib import contextmanager
import math
import numpy as np

from .geometry import fingerprint
from .models import MeshSettings, SolidMesh, SurfacePatch, point_load_key


@contextmanager
def gmsh_model():
    import gmsh
    if gmsh.isInitialized():
        raise RuntimeError("Gmsh must run in an isolated worker")
    gmsh.initialize([], readConfigFiles=False, run=False)
    try:
        gmsh.option.setNumber("General.Terminal", 0)
        gmsh.option.setNumber("General.NumThreads", 1)
        gmsh.model.add("structural")
        yield gmsh
    finally:
        gmsh.finalize()


def _classify(gmsh, geometry, angle, force_parametrizable, create=True):
    gmsh.model.addDiscreteEntity(2, 1)
    gmsh.model.mesh.addNodes(2, 1, np.arange(1, len(geometry.points)+1), geometry.points.ravel())
    gmsh.model.mesh.addElementsByType(1, 2, np.arange(1, len(geometry.triangles)+1), (geometry.triangles+1).ravel())
    gmsh.model.mesh.classifySurfaces(angle, True, force_parametrizable, math.pi)
    groups = []
    for _, tag in gmsh.model.getEntities(2):
        types, elements, _ = gmsh.model.mesh.getElements(2, tag)
        members = tuple(sorted(int(i)-1 for kind, ids in zip(types, elements) if kind == 2 for i in ids))
        if not members:
            raise ValueError("Gmsh produced an empty patch")
        groups.append((members, tag))
    groups.sort()
    covered = [i for members, _ in groups for i in members]
    if sorted(covered) != list(range(len(geometry.triangles))):
        raise ValueError("Gmsh classification did not preserve source triangle membership")
    if create:
        gmsh.model.mesh.createGeometry()
    return groups


def discrete_geometry(gmsh, geometry, settings):
    # Classify user-facing patches at the feature angle, but preserve the
    # imported piecewise-planar surface in the meshing geometry. Parametrizing
    # an entire faceted cylinder as one surface otherwise changes its volume.
    logical = _classify(gmsh, geometry, math.radians(settings.feature_angle), False, create=False)
    patches = tuple(SurfacePatch(members, f"Patch {i+1}") for i, (members, _) in enumerate(logical))
    owner = {source: i for i, patch in enumerate(patches) for source in patch.triangles}
    gmsh.clear()
    gmsh.model.add("structural-facets")
    try:
        surfaces = _classify(gmsh, geometry, min(math.radians(settings.feature_angle), 1e-5), False)
    except Exception:
        gmsh.clear()
        gmsh.model.add("structural-parametrized")
        surfaces = _classify(gmsh, geometry, min(math.radians(settings.feature_angle), 1e-5), True)
    groups = []
    for members, tag in surfaces:
        owners = {owner[source] for source in members}
        if len(owners) != 1:
            raise ValueError("Incompatible reconstruction of surface patches")
        groups.append((members, tag, owners.pop()))
    return groups, patches


def classify_patches(geometry, settings):
    with gmsh_model() as gmsh:
        _, patches = discrete_geometry(gmsh, geometry, settings)
        return patches


def point_position(geometry, load):
    if load.source_triangle >= len(geometry.triangles):
        raise ValueError("Point target source triangle changed; reassign the point")
    return np.asarray(load.barycentric) @ geometry.points[geometry.triangles[load.source_triangle]]


def bind_point_targets(mesh, targets, geometry=None):
    """Bind current identities to existing boundary vertices, without remeshing."""
    from scipy.spatial import cKDTree
    targets = tuple(targets)
    if not targets:
        return {}
    source_points = geometry.points if geometry is not None else mesh.source_points
    source_triangles = geometry.triangles if geometry is not None else mesh.source_triangles
    if source_points is None or source_triangles is None:
        raise ValueError("Mesh lacks point-anchor geometry; generate it again")
    boundary = np.unique(mesh.boundary_triangles)
    tree = cKDTree(mesh.points[boundary])
    tolerance = float(np.linalg.norm(np.ptp(source_points, axis=0)))*1e-10
    mapping = {}
    for target in targets:
        if target.source_triangle >= len(source_triangles):
            raise ValueError("Point source triangle changed; reassign the point")
        position = np.asarray(target.barycentric)@source_points[source_triangles[target.source_triangle]]
        distance, nearest = tree.query(position)
        if distance > tolerance:
            raise ValueError("Point locations changed; mesh update required")
        mapping[target.identifier] = int(boundary[nearest])
    return mapping


def insert_point_nodes(mesh, geometry, loads):
    """Conforming subdivision of boundary face/edge stars; keep exact SI anchors."""
    mesh.source_points = geometry.points
    mesh.source_triangles = geometry.triangles
    mesh.point_anchors = point_load_key(loads)
    mesh.point_nodes = {}
    tolerance = float(np.linalg.norm(geometry.dimensions))*1e-10
    for load in sorted(loads, key=lambda item: item.identifier):
        point = point_position(geometry, load)
        distances = np.linalg.norm(mesh.points-point, axis=1)
        nearest = int(np.argmin(distances))
        if distances[nearest] <= tolerance:
            boundary_nodes = np.unique(mesh.boundary_triangles)
            if nearest not in boundary_nodes:
                raise ValueError("Point load does not lie on the mesh boundary")
            mesh.point_nodes[load.identifier] = nearest
            continue
        feature = None
        for face in mesh.boundary_triangles:
            triangle = mesh.points[face]
            edges = (triangle[1:]-triangle[0]).T
            uv = np.linalg.lstsq(edges, point-triangle[0], rcond=None)[0]
            bary = np.r_[1-uv.sum(), uv]
            if np.linalg.norm(edges@uv+triangle[0]-point) <= tolerance and bary.min() >= -1e-10:
                feature = face[bary > 1e-10]
                break
        if feature is None or len(feature) not in (2, 3):
            raise ValueError("Could not retain the point on this mesh; adjust the element size")
        node = len(mesh.points)
        mesh.points = np.vstack((mesh.points, point))
        tetrahedra = []
        for tetrahedron in mesh.tetrahedra:
            if set(feature) <= set(tetrahedron):
                for vertex in feature:
                    child = tetrahedron.copy()
                    child[np.flatnonzero(child == vertex)[0]] = node
                    tetrahedra.append(child)
            else:
                tetrahedra.append(tetrahedron)
        boundary, patches = [], []
        for face, patch in zip(mesh.boundary_triangles, mesh.boundary_patch):
            if set(feature) <= set(face):
                for vertex in feature:
                    child = face.copy()
                    child[np.flatnonzero(child == vertex)[0]] = node
                    boundary.append(child)
                    patches.append(patch)
            else:
                boundary.append(face)
                patches.append(patch)
        mesh.tetrahedra = np.asarray(tetrahedra, dtype=np.int64)
        mesh.boundary_triangles = np.asarray(boundary, dtype=np.int64)
        mesh.boundary_patch = np.asarray(patches, dtype=np.int64)
        mesh.point_nodes[load.identifier] = node


def validate_mesh(mesh, geometry=None):
    p, t = mesh.points, mesh.tetrahedra
    if p.ndim != 2 or p.shape[1] != 3 or t.ndim != 2 or t.shape[1] != 4 or not len(t):
        raise ValueError("Gmsh did not produce linear tetrahedra")
    if not np.isfinite(p).all() or np.any(t < 0) or np.any(t >= len(p)):
        raise ValueError("Invalid mesh coordinates or connectivity")
    v = p[t]
    volume = np.linalg.det(np.stack((v[:, 1]-v[:, 0], v[:, 2]-v[:, 0], v[:, 3]-v[:, 0]), axis=2))/6
    if not np.isfinite(volume).all() or np.any(volume <= 0):
        raise ValueError("Mesh contains inverted or degenerate tetrahedra")
    faces = np.concatenate([t[:, ids] for ids in ((0, 1, 2), (0, 1, 3), (0, 2, 3), (1, 2, 3))])
    faces, counts = np.unique(np.sort(faces, axis=1), axis=0, return_counts=True)
    if np.any(counts > 2):
        raise ValueError("Nonmanifold volume mesh")
    exterior = {tuple(f) for f in faces[counts == 1]}
    boundary = [tuple(f) for f in np.sort(mesh.boundary_triangles, axis=1)]
    if len(boundary) != len(exterior) or set(boundary) != exterior:
        raise ValueError("Volume boundary is not completely covered by surface patches")
    if len(mesh.boundary_patch) != len(boundary) or set(mesh.boundary_patch) != set(range(len(mesh.patches))):
        raise ValueError("Invalid surface patch coverage")
    if geometry is not None and not np.isclose(volume.sum(), geometry.volume, rtol=1e-6, atol=abs(geometry.volume)*1e-10):
        raise ValueError("Meshed volume differs from the imported solid; check cavities and surface validity")
    return volume


def generate_mesh(geometry, settings, point_loads=(), progress=lambda text: None):
    if fingerprint(geometry.path, geometry.units) != geometry.fingerprint:
        raise ValueError("Geometry changed; import it again and reassign boundaries")
    progress("Classifying source surface patches")
    with gmsh_model() as gmsh:
        groups, logical_patches = discrete_geometry(gmsh, geometry, settings)
        loops = []
        order = sorted(range(len(geometry.shells)), key=lambda i: geometry.depths[i])
        for index in order:
            shell = set(geometry.shells[index])
            tags = []
            for members, tag, _ in groups:
                if shell.intersection(members):
                    if not set(members) <= shell:
                        raise ValueError("A Gmsh patch spans disconnected surface shells")
                    tags.append(tag)
            loops.append(gmsh.model.geo.addSurfaceLoop(tags))
        gmsh.model.geo.addVolume(loops)
        gmsh.model.geo.synchronize()
        gmsh.option.setNumber("Mesh.ElementOrder", 1)
        gmsh.option.setNumber("Mesh.MeshSizeMin", settings.target_size)
        gmsh.option.setNumber("Mesh.MeshSizeMax", settings.target_size)
        gmsh.option.setNumber("Mesh.MeshSizeFromCurvature", 0)
        gmsh.option.setNumber("Mesh.MeshSizeExtendFromBoundary", 0)
        progress("Generating tetrahedral volume mesh")
        gmsh.model.mesh.generate(3)
        tags, coords, _ = gmsh.model.mesh.getNodes()
        points = np.asarray(coords).reshape(-1, 3)
        lookup = {int(tag): i for i, tag in enumerate(tags)}
        def indexed(nodes, count):
            return np.fromiter((lookup[int(n)] for n in nodes), dtype=np.int64).reshape(-1, count)
        types, _, elements = gmsh.model.mesh.getElements(3)
        if list(types) != [4]:
            raise ValueError("Expected first-order tetrahedral geometry")
        tetrahedra = indexed(elements[0], 4)
        v = points[tetrahedra]
        negative = np.linalg.det(np.stack((v[:, 1]-v[:, 0], v[:, 2]-v[:, 0], v[:, 3]-v[:, 0]), axis=2)) < 0
        tetrahedra[negative] = tetrahedra[negative][:, [1, 0, 2, 3]]
        boundary, patches = [], []
        for _, tag, i in groups:
            kinds, _, nodes = gmsh.model.mesh.getElements(2, tag)
            if list(kinds) != [2]:
                raise ValueError("Expected triangular surface mesh")
            triangles = indexed(nodes[0], 3)
            boundary.extend(triangles)
            patches.extend([i]*len(triangles))
        mesh = SolidMesh(points, tetrahedra, np.asarray(boundary), np.asarray(patches),
                         logical_patches,
                         geometry.fingerprint, settings)
    progress("Checking tetrahedra, volume and boundary coverage")
    insert_point_nodes(mesh, geometry, point_loads)
    validate_mesh(mesh, geometry)
    if fingerprint(geometry.path, geometry.units) != geometry.fingerprint:
        raise ValueError("Geometry changed during meshing; import it again")
    return mesh
