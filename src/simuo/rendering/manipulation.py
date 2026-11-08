"""Projection, gizmo hit testing, constrained drags, and selection geometry.

All coordinates are logical viewport pixels. Math is independent of Qt widgets
and GL contexts, so drag behavior can be tested without a display.
"""

from dataclasses import dataclass
from itertools import product
import math

import glm
import numpy as np

from simuo.rendering.picking import object_matrix

AXIS_COLORS = ('#ed6867', '#83c66d', '#6d9ff2')


def rotation_matrix(degrees):
    x, y, z = np.radians(degrees)
    cx, cy, cz, sx, sy, sz = math.cos(x), math.cos(y), math.cos(z), math.sin(x), math.sin(y), math.sin(z)
    return np.array(((cy*cz, -cy*sz, sy), (cx*sz+sx*sy*cz, cx*cz-sx*sy*sz, -sx*cy),
                     (sx*sz-cx*sy*cz, sx*cz+cx*sy*sz, cx*cy)), dtype=float)


def matrix_euler(matrix):
    y = math.asin(float(np.clip(matrix[0, 2], -1, 1)))
    if abs(math.cos(y)) > 1e-7:
        x, z = math.atan2(-matrix[1, 2], matrix[2, 2]), math.atan2(-matrix[0, 1], matrix[0, 0])
    else:
        x, z = math.atan2(matrix[2, 1], matrix[1, 1]), 0.0
    return np.degrees((x, y, z)).tolist()


def axis_rotation(axis, angle):
    x, y, z = axis
    cross = np.array(((0, -z, y), (z, 0, -x), (-y, x, 0)))
    return np.eye(3)*math.cos(angle) + cross*math.sin(angle) + np.outer(axis, axis)*(1-math.cos(angle))


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


def inside_polygon(point, polygon):
    crosses = []
    for a, b in zip(polygon, np.roll(polygon, -1, axis=0)):
        delta, offset = b-a, point-a
        crosses.append(delta[0]*offset[1] - delta[1]*offset[0])
    return min(crosses) >= -1e-6 or max(crosses) <= 1e-6


@dataclass
class Handle:
    key: str
    kind: str
    axis: int | None
    points: np.ndarray
    color: str


class Gizmo:
    def __init__(self, objects, tool, projection, orientation='world', pivot='median'):
        self.objects, self.tool, self.projection = tuple(objects), tool, projection
        positions = np.array([obj.position for obj in objects], dtype=float)
        self.pivot = positions[-1].copy() if pivot == 'active' else positions.mean(axis=0)
        self.basis = rotation_matrix(objects[-1].rotation) if orientation == 'local' or tool == 'scale' else np.eye(3)
        self.center = projection.point(self.pivot)
        self.handles = []
        self.pixel_scale = projection.world_per_pixel(self.pivot)
        if self.center is None or not -1 <= self.center[2] <= 1 or self.pixel_scale <= 0:
            return
        self.length = self.pixel_scale * 80
        center = self.center[:2]
        for axis in range(3):
            color = AXIS_COLORS[axis]
            if tool == 'rotate':
                u, v = self.basis[:, (axis+1) % 3], self.basis[:, (axis+2) % 3]
                points = [projection.point(self.pivot + self.length*(math.cos(angle)*u + math.sin(angle)*v))
                          for angle in np.linspace(0, math.tau, 97)]
                if all(point is not None for point in points):
                    self.handles.append(Handle(str(axis), 'ring', axis, np.array(points)[:, :2], color))
            else:
                end = projection.point(self.pivot + self.basis[:, axis]*self.length)
                if end is None:
                    continue
                if np.linalg.norm(end[:2]-center) < 14:
                    # A view-aligned axis stays usable as a small colored depth handle.
                    end2 = center + np.array((0, 23))
                    self.handles.append(Handle(str(axis), 'depth', axis, np.array([end2]), color))
                else:
                    self.handles.append(Handle(str(axis), 'axis', axis, np.array([center, end[:2]]), color))
        if tool == 'move':
            for a, b in ((0, 1), (1, 2), (2, 0)):
                points = [projection.point(self.pivot + self.length*(u*self.basis[:, a]+v*self.basis[:, b]))
                          for u, v in ((.2, .2), (.4, .2), (.4, .4), (.2, .4))]
                if all(point is not None for point in points):
                    polygon = np.array(points)[:, :2]
                    area = abs(np.dot(polygon[:, 0], np.roll(polygon[:, 1], -1)) - np.dot(polygon[:, 1], np.roll(polygon[:, 0], -1)))/2
                    if area > 30:
                        self.handles.append(Handle(f'{a}{b}', 'plane', a, polygon, AXIS_COLORS[(3-a-b)]))
        if tool != 'rotate':
            self.handles.append(Handle('free', 'center', None, np.array([center]), '#e6eaf0'))

    def hit(self, point):
        point = np.array(point)
        for handle in reversed(self.handles):
            if handle.kind == 'center' and np.linalg.norm(point-handle.points[0]) <= 7:
                return handle
            if handle.kind == 'plane' and inside_polygon(point, handle.points):
                return handle
        candidates = []
        for handle in self.handles:
            if handle.kind == 'depth':
                distance = float(np.linalg.norm(point-handle.points[0]))
            elif handle.kind == 'axis':
                a, b = handle.points
                a = a + (b-a)*min(.2, 14/max(1, np.linalg.norm(b-a)))
                distance = segment_distance(point, a, b)
            elif handle.kind == 'ring':
                distance = min(segment_distance(point, a, b) for a, b in zip(handle.points, handle.points[1:]))
            else:
                continue
            if distance <= 7:
                candidates.append((distance, handle))
        return min(candidates, key=lambda item: item[0])[1] if candidates else None


def ray_plane(projection, point, pivot, normal):
    origin, direction = projection.ray(point)
    denominator = float(np.dot(direction, normal))
    if abs(denominator) < 1e-7:
        return None
    distance = float(np.dot(pivot-origin, normal) / denominator)
    return origin + direction*distance if distance > 0 else None


class TransformDrag:
    def __init__(self, gizmo, handle, start):
        self.gizmo, self.handle, self.start = gizmo, handle, np.array(start, dtype=float)
        self.before = {obj.identifier: {name: np.array(getattr(obj, name), dtype=float)
                                       for name in ('position', 'rotation', 'scale')} for obj in gizmo.objects}
        self.angle = 0.0
        self.last_angle = None
        self.feedback = ''
        self.axis = gizmo.basis[:, handle.axis] if handle.axis is not None else None
        self.normal = np.array(gizmo.projection.camera.front, dtype=float)
        if handle.kind == 'plane':
            self.normal = np.cross(gizmo.basis[:, int(handle.key[0])], gizmo.basis[:, int(handle.key[1])])
        elif gizmo.tool == 'rotate':
            self.normal = self.axis
        elif handle.axis is not None:
            self.normal = self.normal - self.axis*np.dot(self.normal, self.axis)
        norm = np.linalg.norm(self.normal)
        self.normal = self.normal/norm if norm > 1e-5 else np.array((0., 0., 0.))
        self.initial_hit = ray_plane(gizmo.projection, self.start, gizmo.pivot, self.normal) if norm > 1e-5 else None
        if gizmo.tool == 'rotate' and self.initial_hit is not None:
            self.last_angle = self._angle(self.initial_hit)

    def _angle(self, point):
        axis = self.handle.axis
        offset = point-self.gizmo.pivot
        return math.atan2(np.dot(offset, self.gizmo.basis[:, (axis+2) % 3]),
                          np.dot(offset, self.gizmo.basis[:, (axis+1) % 3]))

    def updates(self, point, snap=False, precision=False):
        g, h = self.gizmo, self.handle
        point = np.array(point, dtype=float)
        mouse = point-self.start
        fine = .1 if precision else 1.
        updates = {}
        if g.tool == 'move':
            hit = ray_plane(g.projection, point, g.pivot, self.normal)
            if hit is not None and self.initial_hit is not None and h.kind != 'depth':
                delta = hit-self.initial_hit
                if h.axis is not None and h.kind != 'plane':
                    delta = self.axis*np.dot(delta, self.axis)
            else:
                direction = self._screen_axis()
                delta = self.axis*np.dot(mouse, direction)*g.pixel_scale if self.axis is not None else np.zeros(3)
            delta *= fine
            if snap:
                local = g.basis.T @ delta
                delta = g.basis @ np.round(local)
            for key, original in self.before.items():
                updates[key] = {'position': (original['position']+delta).tolist()}
            self.feedback = 'Move ' + ' / '.join(f'{value:.3g}' for value in delta)
        elif g.tool == 'rotate':
            hit = ray_plane(g.projection, point, g.pivot, self.normal)
            if self.initial_hit is not None and hit is not None and abs(np.dot(self.axis, np.array(g.projection.camera.front))) > .15:
                angle = self._angle(hit)
                self.angle += (angle-self.last_angle+math.pi) % math.tau-math.pi
                self.last_angle = angle
                amount = self.angle*fine
            else:
                amount = (mouse[0]-mouse[1])*math.pi/180*fine
            if snap:
                step = math.radians(15)
                amount = round(amount/step)*step
            rotation = axis_rotation(self.axis, amount)
            for key, original in self.before.items():
                updates[key] = {'position': (g.pivot + rotation@(original['position']-g.pivot)).tolist(),
                                'rotation': (original['rotation'].tolist() if abs(amount) < 1e-12
                                             else matrix_euler(rotation @ rotation_matrix(original['rotation'])))}
            self.feedback = f'Rotate {math.degrees(amount):.1f}°'
        else:
            amount = 1 + ((mouse[0]-mouse[1])/120 if h.axis is None else np.dot(mouse, self._screen_axis())/80)*fine
            if snap:
                amount = round(amount/.1)*.1
            amount = max(.001, amount)
            factors = np.ones(3)
            if h.axis is None:
                factors[:] = amount
            else:
                factors[h.axis] = amount
            linear = g.basis @ np.diag(factors) @ g.basis.T
            for key, original in self.before.items():
                updates[key] = {'position': (g.pivot + linear@(original['position']-g.pivot)).tolist(),
                                'scale': (original['scale']*factors).tolist()}
            self.feedback = f'Scale {amount:.3f}×'
        return updates

    def _screen_axis(self):
        point = self.gizmo.projection.point(self.gizmo.pivot + self.axis*self.gizmo.length)
        delta = point[:2]-self.gizmo.center[:2] if point is not None else np.zeros(2)
        return delta/np.linalg.norm(delta) if np.linalg.norm(delta) > 14 else np.array((0., -1.))


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
