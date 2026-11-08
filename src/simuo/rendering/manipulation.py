"""Viewport projection, Move handles, and box selection geometry."""

from dataclasses import dataclass
from itertools import product
import math

import glm
import numpy as np

from simuo.physics.viewport.mover import AXES, Mover
from simuo.rendering.picking import object_matrix

AXIS_COLORS = ('#ed6867', '#83c66d', '#6d9ff2')


class Projection:
    def __init__(self, camera, width, height):
        self.width, self.height = max(1, width), max(1, height)
        self.camera = camera
        self.view = camera.view_matrix()
        self.projection = glm.perspective(glm.radians(camera.field_of_view), self.width/self.height,
                                          camera.near_plane, camera.far_plane)
        self.matrix = self.projection * self.view
        self.inverse = glm.inverse(self.matrix)

    def point(self, world):
        clip = self.matrix * glm.vec4(*world, 1)
        if clip.w <= 0:
            return None
        return np.array(((clip.x/clip.w+1)*self.width/2, (1-clip.y/clip.w)*self.height/2, clip.z/clip.w))

    def ray(self, point):
        near = self.inverse * glm.vec4(point[0]*2/self.width-1, 1-point[1]*2/self.height, -1, 1)
        near /= near.w
        origin = np.array(self.camera.position, dtype=float)
        direction = np.array(near, dtype=float)[:3] - origin
        return origin, direction / np.linalg.norm(direction)

    def world_per_pixel(self, world):
        depth = float(glm.dot(glm.vec3(*world) - self.camera.position, self.camera.front))
        return 2 * depth * math.tan(math.radians(self.camera.field_of_view/2)) / self.height


def segment_distance(point, a, b):
    delta = b-a
    t = float(np.clip(np.dot(point-a, delta) / max(1e-12, np.dot(delta, delta)), 0, 1))
    return float(np.linalg.norm(point - (a + delta*t)))


@dataclass
class MoveHandle:
    key: str
    points: np.ndarray
    color: str


class MoveGizmo:
    """Screen-sized arrows for the existing world-axis mover."""

    def __init__(self, obj, projection):
        self.mover = Mover(obj)
        self.projection = projection
        self.handles = []
        origin = self.mover.world_center()
        center = projection.point(origin)
        length = projection.world_per_pixel(origin) * 80
        if center is None or not -1 <= center[2] <= 1 or length <= 0:
            return

        for (axis, direction, _), color in zip(AXES, AXIS_COLORS):
            end = projection.point(origin + direction * length)
            if end is not None and np.linalg.norm(end[:2] - center[:2]) >= 14:
                self.handles.append(MoveHandle(axis, np.array([center[:2], end[:2]]), color))

    def hit(self, point):
        point = np.asarray(point)
        best = None
        best_distance = 7
        for handle in self.handles:
            a, b = handle.points
            direction = b - a
            start = a + direction * min(.2, 14 / np.linalg.norm(direction))
            distance = segment_distance(point, start, b)
            if distance <= best_distance:
                best, best_distance = handle, distance
        return best


class MoveDrag:
    """Send Mover's positions to the editor as cancellable previews."""

    def __init__(self, gizmo, handle, start):
        self.handle = handle
        self.start = start
        self.feedback = ''
        self.mover = gizmo.mover
        self.projection = gizmo.projection
        self.mover.begin_drag(handle.key, *self._ray(start))

    def _ray(self, point):
        origin, direction = self.projection.ray(point)
        return glm.vec3(*origin), glm.vec3(*direction)

    def updates(self, point):
        position = self.mover.drag_position(*self._ray(point))
        obj = self.mover.scene_object
        axis = 'xyz'.index(self.handle.key)
        self.feedback = f"Move {self.handle.key.upper()} to {position[axis]:.3g}"
        return {obj.identifier: {'position': position}}


def box_candidates(rendered_objects, projection, rect):
    """Select-through CPU fallback: clip mesh triangles to the selection frustum."""
    left, top, right, bottom = rect
    # Homogeneous clip planes include the box sides and near/far view planes.
    x0, x1 = 2*left/projection.width-1, 2*right/projection.width-1
    y0, y1 = 1-2*bottom/projection.height, 1-2*top/projection.height
    planes = (np.array((1, 0, 0, -x0)), np.array((-1, 0, 0, x1)),
              np.array((0, 1, 0, -y0)), np.array((0, -1, 0, y1)),
              np.array((0, 0, 1, 1)), np.array((0, 0, -1, 1)))
    selected = []
    for item in rendered_objects:
        obj, mesh = item['SceneObject'], item.get('pick_mesh')
        if not obj.viewport_visible or obj.viewport_locked or mesh is None or not len(mesh.triangles) or 0 in obj.scale:
            continue
        matrix = projection.matrix * object_matrix(obj)
        # Bounds reject most objects before triangle clipping.
        corners = [np.array(matrix*glm.vec4(x, y, z, 1), dtype=float) for x, y, z in product(
            (float(mesh.minimum[0]), float(mesh.maximum[0])),
            (float(mesh.minimum[1]), float(mesh.maximum[1])), (float(mesh.minimum[2]), float(mesh.maximum[2])))]
        if any(all(np.dot(plane, corner) < 0 for corner in corners) for plane in planes):
            continue
        found = False
        for triangle in mesh.triangles:
            polygon = [np.array(matrix*glm.vec4(*point, 1), dtype=float) for point in triangle]
            for plane in planes:
                output = []
                for a, b in zip(polygon, polygon[1:]+polygon[:1]):
                    da, db = np.dot(plane, a), np.dot(plane, b)
                    if da >= 0:
                        output.append(a)
                    if (da >= 0) != (db >= 0):
                        output.append(a+(b-a)*(da/(da-db)))
                polygon = output
                if not polygon:
                    break
            if polygon:
                found = True
                break
        if found:
            selected.append(obj.identifier)
    return selected
