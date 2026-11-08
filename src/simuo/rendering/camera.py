"""Camera pose, projection settings, and mouse-ray unprojection."""

import math

import glm


class Camera:
    """Represents the viewer's position and orientation in the 3D scene. Only tracks position and orientation."""

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
