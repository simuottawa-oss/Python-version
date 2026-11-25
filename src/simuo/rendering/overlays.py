"""Crisp, DPI-independent gizmos and selection rectangles above the GL scene."""

import math

from PySide6.QtCore import QPointF, QRectF, Qt
from PySide6.QtGui import QColor, QPainter, QPen, QPolygonF
from PySide6.QtWidgets import QWidget

from simuo.rendering.manipulation import MoveGizmo, RotateDrag, RotateGizmo, ScaleGizmo


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

    def _draw_move(self, painter, gizmo, active):
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

    def _draw_scale(self, painter, gizmo, active):
        for handle in gizmo.handles:
            color = QColor('#f5db7c' if handle.key == active else handle.color)
            painter.setPen(QPen(color, 3 if handle.key == active else 2))
            a, b = handle.points
            painter.drawLine(QPointF(*a), QPointF(*b))
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(color)
            radius = 6 if handle.key == active else 5
            painter.drawEllipse(QPointF(*b), radius, radius)
            painter.setPen(color)
            dx, dy = b[0]-a[0], b[1]-a[1]
            spread = math.hypot(dx, dy) or 1
            label = (b[0]+dx/spread*14, b[1]+dy/spread*14)
            painter.drawText(QPointF(float(label[0]-4), float(label[1]+4)), handle.key.upper())

    def _draw_rotate(self, painter, gizmo, active, drag):
        dragging_key = drag.handle.key if drag is not None else None
        for handle in gizmo.handles:
            if dragging_key is not None and handle.key != dragging_key:
                continue  # the other two handles hide until this drag ends
            hovered = handle.key == active
            color = QColor('#f5db7c' if hovered else handle.color)
            painter.setPen(QPen(color, 3 if hovered else 2))
            painter.setBrush(Qt.BrushStyle.NoBrush)
            painter.drawPolygon(polygon(handle.points))

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        gizmo = self.viewport.gizmo()
        active = self.viewport.drag.handle.key if self.viewport.drag is not None else self.viewport.hover_handle
        if isinstance(gizmo, MoveGizmo):
            self._draw_move(painter, gizmo, active)
        elif isinstance(gizmo, RotateGizmo):
            drag = self.viewport.drag if isinstance(self.viewport.drag, RotateDrag) else None
            self._draw_rotate(painter, gizmo, active, drag)
        elif isinstance(gizmo, ScaleGizmo):
            self._draw_scale(painter, gizmo, active)
        corners = self.viewport.origin_pick_corners()
        if corners:
            projection = self.viewport.projection()
            projected = {}
            for signs, world_point in corners:
                screen = projection.point(world_point)
                if screen is not None and -1 <= screen[2] <= 1:
                    projected[signs] = screen[:2]
            painter.setPen(QPen(QColor('#79baff'), 1, Qt.PenStyle.DashLine))
            for a_signs, a in projected.items():
                for axis in range(3):
                    b_signs = tuple(-s if i == axis else s for i, s in enumerate(a_signs))
                    b = projected.get(b_signs)
                    if b is not None and a_signs < b_signs:
                        painter.drawLine(QPointF(*a), QPointF(*b))
            painter.setPen(Qt.PenStyle.NoPen)
            for signs, point in projected.items():
                hovered = signs == self.viewport.hovered_corner
                painter.setBrush(QColor('#f5db7c' if hovered else '#79baff'))
                painter.drawEllipse(QPointF(*point), 6 if hovered else 5, 6 if hovered else 5)
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
