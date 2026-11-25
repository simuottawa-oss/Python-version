"""Viewport projection, Move handles, and box selection geometry."""

from dataclasses import dataclass
from itertools import product
import math

import glm
import numpy as np

from simuo.physics.viewport.mover import (
    AXES, AXES_BY_NAME, Mover, _ring_points, closest_point_on_line_t, object_center,
)
from simuo.rendering.picking import object_matrix, rotation_matrix

AXIS_COLORS = ('#ed6867', '#83c66d', '#6d9ff2')

ROTATE_RADIUS_PADDING = 1.15          # ring radius vs. the box's own circumscribing radius
ROTATE_HIT_PIXELS = 7
ROTATE_RING_SEGMENTS = 64


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


class ScaleGizmo:
    """Screen-sized dots on the same world axes the move gizmo uses."""

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
        best_distance = 9
        for handle in self.handles:
            distance = float(np.linalg.norm(handle.points[1] - point))
            if distance <= best_distance:
                best, best_distance = handle, distance
        return best


class ScaleDrag:
    """Resize the object along a single world axis, as a cancellable preview.

    The dragged dot's distance from the gizmo's anchor maps onto the box's
    half-size along that axis - at scale 1 the dot already sits on the box's
    actual surface (same ARROW_GAP-free placement math as the move arrows),
    so moving the mouse by that many world units changes the scale by
    roughly one "box half-size" worth, keeping the drag visually attached to
    the edge being pulled instead of feeling arbitrarily sensitive.
    """

    MIN_SCALE = 0.01

    def __init__(self, gizmo, handle, start):
        self.handle = handle
        self.start = start
        self.feedback = ''
        self.projection = gizmo.projection
        self.obj = obj = gizmo.mover.scene_object
        self.axis_index = 'xyz'.index(handle.key)
        self.axis_dir = AXES_BY_NAME[handle.key]
        self.anchor = gizmo.mover.world_center()
        self.scale_start = list(obj.scale)
        self.half_size = float(obj.localMax[self.axis_index] - obj.localMin[self.axis_index]) * 0.5
        self._t0 = closest_point_on_line_t(self.anchor, self.axis_dir, *self._ray(start))

    def _ray(self, point):
        origin, direction = self.projection.ray(point)
        return glm.vec3(*origin), glm.vec3(*direction)

    def updates(self, point):
        scale = self.scale_start.copy()
        if self.half_size > 1e-9:
            t = closest_point_on_line_t(self.anchor, self.axis_dir, *self._ray(point))
            scale[self.axis_index] = max(self.MIN_SCALE,
                                         self.scale_start[self.axis_index] + (t - self._t0) / self.half_size)
        self.feedback = f"Scale {self.handle.key.upper()} to {scale[self.axis_index]:.3g}"
        return {self.obj.identifier: {'scale': scale}}


def decompose_euler_xyz(m, previous_degrees):
    """Inverse of Rx(a)*Ry(b)*Rz(c); matches object_matrix()'s rotation order.

    previous_degrees: the pre-drag [x,y,z], used only to pick a continuous
    branch in the rare gimbal-lock case (pitch == +/-90 deg).
    """
    sin_pitch = max(-1.0, min(1.0, m[2][0]))
    pitch = math.asin(sin_pitch)
    cos_pitch = math.cos(pitch)
    if abs(cos_pitch) > 1e-6:
        roll = math.atan2(-m[2][1], m[2][2])
        yaw = math.atan2(-m[1][0], m[0][0])
    else:
        yaw = math.radians(previous_degrees[2])
        combined = math.atan2(m[0][1], m[1][1])
        roll = (combined - yaw) if sin_pitch > 0 else (yaw - combined)
    return math.degrees(roll), math.degrees(pitch), math.degrees(yaw)


@dataclass
class RotateHandle:
    key: str
    color: str
    center2d: np.ndarray
    right2d: np.ndarray
    up2d: np.ndarray
    axis_dir: glm.vec3        # world-space unit vector, object's current local axis
    points: np.ndarray        # full closed ring, screen space


class RotateGizmo:
    """Full ring handles for the object's own local axes, centered on the object.

    Each ring is centered on the object's true bounding-box center (never
    the move gizmo's user-chosen origin corner) and all three share one
    radius - the smallest of the three per-axis circumscribing radii - so
    they're all the same size instead of each hugging its own (possibly
    non-cubic) cross-section.
    """

    def __init__(self, obj, projection):
        self.mover = Mover(obj)
        self.projection = projection
        self.handles = []
        if obj.localMin is None:
            return
        # Always pivot on the object's true bounding-box center, never the
        # move gizmo's user-chosen origin corner (Mover.world_center()) -
        # rotation isn't tied to where the move handles happen to be anchored.
        origin = object_center(obj)
        model = object_matrix(obj)
        columns = [glm.normalize(glm.vec3(model[i])) for i in range(3)]
        # Half-size of the box along each local axis; a length, so it's the
        # same whether measured before or after rotation.
        half_size = [(obj.localMax[axis] - obj.localMin[axis]) * 0.5 * obj.scale[axis] for axis in range(3)]
        radius = min(math.hypot(half_size[(i + 1) % 3], half_size[(i + 2) % 3]) for i in range(3)) \
            * ROTATE_RADIUS_PADDING
        if radius <= 0:
            return

        for i, (key, color) in enumerate(zip('xyz', AXIS_COLORS)):
            right, up = columns[(i + 1) % 3], columns[(i + 2) % 3]
            center = projection.point(origin)
            if center is None or not -1 <= center[2] <= 1:
                continue
            right_point = projection.point(origin + right * radius)
            up_point = projection.point(origin + up * radius)
            if right_point is None or up_point is None:
                continue
            right2d, up2d = right_point[:2] - center[:2], up_point[:2] - center[:2]
            if abs(right2d[0] * up2d[1] - right2d[1] * up2d[0]) < 25:
                continue  # ring viewed too edge-on to drag reliably

            ring_world = _ring_points(origin, right, up, radius, ROTATE_RING_SEGMENTS)
            ring_projected = [projection.point(point) for point in ring_world]
            if any(point is None for point in ring_projected):
                continue
            points = np.array([point[:2] for point in ring_projected])
            self.handles.append(RotateHandle(key, color, center[:2], right2d, up2d, columns[i], points))

    def hit(self, point):
        point = np.asarray(point)
        best = None
        best_distance = ROTATE_HIT_PIXELS
        for handle in self.handles:
            points = handle.points
            for a, b in zip(points, np.roll(points, -1, axis=0)):
                distance = segment_distance(point, a, b)
                if distance <= best_distance:
                    best, best_distance = handle, distance
        return best


class RotateDrag:
    """Spin the object about one of its own local axes as a cancellable preview."""

    def __init__(self, gizmo, handle, start):
        self.handle = handle
        self.start = start
        self.feedback = ''
        self.mover = gizmo.mover
        self.axis_dir = handle.axis_dir
        obj = self.mover.scene_object
        self.rotation_start = list(obj.rotation)
        # The object only ever rotates about its local origin (obj.position),
        # which for many meshes isn't the box's geometric center (e.g. a
        # model whose origin sits at its base) - so without compensation the
        # box visibly swings around that off-center point instead of the
        # pivot the gizmo is drawn around. Freeze that true center now and
        # re-solve position each update so it stays fixed in world space.
        self.pivot = object_center(obj)
        local_center = (glm.vec3(*obj.localMin) + glm.vec3(*obj.localMax)) * 0.5
        self.local_center_scaled = local_center * glm.vec3(*obj.scale)
        self.center2d, self.right2d, self.up2d = handle.center2d, handle.right2d, handle.up2d
        self._last_angle = 0.0
        self.start_angle = self._angle_at(start)
        self._last_angle = self.start_angle
        self.total_degrees = 0.0

    def _angle_at(self, point):
        delta = np.asarray(point) - self.center2d
        r, u = self.right2d, self.up2d
        det = r[0] * u[1] - u[0] * r[1]
        if abs(det) < 1e-9:
            return self._last_angle
        alpha = (delta[0] * u[1] - u[0] * delta[1]) / det
        beta = (r[0] * delta[1] - delta[0] * r[1]) / det
        return math.atan2(beta, alpha)

    def updates(self, point):
        angle = self._angle_at(point)
        wrapped = (angle - self._last_angle + math.pi) % (2 * math.pi) - math.pi
        self.total_degrees += math.degrees(wrapped)
        self._last_angle = angle
        start_matrix = rotation_matrix(self.rotation_start)
        delta_matrix = glm.rotate(glm.mat4(1.0), math.radians(self.total_degrees), self.axis_dir)
        euler = decompose_euler_xyz(delta_matrix * start_matrix, self.rotation_start)
        obj = self.mover.scene_object
        # position + R(new)*local_center_scaled must still land on the frozen
        # pivot, so solve position backwards from the new orientation.
        offset = glm.vec3(rotation_matrix(euler) * glm.vec4(*self.local_center_scaled, 1.0))
        position = list(self.pivot - offset)
        self.feedback = f"Rotate {self.handle.key.upper()} by {self.total_degrees:.1f}°"
        return {obj.identifier: {'rotation': list(euler), 'position': position}}


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
