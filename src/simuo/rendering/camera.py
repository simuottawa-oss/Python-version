"""Camera pose, projection settings, and mouse-ray unprojection."""

import math

import glm


class Camera:
    """Shared camera pose, projection settings, framing and picking rays."""

    def __init__(self):
        """Initialize the camera at a default viewing position.

        The camera starts facing down the negative Z axis with a standard world-up
        vector and recalculates its orientation vectors.
        """
        # Camera pose state.
        self.field_of_view = 60.0
        self.near_plane = 0.1
        self.far_plane = 1000.0
        self.position = glm.vec3(
            0.0,
            2.0,
            28.0
        )

        # Euler orientation state.
        self.yaw = -90.0
        self.pitch = 0.0

        # World reference vector used to rebuild the camera basis.
        self.world_up = glm.vec3(
            0.0,
            1.0,
            0.0
        )

        # Initial forward-facing direction.
        self.front = glm.vec3(
            0.0,
            0.0,
            -1.0
        )

        # Initial right-facing direction.
        self.right = glm.vec3(
            1.0,
            0.0,
            0.0
        )

        # Initial up-facing direction.
        self.up = glm.vec3(
            0.0,
            1.0,
            0.0
        )

        self.update_vectors()

    def update_vectors(self):
        """Recompute camera direction vectors from yaw and pitch.

        This updates the front, right, and up vectors used for movement and view
        matrix construction.
        """
        yaw = math.radians(
            self.yaw
        )

        pitch = math.radians(
            self.pitch
        )

        front = glm.vec3(
            math.cos(yaw)
            * math.cos(pitch),

            math.sin(pitch),

            math.sin(yaw)
            * math.cos(pitch),
        )

        # Refresh the camera basis vectors after orientation changes.
        self.front = glm.normalize(
            front
        )

        # Rebuild the right vector from the updated forward direction.
        self.right = glm.normalize(
            glm.cross(
                self.front,
                self.world_up
            )
        )

        # Rebuild the up vector from the updated basis.
        self.up = glm.normalize(
            glm.cross(
                self.right,
                self.front
            )
        )

    def rotate(
        self,
        dx,
        dy,
        sensitivity=0.12
    ):
        """Rotate the camera based on mouse movement.

        Args:
            dx: Horizontal mouse movement delta.
            dy: Vertical mouse movement delta.
            sensitivity: Mouse sensitivity multiplier.
        """
        # Apply mouse motion to the persistent yaw state.
        self.yaw += (
            dx * sensitivity
        )

        # Apply mouse motion to the persistent pitch state.
        self.pitch += (
            dy * sensitivity
        )

        # Keep pitch inside the safe range before rebuilding vectors.
        self.pitch = max(
            -89.0,
            min(
                89.0,
                self.pitch
            )
        )

        self.update_vectors()

    def look_at(self, target):
        """Aim at a target while preserving the current position."""
        direction = glm.vec3(*target)-self.position
        if glm.length(direction) == 0:
            return False
        direction = glm.normalize(direction)
        self.yaw = math.degrees(math.atan2(direction.z, direction.x))
        self.pitch = max(-89., min(89., math.degrees(math.asin(max(-1., min(1., direction.y))))))
        self.update_vectors()
        return True

    def frame_points(self, points, aspect, padding=1.15):
        """Fit world-space bounds to the view, preserving the view direction."""
        points = [glm.vec3(*point) for point in points]
        if not points:
            return False
        center = glm.vec3(*[(min(p[axis] for p in points)+max(p[axis] for p in points))/2 for axis in range(3)])
        vertical = math.tan(math.radians(self.field_of_view/2))
        horizontal = vertical*max(aspect, 1e-9)
        distance = self.near_plane
        depths = []
        for point in points:
            delta = point-center
            depth = glm.dot(delta, self.front)
            depths.append(depth)
            distance = max(distance, abs(glm.dot(delta, self.right))*padding/horizontal-depth,
                           abs(glm.dot(delta, self.up))*padding/vertical-depth, self.near_plane*2-depth)
        self.position = center-self.front*distance
        self.far_plane = max(self.far_plane, (distance+max(depths))*1.2)
        return True

    def view_matrix(self):
        """Build the OpenGL view matrix for the current camera orientation.

        Returns:
            glm.mat4: The camera view matrix used by the scene renderer.
        """
        return glm.lookAt(
            self.position,
            self.position
            + self.front,
            self.up,
        )

    def mouse_ray(self, event, width, height, projection, view):
        """Unproject logical widget coordinates into a normalized world-space ray."""
        x = 2.0 * event.position().x() / max(1, width) - 1.0
        y = 1.0 - 2.0 * event.position().y() / max(1, height)
        near = glm.inverse(projection * view) * glm.vec4(x, y, -1.0, 1.0)
        near /= near.w
        origin = glm.vec3(self.position)
        return origin, glm.normalize(glm.vec3(near) - origin)
