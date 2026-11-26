"""CPU asset loading shared by scene import and both OpenGL upload paths."""
from dataclasses import dataclass
from pathlib import Path

import numpy as np

from simuo.parts.part_format import Part, load_part


@dataclass
class PartAsset:
    vertices: np.ndarray  # flat interleaved float32 position/normal data
    part: Part | None = None

    @property
    def color(self):
        """Resolve the part's hex color, or use the legacy mesh default.

        Returns:
            tuple: Three RGB floats in the range 0 to 1.
        """
        if self.part is None:
            return (0.72, 0.76, 0.82)
        return tuple(int(self.part.color[i:i+2], 16)/255 for i in (1, 3, 5))


def load_obj_geometry(filename):
    """Read indexed OBJ triangles in double precision, without touching the source."""
    positions, triangles = [], []
    with Path(filename).open(encoding="utf-8-sig") as stream:
        for line_number, line in enumerate(stream, 1):
            tokens = line.split("#", 1)[0].split()
            if not tokens:
                continue
            try:
                if tokens[0] == "v":
                    if len(tokens) < 4:
                        raise ValueError("Vertex needs three coordinates")
                    position = [float(v) for v in tokens[1:4]]
                    if not np.isfinite(position).all():
                        raise ValueError("Vertex coordinates must be finite")
                    positions.append(position)
                elif tokens[0] == "f":
                    if len(tokens) < 4:
                        raise ValueError("Face needs at least three vertices")
                    indices = []
                    for token in tokens[1:]:
                        index = int(token.split("/", 1)[0])
                        if index == 0:
                            raise ValueError("OBJ indices cannot be zero")
                        index = len(positions)+index if index < 0 else index-1
                        if not 0 <= index < len(positions):
                            raise ValueError("Face references an unavailable vertex")
                        indices.append(index)
                    triangles.extend((indices[0], indices[i], indices[i+1]) for i in range(1, len(indices)-1))
            except (ValueError, IndexError, OverflowError) as error:
                raise ValueError(f"{filename}:{line_number}: {error}") from error
    if not triangles:
        raise ValueError(f"{filename}: no renderable finite triangle geometry")
    return np.asarray(positions, dtype=np.float64), np.asarray(triangles, dtype=np.int64)


def loadObjFlatShaded(filename):
    """Keep the rendering interface while sharing double-precision OBJ extraction."""
    points, indices = load_obj_geometry(filename)
    triangles = points[indices]
    normals = np.cross(triangles[:, 1]-triangles[:, 0], triangles[:, 2]-triangles[:, 0])
    lengths = np.linalg.norm(normals, axis=1)
    valid = lengths > 0
    normals[valid] /= lengths[valid, None]
    normals[~valid] = (0., 1., 0.)
    with np.errstate(over="ignore", invalid="ignore"):
        result = np.concatenate((triangles, np.repeat(normals[:, None, :], 3, axis=1)), axis=2).astype(np.float32).ravel()
    if not np.isfinite(result).all():
        raise ValueError(f"{filename}: no renderable finite triangle geometry")
    return result


def box_vertices(part, dtype=np.float32):
    # Normals are analytic, avoiding cross-product underflow for tiny boxes.
    """Build a centered box mesh with analytic outward normals and check GPU precision.

    Args:
        part (Part): Box definition whose size and eight local corners form the mesh.

    Returns:
        numpy.ndarray: Flat float32 array for 36 vertices, each containing XYZ and
        normal XYZ.
    """
    positions = part.vertices((0, 0, 0))
    faces = [((0,3,2,1), (0,0,-1)), ((4,5,6,7), (0,0,1)),
             ((0,4,7,3), (-1,0,0)), ((1,2,6,5), (1,0,0)),
             ((0,1,5,4), (0,-1,0)), ((3,7,6,2), (0,1,0))]
    output = []
    for (a,b,c,d), normal in faces:
        for index in (a,b,c,a,c,d):
            output.extend((*positions[index], *normal))
    with np.errstate(over="ignore", invalid="ignore", under="ignore"):
        vertices = np.asarray(output, dtype=dtype)
    # Parts may be numerically valid in double precision but unrenderable on GPU.
    rendered = vertices.reshape(-1,6)[:, :3]
    if not np.isfinite(vertices).all() or np.any(np.ptp(rendered, axis=0) <= 0):
        raise ValueError("Part dimensions are outside the OpenGL float32 rendering range")
    return vertices


def load_asset(path):
    """Dispatch by file content to validated JSON geometry or legacy OBJ. Invalid JSON is
    never retried as OBJ; JSON spawn positions are checked for float32 precision.

    Args:
        path (str or Path): Source or destination file path used by this operation.

    Returns:
        PartAsset: CPU triangle mesh and optional Part definition; I/O and validation
        errors propagate.
    """
    path = Path(path)
    with path.open(encoding="utf-8-sig") as stream:
        while True:
            first = stream.read(1)
            if not first or not first.isspace():
                break
    if first in ("{", "["):
        part = load_part(path)
        # The current renderer uses float32 world transforms. Reject positions
        # whose precision is insufficient to distinguish the part's dimensions.
        with np.errstate(over="ignore", invalid="ignore"):
            position = np.asarray(part.position, dtype=np.float32)
            resolution = np.abs(np.spacing(position))
        if not np.isfinite(position).all() or any(resolution >= np.asarray(part.size)/2):
            raise ValueError("Initial position exceeds the precision available for this part's size")
        if part.features is not None:
            return PartAsset(part.features.vertices, part)
        if part.sketch is not None:
            from simuo.parts.sketch_geometry import prism_vertices
            return PartAsset(prism_vertices(part.sketch), part)
        return PartAsset(box_vertices(part), part)
    return PartAsset(loadObjFlatShaded(path))
