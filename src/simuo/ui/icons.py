"""Vector tool icons drawn with QPainter, so the editors never need image assets.

Every icon is rendered on a 24 by 24 transparent square with a light monotone
stroke that matches the dark editor theme. Set ``Qt.ToolButtonIconOnly`` and
an icon size of 24 pixels on the toolbar for a clean header row.
"""
import math

from PySide6.QtCore import QPointF, QRectF, Qt
from PySide6.QtGui import QColor, QIcon, QPainter, QPainterPath, QPen, QPixmap

_SIZE = 24
_COLOR = "#e8e8e8"


def _icon(draw):
    """Render a 24 pixel transparent icon from a painter callback.

    Args:
        draw (callable): Function receiving the configured painter to stroke art.

    Returns:
        QIcon: Icon built from the rendered pixmap.
    """
    pixmap = QPixmap(_SIZE, _SIZE)
    pixmap.fill(Qt.GlobalColor.transparent)
    painter = QPainter(pixmap)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing)
    pen = QPen(QColor(_COLOR))
    pen.setWidthF(1.8)
    pen.setCapStyle(Qt.PenCapStyle.RoundCap)
    pen.setJoinStyle(Qt.PenJoinStyle.RoundJoin)
    painter.setPen(pen)
    painter.setBrush(Qt.BrushStyle.NoBrush)
    draw(painter)
    painter.end()
    return QIcon(pixmap)


def _polyline(painter, points, close=False):
    """Stroke a polyline through the given screen-space points.

    Args:
        painter (QPainter): Target painter.
        points (sequence): (x, y) tuples in icon pixels.
        close (bool): Connect the last point back to the first.

    Returns:
        None. Draws onto the painter.
    """
    path = QPainterPath(QPointF(points[0][0], points[0][1]))
    for x, y in points[1:]:
        path.lineTo(x, y)
    if close:
        path.closeSubpath()
    painter.drawPath(path)


def _dot(painter, x, y, radius=2.0):
    """Fill a small circular endpoint marker.

    Args:
        painter (QPainter): Target painter.
        x (float): Marker center x in icon pixels.
        y (float): Marker center y in icon pixels.
        radius (float): Marker radius.

    Returns:
        None. Draws onto the painter.
    """
    painter.setBrush(QColor(_COLOR))
    painter.drawEllipse(QPointF(x, y), radius, radius)
    painter.setBrush(Qt.BrushStyle.NoBrush)


def _ellipse_arc(painter, cx, cy, rx, ry, start_deg, end_deg, samples=36):
    """Stroke a sampled elliptical arc using standard math angles.

    Args:
        painter (QPainter): Target painter.
        cx (float): Ellipse center x in icon pixels.
        cy (float): Ellipse center y in icon pixels.
        rx (float): Horizontal radius.
        ry (float): Vertical radius.
        start_deg (float): Start angle in degrees, 0 at the right, 90 at the top.
        end_deg (float): End angle in degrees; the arc sweeps across that range.
        samples (int): Polyline resolution.

    Returns:
        None. Draws onto the painter.
    """
    points = []
    for i in range(samples + 1):
        angle = math.radians(start_deg + (end_deg - start_deg) * i / samples)
        points.append(QPointF(cx + rx * math.cos(angle), cy - ry * math.sin(angle)))
    path = QPainterPath(points[0])
    for point in points[1:]:
        path.lineTo(point)
    painter.drawPath(path)


def line_icon():
    """Icon of a diagonal segment with endpoint dots for drawing lines.

    Returns:
        QIcon: Line tool icon.
    """
    def draw(painter):
        _polyline(painter, [(5, 19), (19, 5)])
        _dot(painter, 5, 19)
        _dot(painter, 19, 5)
    return _icon(draw)


def arc_icon():
    """Icon of an open arc with endpoint dots for three-point arcs.

    Returns:
        QIcon: Arc tool icon.
    """
    def draw(painter):
        _ellipse_arc(painter, 12, 15, 8.5, 8.5, 180, 0)
        _dot(painter, 3.5, 15)
        _dot(painter, 20.5, 15)
    return _icon(draw)


def circle_icon():
    """Icon of a circle with a center dot for circle drawing.

    Returns:
        QIcon: Circle tool icon.
    """
    def draw(painter):
        painter.drawEllipse(QRectF(4, 4, 16, 16))
        _dot(painter, 12, 12, 1.6)
    return _icon(draw)


def select_icon():
    """Filled pointer cursor icon for selection mode.

    Returns:
        QIcon: Selection tool icon.
    """
    def draw(painter):
        painter.setBrush(QColor(_COLOR))
        points = [
            QPointF(6, 3), QPointF(6, 17.5), QPointF(9.5, 14.5), QPointF(11.8, 19.5),
            QPointF(14.2, 18.5), QPointF(11.9, 13.5), QPointF(16.5, 13.5),
        ]
        path = QPainterPath(points[0])
        for point in points[1:]:
            path.lineTo(point)
        path.closeSubpath()
        painter.drawPath(path)
        painter.setBrush(Qt.BrushStyle.NoBrush)
    return _icon(draw)


def close_outline_icon():
    """Icon of a closed polygon with a join dot for closing a sketch face.

    Returns:
        QIcon: Close outline tool icon.
    """
    def draw(painter):
        painter.setBrush(QColor(232, 232, 232, 55))
        points = [(5, 17), (8, 7), (16, 7), (19, 17)]
        path = QPainterPath(QPointF(*points[0]))
        for x, y in points[1:]:
            path.lineTo(x, y)
        path.closeSubpath()
        painter.drawPath(path)
        painter.setBrush(Qt.BrushStyle.NoBrush)
        _dot(painter, 5, 17)
    return _icon(draw)


def dimension_icon():
    """Icon of a dimension line with arrowheads and extension ticks.

    Returns:
        QIcon: Dimension tool icon.
    """
    def draw(painter):
        _polyline(painter, [(7, 8), (7, 16)])
        _polyline(painter, [(17, 8), (17, 16)])
        _polyline(painter, [(7, 12), (17, 12)])
        _polyline(painter, [(10, 10.4), (7, 12), (10, 13.6)])
        _polyline(painter, [(14, 10.4), (17, 12), (14, 13.6)])
    return _icon(draw)


def frame_icon():
    """Icon of corner brackets for framing the sketch in the viewport.

    Returns:
        QIcon: Frame tool icon.
    """
    def draw(painter):
        _polyline(painter, [(5, 10), (5, 5), (10, 5)])
        _polyline(painter, [(14, 5), (19, 5), (19, 10)])
        _polyline(painter, [(19, 14), (19, 19), (14, 19)])
        _polyline(painter, [(10, 19), (5, 19), (5, 14)])
    return _icon(draw)


def model_3d_icon():
    """Wireframe cube icon for switching to the 3D model view.

    Returns:
        QIcon: 3D view tool icon.
    """
    def draw(painter):
        _polyline(painter, [(5, 10), (15, 10), (15, 20), (5, 20)], close=True)
        _polyline(painter, [(5, 10), (9, 6)])
        _polyline(painter, [(15, 10), (19, 6)])
        _polyline(painter, [(15, 20), (19, 16)])
        _polyline(painter, [(9, 6), (19, 6)])
        _polyline(painter, [(19, 6), (19, 16)])
    return _icon(draw)


def new_sketch_icon():
    """Dashed plane square with a sketch stroke for starting a new sketch.

    Returns:
        QIcon: New sketch tool icon.
    """
    def draw(painter):
        dash = QPen(painter.pen())
        dash.setStyle(Qt.PenStyle.DashLine)
        dash.setDashPattern([4.0, 3.0])
        painter.setPen(dash)
        painter.drawRect(QRectF(5, 5, 14, 14))
        painter.setPen(QPen(QColor(_COLOR), dash.widthF(), Qt.PenStyle.SolidLine,
                            Qt.PenCapStyle.RoundCap, Qt.PenJoinStyle.RoundJoin))
        _polyline(painter, [(8, 14.5), (11, 9.5), (16, 13.5)])
    return _icon(draw)


def extrude_icon():
    """Icon of a prism between two ellipse levels for extruding a sketch.

    Returns:
        QIcon: Extrude tool icon.
    """
    def draw(painter):
        _ellipse_arc(painter, 12, 6.5, 6.5, 2.2, 0, 360)
        _ellipse_arc(painter, 12, 17.5, 6.5, 2.2, 180, 360)
        _polyline(painter, [(5.5, 6.5), (5.5, 17.5)])
        _polyline(painter, [(18.5, 6.5), (18.5, 17.5)])
    return _icon(draw)


def finish_icon():
    """Check mark icon for finishing the current sketch.

    Returns:
        QIcon: Finish sketch tool icon.
    """
    def draw(painter):
        pen = QPen(painter.pen())
        pen.setWidthF(2.4)
        painter.setPen(pen)
        _polyline(painter, [(5, 13), (10, 17.5), (19, 6.5)])
    return _icon(draw)


def pencil_icon():
    """Pencil icon for re-editing an existing sketch.

    Returns:
        QIcon: Edit sketch tool icon.
    """
    def draw(painter):
        _polyline(painter, [(6, 18), (16, 8), (19, 11), (9, 20)], close=True)
        painter.setBrush(QColor(_COLOR))
        tip = [QPointF(6, 18), QPointF(5.7, 20.8), QPointF(9, 20)]
        path = QPainterPath(tip[0])
        for point in tip[1:]:
            path.lineTo(point)
        path.closeSubpath()
        painter.drawPath(path)
        painter.setBrush(Qt.BrushStyle.NoBrush)
    return _icon(draw)
