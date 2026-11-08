"""Move gizmo for the SimuO 3D editor.

This module builds the three colored arrows that appear around a selected
object, figures out where those arrows sit in world space, hit-tests the
mouse ray against them, and drags the object along a single world axis
while one is held.
"""

import glm
import math
import numpy as np

# Per-axis (name, world direction, base color) used everywhere in this
# module: placing an arrow, hit-testing it, and coloring it for rendering.
AXES = [
    ("x", glm.vec3(1, 0, 0), (0.85, 0.15, 0.15)),  # red
    ("y", glm.vec3(0, 1, 0), (0.15, 0.80, 0.15)),  # green
    ("z", glm.vec3(0, 0, 1), (0.15, 0.35, 0.90)),  # blue
]

# Lookup from axis name back to its direction, used once an axis has already
# been identified by name (e.g. the result of hit_test) and a drag needs the
# actual direction vector to move along.
AXES_BY_NAME = {name: direction for name, direction, _color in AXES}

# Clearance between the object's bounding box and the start of each arrow,
# so the gizmo doesn't start flush against the mesh surface.
ARROW_GAP = 0.3

# Fixed dimensions of the arrow mesh (cylinder shaft + cone head), in world
# units. Independent of the selected object's size.
SHAFT_LENGTH = 1.2
SHAFT_RADIUS = 0.05
HEAD_LENGTH = 0.4
HEAD_RADIUS = 0.13

# Maximum world-space distance from a ray to an arrow that still counts as a
# hit. Fixed in world units, so picking gets harder the farther the camera
# is from the gizmo - a known v1 simplification (see plan notes).
PICK_RADIUS = 0.2


def _perpendicular_basis(direction):
    """Build two unit vectors perpendicular to `direction` and to each other.

    Used to draw a circle of points around an arbitrary direction without
    needing a full rotation matrix - the same two-cross-product technique
    Camera.update_vectors() already uses to build right/up from front.

    Args:
        direction: Unit vector the circle should be centered around.

    Returns:
        tuple[glm.vec3, glm.vec3]: Two unit vectors, perpendicular to
        `direction` and to each other.
    """
    reference = glm.vec3(0, 1, 0)
    if abs(glm.dot(direction, reference)) > 0.99:
        # direction is nearly parallel to the default reference - cross
        # product of two parallel vectors is zero, so swap references.
        reference = glm.vec3(1, 0, 0)

    right = glm.normalize(glm.cross(direction, reference))
    up = glm.normalize(glm.cross(right, direction))
    return right, up


def _ring_points(center_point, right, up, radius, segments):
    """Generate `segments` points evenly spaced around a circle.

    Args:
        center_point: World-space center of the circle.
        right: Unit vector spanning one axis of the circle's plane.
        up: Unit vector spanning the other axis of the circle's plane.
        radius: Circle radius.
        segments: Number of points to place around the circle.

    Returns:
        list[glm.vec3]: Points around the circle, in order.
    """
    points = []
    for i in range(segments):
        angle = 2 * math.pi * i / segments
        offset = right * math.cos(angle) * radius + up * math.sin(angle) * radius
        points.append(center_point + offset)
    return points


def build_arrow_mesh(start, direction, shaft_len, shaft_r, head_len, head_r, segments=10):
    """Build triangle data for one arrow: a cylinder shaft plus a cone head.

    Args:
        start: World-space point where the arrow begins.
        direction: Unit vector the arrow points along.
        shaft_len: Length of the cylindrical shaft.
        shaft_r: Radius of the shaft.
        head_len: Length of the cone head.
        head_r: Radius of the cone head's base.
        segments: Number of sides used to approximate the shaft/head circles.

    Returns:
        list[glm.vec3]: Triangle corner points, 3 per triangle.
    """
    direction = glm.normalize(direction)
    right, up = _perpendicular_basis(direction)

    shaft_top = start + direction * shaft_len
    head_tip = shaft_top + direction * head_len

    shaft_ring_bottom = _ring_points(start, right, up, shaft_r, segments)
    shaft_ring_top = _ring_points(shaft_top, right, up, shaft_r, segments)
    head_ring = _ring_points(shaft_top, right, up, head_r, segments)

    triangles = []

    # Shaft walls: each quad between the two rings becomes 2 triangles.
    for i in range(segments):
        j = (i + 1) % segments
        a, b = shaft_ring_bottom[i], shaft_ring_bottom[j]
        c, d = shaft_ring_top[i], shaft_ring_top[j]
        triangles += [a, b, c]
        triangles += [b, d, c]

    # Cone head: a triangle fan from the base ring to the single tip point.
    for i in range(segments):
        j = (i + 1) % segments
        a, b = head_ring[i], head_ring[j]
        triangles += [a, b, head_tip]

    return triangles


def _flatten(points):
    """Convert a list of glm.vec3 into one flat (N*3,) float32 array for GPU upload."""
    flat = []
    for p in points:
        flat.extend([p.x, p.y, p.z])
    return np.array(flat, dtype=np.float32)


def ray_segment_distance(ray_origin, ray_direction, seg_start, seg_end):
    """Shortest distance between a ray and a finite line segment.

    Finds the closest point on the ray and the closest point on the segment
    to each other, clamping the segment's parameter to its own ends and the
    ray's parameter to non-negative values, then returns the distance
    between those two points. Used for hit-testing the mouse ray against a
    single arrow's visible shaft.

    Args:
        ray_origin: Ray starting point.
        ray_direction: Ray direction (expected to already be a unit vector).
        seg_start: Segment start point.
        seg_end: Segment end point.

    Returns:
        float: Shortest distance between the ray and the segment.
    """
    d1 = ray_direction
    d2 = seg_end - seg_start
    r = ray_origin - seg_start

    a = glm.dot(d1, d1)
    b = glm.dot(d1, d2)
    e = glm.dot(d2, d2)
    c = glm.dot(d1, r)
    f = glm.dot(d2, r)

    denom = a * e - b * b
    s = (b * f - c * e) / denom if abs(denom) > 1e-8 else 0.0

    t = (b * s + f) / e
    t = max(0.0, min(1.0, t))          # the arrow is finite — clamp to its ends
    s = (t * b - c) / a if a > 1e-8 else 0.0
    s = max(0.0, s)                     # the ray can't go backward

    closest_on_ray = ray_origin + d1 * s
    closest_on_segment = seg_start + d2 * t

    return glm.length(closest_on_ray - closest_on_segment)


def closest_point_on_line_t(line_point, line_dir, ray_origin, ray_dir):
    """Where along an infinite line a ray passes closest to it.

    Same closest-point math as ray_segment_distance, but for an unbounded
    line (no clamping needed, since the object is allowed to slide past
    wherever the visible arrow currently happens to end). Used to project
    mouse movement onto a fixed drag axis.

    Args:
        line_point: A point the line passes through.
        line_dir: The line's direction (expected to already be a unit vector).
        ray_origin: Ray starting point.
        ray_dir: Ray direction.

    Returns:
        float: The line parameter `t` such that `line_point + line_dir * t`
        is the closest point on the line to the ray.
    """
    d1 = ray_dir
    d2 = line_dir
    r = ray_origin - line_point

    a = glm.dot(d1, d1)
    b = glm.dot(d1, d2)
    e = glm.dot(d2, d2)
    c = glm.dot(d1, r)
    f = glm.dot(d2, r)

    denom = a * e - b * b
    if abs(denom) < 1e-8:
        return 0.0

    s = (b * f - c * e) / denom
    return (b * s + f) / e


class Mover:
    """Tracks the move gizmo (3 colored arrows) for one selected SceneObject.

    The gizmo is always axis-aligned to world space, not the object's own
    rotation. Its position and size are derived live from the object's
    current position/scale and its mesh's cached bounding box, so it stays
    attached to the object as it moves instead of a fixed snapshot. Mover
    also owns hit-testing the mouse against its own arrows, and the drag
    state used to translate the object along a single axis.
    """

    def __init__(self, scene_object):
        """Create a gizmo attached to the given object.

        Args:
            scene_object: SceneObject the gizmo surrounds and will move.
        """
        self.scene_object = scene_object
        self.hovered_axis = None
        self.dragging_axis = None

    def world_center(self):
        """Where the object's bounding-box middle sits in world space right now."""
        obj = self.scene_object

        if obj.localMin is None:
            # No mesh bounds yet (e.g. mesh still loading) — fall back to the
            # object's raw position so the gizmo doesn't crash.
            return glm.vec3(*obj.position)

        local_center = (glm.vec3(*obj.localMin) + glm.vec3(*obj.localMax)) * 0.5
        return glm.vec3(*obj.position) + local_center * glm.vec3(*obj.scale)

    def half_extent(self):
        """How far the object's box reaches from its center, per world axis, right now."""
        obj = self.scene_object

        if obj.localMin is None:
            return glm.vec3(0.5, 0.5, 0.5)

        size = glm.vec3(*obj.localMax) - glm.vec3(*obj.localMin)
        return size * glm.vec3(*obj.scale) * 0.5

    def axis_endpoints(self, axis_index):
        """World-space start/end points of one arrow's shaft.

        Args:
            axis_index: Index into AXES (0=x, 1=y, 2=z).

        Returns:
            tuple[glm.vec3, glm.vec3]: The arrow's start and end points.
        """
        name, axis_dir, color = AXES[axis_index]

        center = self.world_center()
        extent = self.half_extent()
        reach = glm.dot(extent, axis_dir)

        start = center + axis_dir * (reach + ARROW_GAP)
        end = start + axis_dir * SHAFT_LENGTH
        return start, end

    def axis_segments(self):
        """All three arrows' (name, start, end, color) — used to build gizmo geometry."""
        return [
            (AXES[i][0], *self.axis_endpoints(i), AXES[i][2])
            for i in range(3)
        ]

    def build_render_data(self):
        """Build combined triangle data for all three arrows.

        Returns:
            tuple[numpy.ndarray, list]: A flat float32 vertex array ready for
            GPU upload, and a list of (name, color, start_vertex,
            vertex_count) tuples describing where each axis's triangles live
            within that array, so each one can be drawn with its own color.
        """
        all_points = []
        segments = []

        for i in range(3):
            name, axis_dir, color = AXES[i]
            start, _end = self.axis_endpoints(i)

            triangles = build_arrow_mesh(
                start, axis_dir,
                SHAFT_LENGTH, SHAFT_RADIUS,
                HEAD_LENGTH, HEAD_RADIUS,
            )

            # Record where this axis's triangles start in the combined list
            # before extending it, so renderer.py can issue one draw call
            # per axis out of a single shared buffer.
            start_vertex = len(all_points)
            all_points.extend(triangles)
            vertex_count = len(triangles)

            segments.append((name, color, start_vertex, vertex_count))

        return _flatten(all_points), segments

    def hit_test(self, ray_origin, ray_direction):
        """Find which arrow (if any) the given ray is touching.

        Args:
            ray_origin: Ray starting point (e.g. the camera position).
            ray_direction: Ray direction.

        Returns:
            str or None: The name of the closest arrow within PICK_RADIUS,
            or None if the ray isn't close enough to any of them.
        """
        best_axis = None
        best_distance = PICK_RADIUS

        for i in range(3):
            name, axis_dir, color = AXES[i]
            start, end = self.axis_endpoints(i)
            distance = ray_segment_distance(ray_origin, ray_direction, start, end)

            if distance < best_distance:
                best_axis = name
                best_distance = distance

        return best_axis

    def begin_drag(self, axis_name, ray_origin, ray_direction):
        """Start dragging the object along one axis.

        Freezes the object's current position and the gizmo's current
        center so later update_drag() calls have a fixed reference to
        measure movement against, instead of chasing the object as it moves.

        Args:
            axis_name: Name of the axis being dragged (as returned by hit_test).
            ray_origin: Current mouse ray origin.
            ray_direction: Current mouse ray direction.
        """
        self.dragging_axis = axis_name
        self._drag_axis_dir = AXES_BY_NAME[axis_name]
        self._drag_anchor = self.world_center()
        self._drag_start_position = glm.vec3(*self.scene_object.position)
        self._drag_t0 = closest_point_on_line_t(self._drag_anchor, self._drag_axis_dir, ray_origin, ray_direction)

    def update_drag(self, ray_origin, ray_direction):
        """Move the object to follow the mouse along the axis grabbed in begin_drag().

        Args:
            ray_origin: Current mouse ray origin.
            ray_direction: Current mouse ray direction.
        """
        t = closest_point_on_line_t(self._drag_anchor, self._drag_axis_dir, ray_origin, ray_direction)
        delta = t - self._drag_t0
        new_position = self._drag_start_position + self._drag_axis_dir * delta
        self.scene_object.setPosition(new_position.x, new_position.y, new_position.z)

    def end_drag(self):
        """Stop dragging and clear the temporary drag state."""
        self.dragging_axis = None
        self._drag_axis_dir = None
        self._drag_anchor = None
        self._drag_start_position = None
        self._drag_t0 = None
