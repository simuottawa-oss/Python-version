"""Small vector icons shared by hierarchy rows and actions."""

from PySide6.QtCore import Qt
from PySide6.QtGui import QColor, QIcon, QPainter, QPainterPath, QPen, QPixmap


def outliner_icon(kind, active=True):
    """Small vector icons stay readable on both standard and Retina displays."""
    pixmap = QPixmap(40, 40)
    pixmap.fill(Qt.GlobalColor.transparent)
    painter = QPainter(pixmap)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing)
    painter.scale(2, 2)
    color = "#d1af71" if kind == "lock" and active else "#a9b3c0" if active else "#69717c"
    painter.setPen(QPen(QColor(color), 1.3))
    if kind == "mesh":
        for a, b in (((10, 2), (17, 6)), ((17, 6), (17, 14)), ((17, 14), (10, 18)),
                     ((10, 18), (3, 14)), ((3, 14), (3, 6)), ((3, 6), (10, 2)),
                     ((3, 6), (10, 10)), ((17, 6), (10, 10)), ((10, 10), (10, 18))):
            painter.drawLine(*a, *b)
    elif kind == "material":
        painter.drawEllipse(3, 3, 14, 14)
        painter.drawArc(6, 3, 8, 14, -90*16, 180*16)
        painter.drawLine(4, 13, 15, 5)
    elif kind == "results":
        painter.drawLine(3, 3, 3, 17)
        painter.drawLine(3, 17, 18, 17)
        painter.drawLine(5, 13, 9, 8)
        painter.drawLine(9, 8, 13, 11)
        painter.drawLine(13, 11, 17, 4)
    elif kind == "eye":
        path = QPainterPath()
        path.moveTo(2, 10)
        path.cubicTo(6, 3, 14, 3, 18, 10)
        path.cubicTo(14, 17, 6, 17, 2, 10)
        painter.drawPath(path)
        painter.drawEllipse(8, 8, 4, 4)
        if not active:
            painter.drawLine(3, 3, 17, 17)
    elif kind == "filter":
        path = QPainterPath()
        path.moveTo(2, 4)
        path.lineTo(18, 4)
        path.lineTo(12, 11)
        path.lineTo(12, 17)
        path.lineTo(8, 15)
        path.lineTo(8, 11)
        path.closeSubpath()
        painter.drawPath(path)
    elif kind == "isolate":
        for points in (((2, 7), (2, 2), (7, 2)), ((13, 2), (18, 2), (18, 7)),
                       ((18, 13), (18, 18), (13, 18)), ((7, 18), (2, 18), (2, 13))):
            painter.drawLine(*points[0], *points[1])
            painter.drawLine(*points[1], *points[2])
        painter.drawRoundedRect(7, 7, 6, 6, 1, 1)
    elif kind == "reveal":
        painter.drawLine(3, 4, 17, 4)
        painter.drawLine(10, 10, 17, 10)
        painter.drawLine(3, 16, 17, 16)
        painter.drawLine(2, 10, 7, 10)
        painter.drawLine(4, 7, 7, 10)
        painter.drawLine(4, 13, 7, 10)
    elif kind == "group_add":
        painter.drawRoundedRect(2, 5, 15, 12, 1.5, 1.5)
        painter.drawLine(4, 5, 4, 3)
        painter.drawLine(4, 3, 9, 3)
        painter.drawLine(9, 3, 11, 5)
        painter.drawLine(7, 11, 13, 11)
        painter.drawLine(10, 8, 10, 14)
    elif kind == "lock":
        painter.drawRoundedRect(5, 9, 10, 8, 1.5, 1.5)
        path = QPainterPath()
        path.moveTo(7, 9)
        path.lineTo(7, 6)
        path.cubicTo(7, 2, 13, 2, 13, 6)
        path.lineTo(13, 9 if active else 5)
        painter.drawPath(path)
    else:
        painter.drawRoundedRect(2, 5, 16, 12, 1.5, 1.5)
        painter.drawLine(4, 5, 4, 3)
        painter.drawLine(4, 3, 10, 3)
        painter.drawLine(10, 3, 12, 5)
    painter.end()
    pixmap.setDevicePixelRatio(2)
    return QIcon(pixmap)
