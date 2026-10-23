from functools import lru_cache
from pathlib import Path

import numpy as np


@lru_cache(maxsize=32)
def _loadTriangles(path, modified, size):
    """Cache OBJ-style meshes; the file stat arguments invalidate edited assets."""
    positions = []
    triangles = []
    with path.open(encoding="utf-8", errors="ignore") as mesh:
        for line in mesh:
            fields = line.split("#", 1)[0].split()
            if not fields:
                continue
            if fields[0] == "v":
                positions.append([float(value) for value in fields[1:4]])
            elif fields[0] == "f":
                indices = [int(token.split("/")[0]) for token in fields[1:]]
                if any(index == 0 or not -len(positions) <= index <= len(positions)
                       for index in indices):
                    raise ValueError(f"Invalid face index in {path}")
                face = [positions[index - 1 if index > 0 else index] for index in indices]
                for i in range(1, len(face) - 1):
                    triangles.append([face[0], face[i], face[i + 1]])
    return np.asarray(triangles, dtype=np.float64).reshape(-1, 3, 3)


class Ray:
    """Representation of a ray with an origin and direction vector."""

    def __init__(self, position, direction):
        self._position = np.asarray(position, dtype=np.float32)
        self._direction = np.asarray(direction, dtype=np.float32)

    @property
    def position(self):
        return self._position

    @property
    def direction(self):
        return self._direction

    def at(self, t):
        return self._position + self._direction * t

    @staticmethod
    def RayPosition(position):
        """Returns ray position."""
        return position

    @staticmethod
    def Direction(direction):
        """Return ray direction."""
        return direction

    def render(self, t=100.0):
        """Build the line data for the ray from origin to direction * t."""
        end = self.at(t)
        return np.array(
            [
                self._position[0], self._position[1], self._position[2],
                end[0], end[1], end[2],
            ],
            dtype=np.float32,
        )
    
    def checkCollisions(self, objects):
        """Return the nearest forward mesh hit, or None when nothing is hit.

        Pass a SceneObject, an .obj/.simuOPart path (at the origin), or an
        iterable of either. Scene objects use the renderer's T * Rx * Ry * Rz * S
        transform. Both sides of each triangle are tested, including edges.
        Call from left-click events rather than the rendering loop.

        The result contains object (the original input), point (world space),
        distance (world units), t (for at(t)), and triangleIndex (zero based).
        Missing files and malformed meshes raise their normal loading errors.
        """
        origin = np.asarray(self.position, dtype=np.float64)
        direction = np.asarray(self.direction, dtype=np.float64)
        if (origin.shape != (3,) or direction.shape != (3,)
                or not np.all(np.isfinite(origin)) or not np.all(np.isfinite(direction))):
            raise ValueError("Ray position and direction must be finite 3D vectors")
        directionLength = np.linalg.norm(direction)
        if directionLength == 0:
            raise ValueError("Ray direction must be nonzero")
        direction = direction / directionLength
        if isinstance(objects, (str, Path)) or hasattr(objects, "meshPath"):
            objects = [objects]

        nearest = None
        for obj in objects:
            meshPath = getattr(obj, "meshPath", obj)
            if meshPath is None:
                continue
            path = Path(meshPath).resolve()
            if path.suffix.lower() not in (".obj", ".simuopart"):
                raise ValueError(f"Unsupported mesh format: {path.suffix}")
            stat = path.stat()
            triangles = _loadTriangles(path, stat.st_mtime_ns, stat.st_size)
            if not len(triangles):
                continue

            if hasattr(obj, "meshPath"):
                x, y, z = np.radians(obj.rotation)
                cx, cy, cz = np.cos([x, y, z])
                sx, sy, sz = np.sin([x, y, z])
                rx = np.array([[1, 0, 0], [0, cx, -sx], [0, sx, cx]])
                ry = np.array([[cy, 0, sy], [0, 1, 0], [-sy, 0, cy]])
                rz = np.array([[cz, -sz, 0], [sz, cz, 0], [0, 0, 1]])
                transform = rx @ ry @ rz @ np.diag(obj.scale)
                triangles = triangles @ transform.T + np.asarray(obj.position)

            # Vectorized Moller-Trumbore ray/triangle intersection.
            edge1 = triangles[:, 1] - triangles[:, 0]
            edge2 = triangles[:, 2] - triangles[:, 0]
            p = np.cross(direction, edge2)
            determinant = np.einsum("ij,ij->i", edge1, p)
            tolerance = 1e-10
            areaScale = np.linalg.norm(edge1, axis=1) * np.linalg.norm(edge2, axis=1)
            valid = np.abs(determinant) > tolerance * areaScale
            inverse = np.zeros_like(determinant)
            np.divide(1.0, determinant, out=inverse, where=valid)
            offset = origin - triangles[:, 0]
            u = np.einsum("ij,ij->i", offset, p) * inverse
            q = np.cross(offset, edge1)
            v = (q @ direction) * inverse
            distances = np.einsum("ij,ij->i", edge2, q) * inverse
            valid &= ((u >= -tolerance) & (v >= -tolerance)
                      & (u + v <= 1 + tolerance) & (distances >= 0))
            indices = np.flatnonzero(valid)
            if not len(indices):
                continue
            index = indices[np.argmin(distances[indices])]
            distance = float(distances[index])
            if nearest is None or distance < nearest["distance"]:
                nearest = {
                    "object": obj,
                    "point": origin + direction * distance,
                    "distance": distance,
                    "t": distance / directionLength,
                    "triangleIndex": int(index),
                }
        return nearest

