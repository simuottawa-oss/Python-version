"""Engine-independent transforms using the scene editor's coordinate convention."""

import numpy as np


def rotation_matrix(rotation):
    """Return a 3x3 Rx * Ry * Rz matrix for scene Euler angles in degrees.

    Multiply column vectors by this matrix, or row vertices by its transpose,
    matching the viewport's X, Y, then Z model-matrix rotations.
    """
    x, y, z = np.radians(rotation)
    sx, sy, sz = np.sin([x, y, z])
    cx, cy, cz = np.cos([x, y, z])
    return np.array([
        [cy*cz, -cy*sz, sy],
        [cx*sz + sx*sy*cz, cx*cz - sx*sy*sz, -sx*cy],
        [sx*sz - cx*sy*cz, sx*cz + cx*sy*sz, cx*cy],
    ])
