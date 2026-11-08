"""Crisp, DPI-independent gizmos and selection rectangles above the GL scene."""

import math

from PySide6.QtCore import QPointF, QRectF, Qt
from PySide6.QtGui import QColor, QPainter, QPen, QPolygonF
from PySide6.QtWidgets import QWidget


def polygon(points):
    return QPolygonF([QPointF(float(point[0]), float(point[1])) for point in points])


class InteractionOverlay(QWidget):
    def __init__(self, viewport):
        super().__init__(viewport)
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
        self.setAttribute(Qt.WidgetAttribute.WA_NoSystemBackground)
        self.setFocusPolicy(Qt.FocusPolicy.NoFocus)

    @property
    def viewport(self):
        return self.parentWidget()

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        gizmo = self.viewport.gizmo()
        active = self.viewport.drag.handle.key if self.viewport.drag is not None else self.viewport.hover_handle
        if gizmo is not None:
            for handle in gizmo.handles:
                color = QColor('#f5db7c' if handle.key == active else handle.color)
                painter.setPen(QPen(color, 3 if handle.key == active else 2))
                a, b = handle.points
                painter.drawLine(QPointF(*a), QPointF(*b))
                angle = math.atan2(*(b-a)[::-1])
                sides = [(b[0]-10*math.cos(angle+offset), b[1]-10*math.sin(angle+offset)) for offset in (-.45, .45)]
                painter.setBrush(color)
                painter.drawPolygon(polygon([b, *sides]))
                label = b+(b-a)/math.hypot(*(b-a))*11
                painter.drawText(QPointF(float(label[0]-4), float(label[1]+4)), handle.key.upper())
        rect = self.viewport.box_rect()
        if rect is not None:
            painter.setPen(QPen(QColor('#79baff'), 1, Qt.PenStyle.DashLine))
            painter.setBrush(QColor(70, 145, 225, 35))
            painter.drawRect(QRectF(rect[0], rect[1], rect[2]-rect[0], rect[3]-rect[1]))
        if self.viewport.drag is not None and self.viewport.drag.feedback:
            text = self.viewport.drag.feedback + '   ·   Esc cancels'
            box = painter.fontMetrics().boundingRect(text).adjusted(-8, -5, 8, 5)
            x, y = 12, self.height()-box.height()-12
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(QColor(30, 34, 40, 225))
            painter.drawRoundedRect(QRectF(x, y, box.width(), box.height()), 4, 4)
            painter.setPen(QColor('#e1e8f1'))
            painter.drawText(QPointF(x+8, y+box.height()-7), text)
        painter.end()
