"""Structural surface selection, volume-mesh preview and stress lookup texture."""
import math
import numpy as np
from PySide6.QtCore import Qt, Signal, QRectF, QPointF, QTimer, QElapsedTimer
from PySide6.QtGui import QMatrix4x4, QVector3D, QPainter, QColor, QLinearGradient, QPen, QCursor, QPolygonF
from PySide6.QtOpenGLWidgets import QOpenGLWidget
from PySide6.QtWidgets import QWidget
import glm
from simuo.rendering.camera import Camera

from simuo.structural.postprocessing import gradient_texture

VERTEX = """
#version 330 core
layout(location=0) in vec3 position;
layout(location=1) in vec3 color;
layout(location=2) in float stress;
uniform mat4 mvp;
out vec3 tint;
out float field;
void main() { gl_Position=mvp*vec4(position,1); tint=color; field=stress; }
"""
FRAGMENT = """
#version 330 core
in vec3 tint;
in float field;
uniform sampler2D stress_gradient;
uniform bool show_stress;
out vec4 output_color;
void main() {
    float coordinate=(clamp(field,0.,1.)*256.+0.5)/257.;
    output_color=vec4(show_stress ? texture(stress_gradient,vec2(coordinate,.5)).rgb : tint,1);
}
"""


class StructuralOverlay(QWidget):
    """Use the Scene editor's transparent overlay pattern for arrows and legends."""
    def __init__(self, viewport):
        super().__init__(viewport)
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
        self.setAttribute(Qt.WidgetAttribute.WA_NoSystemBackground)
        self.setFocusPolicy(Qt.FocusPolicy.NoFocus)

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        self.parentWidget().paint_overlay(painter)
        painter.end()


class StructuralViewport(QOpenGLWidget):
    patch_clicked = Signal(int, bool)
    point_picked = Signal(int, object)
    load_picked = Signal(str)
    support_picked = Signal(str)
    placement_cancelled = Signal()
    frame_requested = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setMinimumSize(400, 320)
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        from simuo.ui.camera_keys import VerticalNavigationFilter
        self.vertical_navigation = VerticalNavigationFilter(self)
        self.setMouseTracking(True)
        self.camera = Camera()
        self.camera.near_plane = .01
        self.camera.far_plane = 100.
        self.tool = "select"
        self.keys = set()
        self.right_mouse = False
        self.point_loads = ()
        self.point_supports = ()
        self.pinned_faces = set()
        self.selected_support = None
        self.display_maximum = None
        self.saturated = 0
        self.surface_loads = ()
        self.draft_surface_load = None
        self.selected_load = None
        self.draft_point = self.hover_point = None
        self.preview_force = (0., 0., 0.)
        self.tool_rail = self.tool_context = None
        self.navigation = QTimer(self)
        self.navigation.timeout.connect(self.navigate)
        self.navigation.start(16)
        self.geometry = self.mesh = self.result = None
        self.patches = ()
        self.selected = set()
        self.supports, self.loads = set(), set()
        self.display = "Setup"
        self.yaw, self.pitch, self.distance = -35., 25., 3.5
        self.last_mouse = None
        self.dirty = True
        self.program = self.vao = self.vbo = self.texture = None
        self.draw_count = 0
        self.maximum = 0.
        self.triangles = np.empty((0, 3, 3))
        self.triangle_patch = np.empty(0, dtype=int)
        self.line_count = 0
        self.overlay = StructuralOverlay(self)
        self.overlay.setGeometry(self.rect())
        self.frame_all()

    def set_data(self, geometry, patches, mesh=None, result=None):
        self.geometry, self.patches, self.mesh, self.result = geometry, patches, mesh, result
        self.refresh()

    def refresh(self):
        self.dirty = True
        self.update()

    def initializeGL(self):
        from OpenGL.GL import glGenVertexArrays, glGenBuffers, glGenTextures, glBindTexture, glTexImage2D, glTexParameteri, glPixelStorei
        from OpenGL.GL import GL_TEXTURE_2D, GL_RGB8, GL_RGB, GL_UNSIGNED_BYTE, GL_TEXTURE_MIN_FILTER, GL_TEXTURE_MAG_FILTER, GL_LINEAR, GL_TEXTURE_WRAP_S, GL_TEXTURE_WRAP_T, GL_CLAMP_TO_EDGE, GL_UNPACK_ALIGNMENT
        from OpenGL.GL.shaders import compileProgram, compileShader
        from OpenGL.GL import GL_VERTEX_SHADER, GL_FRAGMENT_SHADER
        self.program = compileProgram(compileShader(VERTEX, GL_VERTEX_SHADER), compileShader(FRAGMENT, GL_FRAGMENT_SHADER))
        self.vao, self.vbo, self.texture = glGenVertexArrays(1), glGenBuffers(1), glGenTextures(1)
        glBindTexture(GL_TEXTURE_2D, self.texture)
        glPixelStorei(GL_UNPACK_ALIGNMENT, 1)
        glTexImage2D(GL_TEXTURE_2D, 0, GL_RGB8, 257, 1, 0, GL_RGB, GL_UNSIGNED_BYTE, gradient_texture())
        for parameter in (GL_TEXTURE_MIN_FILTER, GL_TEXTURE_MAG_FILTER):
            glTexParameteri(GL_TEXTURE_2D, parameter, GL_LINEAR)
        for parameter in (GL_TEXTURE_WRAP_S, GL_TEXTURE_WRAP_T):
            glTexParameteri(GL_TEXTURE_2D, parameter, GL_CLAMP_TO_EDGE)
        self.context().aboutToBeDestroyed.connect(self.cleanup)

    def cleanup(self):
        if self.program is None:
            return
        from OpenGL.GL import glDeleteBuffers, glDeleteVertexArrays, glDeleteTextures, glDeleteProgram
        self.makeCurrent()
        glDeleteBuffers(1, [self.vbo])
        glDeleteVertexArrays(1, [self.vao])
        glDeleteTextures([self.texture])
        glDeleteProgram(self.program)
        self.program = None
        self.doneCurrent()

    def matrices(self):
        projection = QMatrix4x4()
        projection.perspective(self.camera.field_of_view, max(1, self.width())/max(1, self.height()),
                               self.camera.near_plane, self.camera.far_plane)
        view = QMatrix4x4()
        view.lookAt(QVector3D(*self.camera.position), QVector3D(*(self.camera.position+self.camera.front)), QVector3D(*self.camera.up))
        return projection*view

    def set_tool(self, tool):
        self.tool = tool
        self.hover_point = None
        self.setCursor(Qt.CursorShape.CrossCursor if tool in ("point", "fixed_point") else Qt.CursorShape.ArrowCursor)
        self.update()

    def frame_all(self):
        self.camera.position = glm.vec3(2.2, 1.5, 3.)
        direction = glm.normalize(-self.camera.position)
        self.camera.yaw = math.degrees(math.atan2(direction.z, direction.x))
        self.camera.pitch = math.degrees(math.asin(direction.y))
        self.camera.update_vectors()
        self.update()

    def normalized(self, points):
        if self.geometry is None:
            return np.asarray(points)
        g = self.geometry
        center = (g.points.min(axis=0)+g.points.max(axis=0))/2
        return (np.asarray(points)-center)/max(np.linalg.norm(g.dimensions)/2, 1e-12)

    def frame_point(self, point):
        target = self.normalized(point)
        self.camera.position = glm.vec3(*target)-self.camera.front*1.5
        self.update()

    def layout_tools(self):
        if hasattr(self, "overlay"):
            self.overlay.setGeometry(self.rect())
            self.overlay.raise_()
        if self.tool_context is not None:
            self.tool_context.adjustSize()
            self.tool_context.move(8, 8)
            self.tool_context.raise_()
        if self.tool_rail is not None:
            self.tool_rail.adjustSize()
            self.tool_rail.move(8, self.tool_context.height()+16 if self.tool_context else 8)
            self.tool_rail.raise_()

    def resizeGL(self, width, height):
        from OpenGL.GL import glViewport
        ratio = self.devicePixelRatioF()
        glViewport(0, 0, round(width*ratio), round(height*ratio))

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self.layout_tools()

    def navigate(self):
        if not self.keys or not self.hasFocus():
            return
        delta = glm.vec3(0.)
        for key, vector in ((Qt.Key.Key_W, self.camera.front), (Qt.Key.Key_S, -self.camera.front),
                            (Qt.Key.Key_D, self.camera.right), (Qt.Key.Key_A, -self.camera.right),
                            (Qt.Key.Key_Space, self.camera.world_up), (Qt.Key.Key_Alt, -self.camera.world_up)):
            if key in self.keys:
                delta += vector
        self.camera.position += delta*.035
        self.update()

    def upload(self):
        import ctypes
        from OpenGL.GL import glBindVertexArray, glBindBuffer, glBufferData, glEnableVertexAttribArray, glVertexAttribPointer, GL_ARRAY_BUFFER, GL_STATIC_DRAW, GL_FLOAT
        if self.geometry is None:
            self.draw_count = 0
            self.line_count = 0
            self.triangles = np.empty((0, 3, 3))
            return
        g = self.geometry
        center = (g.points.min(axis=0)+g.points.max(axis=0))/2
        radius = max(np.linalg.norm(g.dimensions)/2, 1e-12)
        if self.display != "Setup" and self.mesh is not None:
            triangles = self.mesh.points[self.mesh.boundary_triangles]
            triangle_patch = self.mesh.boundary_patch
        else:
            triangles = g.points[g.triangles]
            triangle_patch = np.empty(len(triangles), dtype=int)
            for i, patch in enumerate(self.patches):
                triangle_patch[list(patch.triangles)] = i
        self.triangles = (triangles-center)/radius
        self.triangle_patch = triangle_patch
        colors = np.tile([.64, .7, .78], (len(triangles), 3, 1))
        for i, patch in enumerate(self.patches):
            source = set(patch.triangles)
            color = None
            if source & self.supports:
                color = (.2, .45, 1.)
            if source & self.pinned_faces:
                color = (.65, .45, 1.)
            if source & self.loads:
                color = (1., .55, .15)
            if i in self.selected:
                color = (.1, .95, .95)
            if color:
                colors[triangle_patch == i] = color
        values = np.zeros((len(triangles), 3))
        self.maximum = 0.
        if self.display == "Stress" and self.result is not None and self.mesh is not None:
            raw = self.result.averaged_von_mises
            self.maximum = self.display_maximum or float(raw.max())
            field = np.clip(raw/max(self.maximum, 1e-30), 0., 1.)
            self.saturated = int(np.count_nonzero(raw > self.maximum))
            values = field[self.mesh.boundary_triangles]
        data = np.concatenate((self.triangles, colors, values[:, :, None]), axis=2).astype(np.float32)
        line_data = []
        floor = float(self.normalized(g.points).min(axis=0)[1])
        for value in np.linspace(-2, 2, 17):
            for point in ((value, floor, -2), (value, floor, 2), (-2, floor, value), (2, floor, value)):
                line_data.append((*point, .20, .20, .20, 0.))
        self.line_count = len(line_data)
        triangles_data = data.reshape(-1, 7)
        data = np.vstack((triangles_data, np.asarray(line_data, dtype=np.float32)))
        glBindVertexArray(self.vao)
        glBindBuffer(GL_ARRAY_BUFFER, self.vbo)
        glBufferData(GL_ARRAY_BUFFER, data.nbytes, data, GL_STATIC_DRAW)
        for location, count, offset in ((0, 3, 0), (1, 3, 12), (2, 1, 24)):
            glEnableVertexAttribArray(location)
            glVertexAttribPointer(location, count, GL_FLOAT, False, 28, ctypes.c_void_p(offset))
        self.draw_count = len(triangles_data)

    def paintGL(self):
        from OpenGL.GL import glClearColor, glClear, glEnable, glDisable, glUseProgram, glUniformMatrix4fv, glGetUniformLocation, glUniform1i, glBindVertexArray, glDrawArrays, glBindTexture, glPolygonMode, glActiveTexture
        from OpenGL.GL import GL_COLOR_BUFFER_BIT, GL_DEPTH_BUFFER_BIT, GL_DEPTH_TEST, GL_TEXTURE_2D, GL_TRIANGLES, GL_FRONT_AND_BACK, GL_LINE, GL_FILL, GL_TEXTURE0, GL_LINES, GL_BLEND, GL_SCISSOR_TEST, glColorMask, glDepthMask
        # QPainter changes GL state for its text overlay. Restore opaque mesh
        # rendering each frame so lookup colors retain their exact endpoints.
        glDisable(GL_BLEND)
        glDisable(GL_SCISSOR_TEST)
        glColorMask(True, True, True, True)
        glDepthMask(True)
        glClearColor(.075, .09, .12, 1.)
        glClear(GL_COLOR_BUFFER_BIT | GL_DEPTH_BUFFER_BIT)
        if self.dirty:
            self.upload()
            self.dirty = False
        if self.draw_count:
            glEnable(GL_DEPTH_TEST)
            glUseProgram(self.program)
            matrix = np.asarray(self.matrices().data(), dtype=np.float32)
            glUniformMatrix4fv(glGetUniformLocation(self.program, "mvp"), 1, False, matrix)
            glUniform1i(glGetUniformLocation(self.program, "show_stress"), False)
            glUniform1i(glGetUniformLocation(self.program, "stress_gradient"), 0)
            glActiveTexture(GL_TEXTURE0)
            glBindTexture(GL_TEXTURE_2D, self.texture)
            glBindVertexArray(self.vao)
            glDrawArrays(GL_LINES, self.draw_count, self.line_count)
            glUniform1i(glGetUniformLocation(self.program, "show_stress"), self.display == "Stress" and self.result is not None)
            glPolygonMode(GL_FRONT_AND_BACK, GL_LINE if self.display == "Mesh" else GL_FILL)
            glDrawArrays(GL_TRIANGLES, 0, self.draw_count)
            glPolygonMode(GL_FRONT_AND_BACK, GL_FILL)
            glBindVertexArray(0)
            glUseProgram(0)
            glDisable(GL_DEPTH_TEST)
        self.overlay.update()

    def paint_overlay(self, painter):
        painter.setPen(QColor("white"))
        painter.drawText(14, self.height()-10, "Left-click selects · Ctrl adds faces · Right-drag looks · WASD moves · Space/Alt up/down · F frames")
        self.paint_loads(painter)
        painter.setPen(QColor("white"))
        if self.display == "Stress" and self.result is not None:
            x, y = 20, self.height()-85
            gradient = QLinearGradient(x, y, x+250, y)
            for position, color in ((0., "#00ff00"), (.5, "#ffff00"), (1., "#ff0000")):
                gradient.setColorAt(position, QColor(color))
            painter.fillRect(QRectF(x, y, 250, 16), gradient)
            painter.drawText(x, y-9, "Averaged von Mises stress (Pa)")
            painter.drawText(x, y+33, f"0              {self.maximum/2:.4g}              {self.maximum:.4g}{' + saturated' if self.saturated else ''}")
            painter.drawText(x, y+52, f"Unaveraged peak: {self.result.von_mises.max():.6g} Pa")

    def project_point(self, physical_point):
        return self.project_normalized(self.normalized(physical_point))

    def project_normalized(self, point):
        point = self.matrices().map(QVector3D(*point))
        if not -1 <= point.z() <= 1:
            return None
        return np.array([(point.x()+1)*self.width()/2, (1-point.y())*self.height()/2])

    def arrow(self, painter, point, direction, color, label=""):
        start = self.project_point(point)
        length = np.linalg.norm(direction)
        if start is None:
            return
        painter.setPen(QPen(QColor(color), 2))
        painter.setBrush(QColor(color))
        painter.drawEllipse(QRectF(start[0]-4, start[1]-4, 8, 8))
        if length > 0:
            end = self.project_normalized(self.normalized(point)+np.asarray(direction)/length*.28)
            if end is not None:
                delta = end-start
                if np.linalg.norm(delta) > 1:
                    delta = delta/np.linalg.norm(delta)
                    side = np.array([-delta[1], delta[0]])
                    painter.drawLine(int(start[0]), int(start[1]), int(end[0]), int(end[1]))
                    for vertex in (end-delta*9+side*4, end-delta*9-side*4):
                        painter.drawLine(int(end[0]), int(end[1]), int(vertex[0]), int(vertex[1]))
        if label:
            painter.drawText(int(start[0])+8, int(start[1])-8, label)

    def paint_loads(self, painter):
        if self.geometry is None:
            return
        from simuo.structural.meshing import point_position
        for support in self.point_supports:
            point = point_position(self.geometry, support)
            screen = self.project_point(point)
            if screen is not None and self.visible_point(point):
                painter.setPen(QPen(QColor("#78e4de" if support.identifier == self.selected_support else "#68a4ff"), 2))
                painter.drawEllipse(QPointF(*screen), 6, 6)
                painter.drawText(QPointF(*(screen+np.array([10, -8]))), support.name)
        for load in self.point_loads:
            point = point_position(self.geometry, load)
            if self.visible_point(point):
                self.arrow(painter, point, load.force, "#f0bcc8" if load.identifier == self.selected_load else "#ffad57", load.name)
        if self.draft_point is not None:
            self.arrow(painter, self.draft_point, self.preview_force, "#78e4de", "Point force preview")
        elif self.hover_point is not None:
            self.arrow(painter, self.hover_point, (0, 0, 0), "#78e4de")
        for load in (*self.surface_loads, *((self.draft_surface_load,) if self.draft_surface_load is not None else ())):
            indices = load.triangles
            for index in indices[::max(1, math.ceil(len(indices)/8))]:
                triangle = self.geometry.points[self.geometry.triangles[index]]
                point = triangle.mean(axis=0)
                if not self.visible_point(point):
                    continue
                if load.kind == "pressure":
                    normal = np.cross(triangle[1]-triangle[0], triangle[2]-triangle[0])
                    direction = -normal*(1 if load.value[0] >= 0 else -1)
                else:
                    direction = load.value
                self.arrow(painter, point, direction, "#78e4de" if load.identifier == "draft" else "#f0bcc8" if load.identifier == self.selected_load else "#ffad57")

    def visible_point(self, point):
        screen = self.project_point(point)
        if screen is None:
            return False
        hit = self.pick_surface(*screen)
        return hit is not None and np.linalg.norm(hit[2]-point) <= np.linalg.norm(self.geometry.dimensions)*2e-5

    def pick_surface(self, x, y):
        if self.geometry is None:
            return None
        inverse, valid = self.matrices().inverted()
        if not valid:
            return None
        nx = 2*x/max(self.width(), 1)-1
        ny = 1-2*y/max(self.height(), 1)
        a, b = (inverse.map(QVector3D(nx, ny, z)) for z in (-1., 1.))
        origin = np.array(a.toTuple())
        direction = np.array(b.toTuple())-origin
        source = self.geometry.points[self.geometry.triangles]
        triangles = self.normalized(source)
        edge1, edge2 = triangles[:, 1]-triangles[:, 0], triangles[:, 2]-triangles[:, 0]
        h = np.cross(direction, edge2)
        determinant = np.einsum("ij,ij->i", edge1, h)
        safe = np.abs(determinant) > 1e-12
        inv = np.divide(1., determinant, out=np.zeros_like(determinant), where=safe)
        offset = origin-triangles[:, 0]
        u = inv*np.einsum("ij,ij->i", offset, h)
        q = np.cross(offset, edge1)
        v = inv*(q@direction)
        distance = inv*np.einsum("ij,ij->i", edge2, q)
        hit = safe & (u >= -1e-8) & (v >= -1e-8) & (u+v <= 1+1e-8) & (distance > 0)
        if not hit.any():
            return None
        index = int(np.argmin(np.where(hit, distance, np.inf)))
        bary = np.maximum(np.array([1-u[index]-v[index], u[index], v[index]]), 0.)
        bary /= bary.sum()
        return index, tuple(bary), bary@source[index]

    def mousePressEvent(self, event):
        self.setFocus()
        self.last_mouse = self.press_mouse = event.position()
        if event.button() == Qt.MouseButton.RightButton:
            self.right_mouse = True
            self.setCursor(Qt.CursorShape.BlankCursor)

    def mouseMoveEvent(self, event):
        if self.right_mouse and self.last_mouse is not None:
            delta = event.position()-self.last_mouse
            self.camera.rotate(delta.x(), -delta.y(), .25)
            self.last_mouse = event.position()
            self.update()
        elif self.tool in ("point", "fixed_point"):
            hit = self.pick_surface(event.position().x(), event.position().y())
            self.hover_point = hit[2] if hit else None
            self.update()

    def mouseReleaseEvent(self, event):
        if event.button() == Qt.MouseButton.RightButton:
            self.right_mouse = False
            self.setCursor(Qt.CursorShape.CrossCursor if self.tool in ("point", "fixed_point") else Qt.CursorShape.ArrowCursor)
            return
        if event.button() != Qt.MouseButton.LeftButton or self.last_mouse is None:
            return
        moved = (event.position()-self.press_mouse).manhattanLength()
        self.last_mouse = None
        if moved > 4:
            return
        if self.tool == "select" and self.geometry:
            from simuo.structural.meshing import point_position
            for support in reversed(self.point_supports):
                point = point_position(self.geometry, support)
                screen = self.project_point(point)
                if screen is not None and np.linalg.norm(screen-np.array(event.position().toTuple())) < 12 and self.visible_point(point):
                    self.support_picked.emit(support.identifier)
                    return
            for load in reversed(self.point_loads):
                point = point_position(self.geometry, load)
                screen = self.project_point(point)
                if screen is not None and np.linalg.norm(screen-np.array(event.position().toTuple())) < 12 and self.visible_point(point):
                    self.load_picked.emit(load.identifier)
                    return
        hit = self.pick_surface(event.position().x(), event.position().y())
        if hit is None:
            return
        index, bary, point = hit
        if self.tool in ("point", "fixed_point"):
            self.point_picked.emit(index, bary)
        else:
            patch = next(i for i, item in enumerate(self.patches) if index in item.triangles)
            self.patch_clicked.emit(patch, bool(event.modifiers() & (Qt.KeyboardModifier.ControlModifier | Qt.KeyboardModifier.MetaModifier)))

    def wheelEvent(self, event):
        self.camera.position += self.camera.front*(event.angleDelta().y()/120)*.15
        self.update()

    def keyPressEvent(self, event):
        if event.key() in (Qt.Key.Key_Control, Qt.Key.Key_Meta, Qt.Key.Key_AltGr) or event.modifiers() & (Qt.KeyboardModifier.ControlModifier | Qt.KeyboardModifier.MetaModifier):
            self.keys.clear()
            event.ignore()
        elif event.key() == Qt.Key.Key_Escape:
            self.placement_cancelled.emit()
        elif event.key() == Qt.Key.Key_F:
            if event.modifiers() & Qt.KeyboardModifier.ShiftModifier:
                self.frame_all()
            else:
                self.frame_requested.emit()
        elif event.key() in (Qt.Key.Key_W, Qt.Key.Key_A, Qt.Key.Key_S, Qt.Key.Key_D, Qt.Key.Key_Space, Qt.Key.Key_Alt):
            self.keys.add(event.key())
        else:
            super().keyPressEvent(event)

    def keyReleaseEvent(self, event):
        if not event.isAutoRepeat():
            self.keys.discard(event.key())

    def focusOutEvent(self, event):
        self.keys.clear()
        self.right_mouse = False
        super().focusOutEvent(event)


class BeamDiagram(QWidget):
    """Signed section-moment curves; root reactions are displayed in the window."""
    def __init__(self, parent=None):
        super().__init__(parent)
        self.result = None
        self.setMinimumHeight(210)

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.fillRect(self.rect(), QColor("#131a23"))
        painter.setPen(QColor("white"))
        r = self.result
        if r is None or r.beam_stations is None:
            painter.drawText(20, 30, r.beam_message if r and r.beam_message else "Select beam end patches and solve to plot signed bending moments.")
            return
        x, values = r.beam_stations, r.beam_moments
        scale = max(float(np.abs(values).max()), 1e-30)
        left, right, top, bottom = 65., self.width()-25., 42., self.height()-38.
        middle = (top+bottom)/2
        painter.setPen(QColor("#8c97a5"))
        painter.drawLine(int(left), int(middle), int(right), int(middle))
        painter.drawText(10, 20, f"Signed section moments (N·m), ±{scale:.5g}")
        painter.drawText(int(left), self.height()-10, f"x = {x[0]:.4g} … {x[-1]:.4g} m from clamp")
        for component, color in enumerate(("#60c0ff", "#ffb65c")):
            painter.setPen(QPen(QColor(color), 2))
            px = left+(x-x[0])/(x[-1]-x[0])*(right-left)
            py = middle-values[:, component]/scale*(bottom-top)/2
            for i in range(len(x)-1):
                painter.drawLine(int(px[i]), int(py[i]), int(px[i+1]), int(py[i+1]))
            painter.drawText(int(right)-120, 18+component*18, ("My", "Mz")[component])
        painter.end()
