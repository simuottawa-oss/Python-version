"""Generated reference geometry for the viewport."""

import numpy as np


def create_axis_lines(
    minimum=-2000,
    maximum=2000
    ,
    tickSize=0.15
):
    """Generate axis and tick line geometry for the scene reference grid.

    Args:
        minimum: Minimum axis coordinate value.
        maximum: Maximum axis coordinate value.
        tickSize: Half-length of each axis tick mark.

    Returns:
        numpy.ndarray: Float32 vertex array containing line segments for X, Y,
        and Z axes.
    """
    vertices = []

    # -------------------------------------------------
    # MAIN X AXIS
    # -------------------------------------------------

    vertices.extend([
        minimum, 0.0, 0.0,
        maximum, 0.0, 0.0
    ])

    # X ticks
    for x in range(
        minimum,
        maximum + 1
    ):
        vertices.extend([
            x, -tickSize, 0.0,
            x, tickSize, 0.0
        ])

    # -------------------------------------------------
    # MAIN Y AXIS
    # -------------------------------------------------

    vertices.extend([
        0.0, minimum, 0.0,
        0.0, maximum, 0.0
    ])

    # Y ticks
    for y in range(
        minimum,
        maximum + 1
    ):
        vertices.extend([
            -tickSize, y, 0.0,
            tickSize, y, 0.0
        ])

    # -------------------------------------------------
    # MAIN Z AXIS
    # -------------------------------------------------

    vertices.extend([
        0.0, 0.0, minimum,
        0.0, 0.0, maximum
    ])

    # Z ticks
    for z in range(
        minimum,
        maximum + 1
    ):
        vertices.extend([
            -tickSize, 0.0, z,
            tickSize, 0.0, z
        ])

    return np.array(
        vertices,
        dtype=np.float32
    )
