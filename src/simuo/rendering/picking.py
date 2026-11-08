"""Ray picking against the same transformed triangles used for rendering."""

import glm
import numpy as np


def object_matrix(obj):
    """Keep rendering and picking on the same translation/rotation/scale order."""
    model = glm.translate(glm.mat4(1.0), glm.vec3(*obj.position))
    for angle, axis in zip(obj.rotation, ((1, 0, 0), (0, 1, 0), (0, 0, 1))):
        model = glm.rotate(model, glm.radians(angle), glm.vec3(*axis))
    return glm.scale(model, glm.vec3(*obj.scale))


class PickMesh:
    """Cache mesh-space triangles and bounds once, when a mesh is uploaded."""

    def __init__(self, vertex_data):
        self.triangles = vertex_data.reshape(-1, 6)[:, :3].reshape(-1, 3, 3).copy()
        if len(self.triangles):
            self.minimum = self.triangles.min(axis=(0, 1))
            self.maximum = self.triangles.max(axis=(0, 1))
        else:
            self.minimum = self.maximum = np.zeros(3)

    def intersect(self, origin, direction, minimum_distance, maximum_distance):
        """Return the closest positive ray parameter, without normalizing direction.

        Keeping the inverse-transformed direction unnormalized preserves world
        distances even when an object has nonuniform or negative scale.
        """
        if not len(self.triangles):
            return None
        lower, upper = minimum_distance, maximum_distance
        for axis in range(3):
            if abs(direction[axis]) < 1e-15:
                if not self.minimum[axis] <= origin[axis] <= self.maximum[axis]:
                    return None
            else:
                a = (self.minimum[axis] - origin[axis]) / direction[axis]
                b = (self.maximum[axis] - origin[axis]) / direction[axis]
                lower, upper = max(lower, min(a, b)), min(upper, max(a, b))
                if lower > upper:
                    return None

        closest = maximum_distance
        hit = False
        # Bound temporary allocations for large imported meshes.
        for start in range(0, len(self.triangles), 32768):
            triangles = self.triangles[start:start + 32768]
            edge1 = triangles[:, 1] - triangles[:, 0]
            edge2 = triangles[:, 2] - triangles[:, 0]
            p = np.cross(direction, edge2)
            determinant = np.einsum("ij,ij->i", edge1, p)
            valid = np.abs(determinant) > 1e-12
            inverse = np.zeros_like(determinant)
            np.divide(1.0, determinant, out=inverse, where=valid)
            delta = origin - triangles[:, 0]
            u = np.einsum("ij,ij->i", delta, p) * inverse
            q = np.cross(delta, edge1)
            v = q @ direction * inverse
            distance = np.einsum("ij,ij->i", edge2, q) * inverse
            valid &= (u >= -1e-7) & (v >= -1e-7) & (u + v <= 1.0 + 1e-7)
            valid &= (distance >= minimum_distance) & (distance <= closest)
            if valid.any():
                closest = float(distance[valid].min())
                hit = True
        return closest if hit else None


def pick_object(render_objects, origin, direction, minimum_distance=0.0, maximum_distance=1000.0):
    """Find the frontmost visible mesh hit; bounding boxes alone never select."""
    closest = maximum_distance
    selected = None
    for rendered in render_objects:
        obj = rendered["SceneObject"]
        mesh = rendered.get("pick_mesh")
        if (not obj.viewport_visible or obj.viewport_locked
                or mesh is None or any(scale == 0 for scale in obj.scale)):
            continue
        inverse = glm.inverse(object_matrix(obj))
        local_origin = np.array(inverse * glm.vec4(*origin, 1.0), dtype=np.float64)[:3]
        local_direction = np.array(inverse * glm.vec4(*direction, 0.0), dtype=np.float64)[:3]
        if not (np.isfinite(local_origin).all() and np.isfinite(local_direction).all()):
            continue
        distance = mesh.intersect(local_origin, local_direction, minimum_distance, closest)
        if distance is not None and (selected is None or distance < closest):
            selected, closest = obj, distance
    return selected
