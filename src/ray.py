import numpy as np


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
    
    def checkCollisions(self, ):
        """Checks collision with literally anything. ONLY CALL DURING LEFT MOUSE CLICK EVENTS"""
        pass

