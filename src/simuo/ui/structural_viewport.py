"""Structural surface selection, volume-mesh preview and stress lookup texture."""
import math

import glm
import numpy as np
from PySide6.QtCore import QElapsedTimer, QPointF, QRectF, Qt, QTimer, Signal
from PySide6.QtGui import (
    QColor,
    QLinearGradient,
    QMatrix4x4,
    QPainter,
    QPen,
    QPolygonF,
    QVector3D,
)
from PySide6.QtOpenGLWidgets import QOpenGLWidget
from PySide6.QtWidgets import QWidget

from simuo.rendering.camera import Camera
from simuo.rendering.camera_controller import CameraController
from simuo.structural.load_regions import area_region
from simuo.structural.postprocessing import (
    STRESS_COLORS,
    deformed_points,
    gradient_texture,
    normalized_field,
    stress_scale,
)

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
    deformation_changed = Signal(bool)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setMinimumSize(400, 320)
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self.setMouseTracking(True)
        self.camera = Camera()
        self.camera.near_plane = .01
        self.camera.far_plane = 100.
        self.tool = "select"
        self.camera_controller = CameraController(self, move_speed=.035/.016)
        self.keys = self.camera_controller.keys
        self.right_mouse = False
        self.point_loads = ()
        self.point_supports = ()
        self.pinned_faces = set()
        self.selected_support = None
        self.stress_mode = "yield"
        self.stress_material = None
        self.custom_stress_maximum = 1e6
        self.stress_scale_label = "Material yield"
        self.load_preview = None
        self.preview_factor = 1.
        self.deformation_enabled = False
        self.deformation_mode = "auto"
        self.custom_deformation_scale = 1.
        self.deformation_scale = 1.
        self.peak_displacement = 0.
        self._deformation_cache = None
        self.saturated = 0
        self.surface_loads = ()
        self.area_loads = ()
        self.draft_area_load = None
        self._area_region_cache = {}
        self.draft_surface_load = None
        self.selected_load = None
        self.draft_point = self.hover_point = None
        self.preview_force = (0., 0., 0.)
        self.tool_rail = self.tool_context = None
        self.navigation_clock = QElapsedTimer()
        self.navigation_clock.start()
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
        self.overlay = StructuralOverlay(self)
        self.overlay.setGeometry(self.rect())
        self.frame_all()

    def set_data(self, geometry, patches, mesh=None, result=None):
        changed = geometry is not self.geometry or mesh is not self.mesh or result is not self.result
        if geometry is not self.geometry:
            self._area_region_cache.clear()
        self.geometry, self.patches, self.mesh, self.result = geometry, patches, mesh, result
        if changed:
            self.set_deformation(False)
        self.update_stress_scale()
        self.refresh()

    def update_stress_scale(self):
        values = self.result.averaged_von_mises if self.result is not None else np.zeros(0)
        self.maximum, self.stress_scale_label = stress_scale(values, self.stress_mode, self.stress_material, self.custom_stress_maximum)
        self.saturated = int(np.count_nonzero(values > self.maximum))

    def area_region(self, load):
        key = (id(self.geometry), load)
        if key not in self._area_region_cache:
            if len(self._area_region_cache) > 64:
                self._area_region_cache.clear()
            self._area_region_cache[key] = area_region(self.geometry.points, self.geometry.triangles, load)
        return self._area_region_cache[key]

    def refresh(self):
        self._deformation_cache = None
        self.dirty = True
        self.update()

    def set_deformation(self, enabled):
        enabled = bool(enabled and self.geometry is not None and self.mesh is not None and self.result is not None and self.display != "Setup")
        if enabled != self.deformation_enabled:
            self.deformation_enabled = enabled
            self.refresh()
            self.deformation_changed.emit(enabled)

    def display_points(self):
        if self.load_preview is not None:
            scale = self.custom_deformation_scale if self.deformation_mode == "custom" else 1.
            self.deformation_scale = scale
            self.peak_displacement = float(np.linalg.norm(self.result.solution.reshape(-1,3),axis=1).max())
            return self.result.dof_points+scale*self.result.solution.reshape(-1,3)
        if self.display != "Setup" and self.mesh is not None:
            if self.deformation_enabled:
                if self._deformation_cache is None:
                    displayed, self.deformation_scale, self.peak_displacement = deformed_points(
                        self.mesh.points, self.result.displacement, self.deformation_mode, self.custom_deformation_scale)
                    self._deformation_cache = displayed
                return self._deformation_cache
            return self.mesh.points
        return self.geometry.points if self.geometry is not None else np.empty((0, 3))

    def initializeGL(self):
        from OpenGL.GL import (
            GL_CLAMP_TO_EDGE,
            GL_FRAGMENT_SHADER,
            GL_LINEAR,
            GL_RGB,
            GL_RGB8,
            GL_TEXTURE_2D,
            GL_TEXTURE_MAG_FILTER,
            GL_TEXTURE_MIN_FILTER,
            GL_TEXTURE_WRAP_S,
            GL_TEXTURE_WRAP_T,
            GL_UNPACK_ALIGNMENT,
            GL_UNSIGNED_BYTE,
            GL_VERTEX_SHADER,
            glBindTexture,
            glGenBuffers,
            glGenTextures,
            glGenVertexArrays,
            glPixelStorei,
            glTexImage2D,
            glTexParameteri,
        )
        from OpenGL.GL.shaders import compileProgram, compileShader
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
        from OpenGL.GL import (
            glDeleteBuffers,
            glDeleteProgram,
            glDeleteTextures,
            glDeleteVertexArrays,
        )
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
        if tool != "select":
            self.set_deformation(False)
        self.tool = tool
        self.hover_point = None
        self.setCursor(Qt.CursorShape.CrossCursor if tool in ("point", "area", "fixed_point") else Qt.CursorShape.ArrowCursor)
        self.update()

    def frame_all(self):
        if self.deformation_enabled:
            self.camera.frame_points(self.normalized(self.display_points()), max(1, self.width())/max(1, self.height()))
            self.update()
            return
        self.camera.position = glm.vec3(2.2, 1.5, 3.)
        self.camera.look_at((0., 0., 0.))
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

    def navigate(self, delta_time=None):
        seconds = self.navigation_clock.nsecsElapsed()/1e9 if delta_time is None else delta_time
        self.navigation_clock.restart()
        if not self.hasFocus():
            return
        if self.camera_controller.advance(seconds):
            self.update()

    def upload(self):
        import ctypes

        from OpenGL.GL import (
            GL_ARRAY_BUFFER,
            GL_FLOAT,
            GL_STATIC_DRAW,
            glBindBuffer,
            glBindVertexArray,
            glBufferData,
            glEnableVertexAttribArray,
            glVertexAttribPointer,
        )
        if self.geometry is None:
            self.draw_count = 0
            self.triangles = np.empty((0, 3, 3))
            return
        g = self.geometry
        center = (g.points.min(axis=0)+g.points.max(axis=0))/2
        radius = max(np.linalg.norm(g.dimensions)/2, 1e-12)
        if self.load_preview is not None:
            triangles = self.display_points()[self.load_preview.triangles]
            triangle_patch = self.load_preview.patches
        elif self.display != "Setup" and self.mesh is not None:
            triangles = self.display_points()[self.mesh.boundary_triangles]
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
        if self.display == "Stress" and self.result is not None and self.mesh is not None:
            raw = self.result.averaged_von_mises
            self.update_stress_scale()
            field = normalized_field(raw, self.maximum)[0] if self.maximum > 0 else np.zeros_like(raw)
            if self.load_preview is not None:
                from simuo.structural.postprocessing import von_mises
                tensors = (self.load_preview.projection@self.result.averaged_stress.reshape(-1,9)).reshape(-1,3,3)
                raw = von_mises(tensors)
                field = normalized_field(raw,self.maximum)[0] if self.maximum>0 else np.zeros_like(raw)
                values = field[self.load_preview.triangles]
            else:
                values = field[self.mesh.boundary_triangles]
        data = np.concatenate((self.triangles, colors, values[:, :, None]), axis=2).astype(np.float32)
        data = data.reshape(-1, 7)
        glBindVertexArray(self.vao)
        glBindBuffer(GL_ARRAY_BUFFER, self.vbo)
        glBufferData(GL_ARRAY_BUFFER, data.nbytes, data, GL_STATIC_DRAW)
        for location, count, offset in ((0, 3, 0), (1, 3, 12), (2, 1, 24)):
            glEnableVertexAttribArray(location)
            glVertexAttribPointer(location, count, GL_FLOAT, False, 28, ctypes.c_void_p(offset))
        self.draw_count = len(data)

    def paintGL(self):
        from OpenGL.GL import (
            GL_BLEND,
            GL_COLOR_BUFFER_BIT,
            GL_DEPTH_BUFFER_BIT,
            GL_DEPTH_TEST,
            GL_FILL,
            GL_FRONT_AND_BACK,
            GL_LINE,
            GL_SCISSOR_TEST,
            GL_TEXTURE0,
            GL_TEXTURE_2D,
            GL_TRIANGLES,
            glActiveTexture,
            glBindTexture,
            glBindVertexArray,
            glClear,
            glClearColor,
            glColorMask,
            glDepthMask,
            glDisable,
            glDrawArrays,
            glEnable,
            glGetUniformLocation,
            glPolygonMode,
            glUniform1i,
            glUniformMatrix4fv,
            glUseProgram,
        )
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
            glUniform1i(glGetUniformLocation(self.program, "show_stress"), self.display == "Stress" and self.result is not None)
            glPolygonMode(GL_FRONT_AND_BACK, GL_LINE if self.display == "Mesh" else GL_FILL)
            glDrawArrays(GL_TRIANGLES, 0, self.draw_count)
            glPolygonMode(GL_FRONT_AND_BACK, GL_FILL)
            glBindVertexArray(0)
            glUseProgram(0)
            glDisable(GL_DEPTH_TEST)
        self.overlay.update()

    def paint_overlay(self, painter):
        inset = max(14, self.tool_rail.geometry().right()+12) if self.tool_rail is not None and self.tool_rail.isVisible() else 14
        painter.setPen(QColor("white"))
        controls = "Inspection only · Right-drag looks · WASD moves · Space/Alt up/down · F frames" if self.deformation_enabled else "Left-click selects · Ctrl adds faces · Right-drag looks · WASD moves · Space/Alt up/down · F frames"
        painter.drawText(inset, self.height()-10, controls)
        self.paint_loads(painter)
        painter.setPen(QColor("white"))
        if self.deformation_enabled:
            y = self.tool_context.geometry().bottom()+20 if self.tool_context is not None else 24
            painter.drawText(inset, y, f"Deformation: {self.deformation_scale:.6g}× (visual magnification)")
            painter.drawText(inset, y+18, f"Peak displacement: {self.peak_displacement:.6g} m · elastic preview")
            if self.load_preview is not None:
                painter.drawText(inset,y+36,f"Load preview: {self.preview_factor:.6g}× analyzed load · preview only")
                limits = self.load_preview.strength_limits
                if limits['yield'] is not None and self.preview_factor >= limits['yield']:
                    painter.drawText(inset,y+54,"Elastic extrapolation beyond yield")
                if limits['uts'] is not None and self.preview_factor >= limits['uts']:
                    painter.drawText(inset,y+72,"UTS reference reached — fracture is not simulated")
        if self.display == "Stress" and self.result is not None:
            x, y = max(20, inset), self.height()-100
            gradient = QLinearGradient(x, y, x+250, y)
            for position, color in STRESS_COLORS:
                gradient.setColorAt(position, QColor.fromRgbF(*color))
            painter.fillRect(QRectF(x, y, 250, 16), gradient)
            painter.drawText(x, y-24, self.stress_scale_label)
            painter.drawText(x, y-9, "Averaged von Mises stress (MPa)")
            painter.drawText(x, y+33, f"0              {self.maximum/2e6:.4g}              {self.maximum/1e6:.4g}{' + saturated' if self.saturated else ''}")
            painter.drawText(x, y+52, f"Unaveraged peak: {self.result.von_mises.max()/1e6:.6g} MPa")

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
        if self.load_preview is not None:
            points = self.display_points()
            for identity,name,nodes,weights,direction in self.load_preview.anchors:
                position = weights@points[nodes]
                if identity == self.load_preview.load_id:
                    direction = direction*self.preview_factor
                if self.visible_point(position):
                    self.arrow(painter,position,direction,"#ffad57" if np.any(direction) else "#68a4ff",name)
            return
        if self.geometry is None or self.deformation_enabled:
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
        for load in (*self.area_loads, *((self.draft_area_load,) if self.draft_area_load is not None else ())):
            if self.draft_area_load is not None and load.identifier == self.selected_load:
                continue
            try:
                region = self.area_region(load)
            except ValueError:
                continue
            color = "#78e4de" if load.identifier == "draft" else "#f0bcc8" if load.identifier == self.selected_load else "#ffad57"
            painter.setPen(Qt.PenStyle.NoPen)
            fill = QColor(color)
            fill.setAlpha(85)
            painter.setBrush(fill)
            for triangle in region.triangles:
                screen = [self.project_point(vertex) for vertex in triangle]
                if all(point is not None for point in screen) and self.visible_point(triangle.mean(axis=0)):
                    painter.drawPolygon(QPolygonF([QPointF(*point) for point in screen]))
            if self.visible_point(region.center):
                direction = load.value if load.kind == "force" else -load.value[0]*region.normal
                self.arrow(painter, region.center, direction, color, load.name)
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
        hit = self.pick_surface(*screen, inspection=self.load_preview is not None)
        return hit is not None and np.linalg.norm(hit[2]-point) <= np.linalg.norm(self.geometry.dimensions)*2e-5

    def pick_surface(self, x, y, *, inspection=False):
        if self.geometry is None or ((self.deformation_enabled or self.load_preview is not None) and not inspection):
            return None
        inverse, valid = self.matrices().inverted()
        if not valid:
            return None
        nx = 2*x/max(self.width(), 1)-1
        ny = 1-2*y/max(self.height(), 1)
        a, b = (inverse.map(QVector3D(nx, ny, z)) for z in (-1., 1.))
        origin = np.array(a.toTuple())
        direction = np.array(b.toTuple())-origin
        source = self.display_points()[self.load_preview.triangles] if inspection and self.load_preview is not None else self.geometry.points[self.geometry.triangles]
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
            self.camera_controller.look(delta.x(), -delta.y())
            self.last_mouse = event.position()
            self.update()
        elif self.tool in ("point", "area", "fixed_point"):
            hit = self.pick_surface(event.position().x(), event.position().y())
            self.hover_point = hit[2] if hit else None
            self.update()

    def mouseReleaseEvent(self, event):
        if event.button() == Qt.MouseButton.RightButton:
            self.right_mouse = False
            self.setCursor(Qt.CursorShape.CrossCursor if self.tool in ("point", "area", "fixed_point") else Qt.CursorShape.ArrowCursor)
            return
        if event.button() != Qt.MouseButton.LeftButton or self.last_mouse is None:
            return
        moved = (event.position()-self.press_mouse).manhattanLength()
        self.last_mouse = None
        if moved > 4:
            return
        if self.deformation_enabled:
            return
        if self.tool == "select" and self.geometry:
            from simuo.structural.meshing import point_position
            for support in reversed(self.point_supports):
                point = point_position(self.geometry, support)
                screen = self.project_point(point)
                if screen is not None and np.linalg.norm(screen-np.array(event.position().toTuple())) < 12 and self.visible_point(point):
                    self.support_picked.emit(support.identifier)
                    return
            for load in reversed((*self.point_loads, *self.area_loads)):
                point = point_position(self.geometry, load)
                screen = self.project_point(point)
                if screen is not None and np.linalg.norm(screen-np.array(event.position().toTuple())) < 12 and self.visible_point(point):
                    self.load_picked.emit(load.identifier)
                    return
        hit = self.pick_surface(event.position().x(), event.position().y())
        if hit is None:
            return
        index, bary, point = hit
        if self.tool in ("point", "area", "fixed_point"):
            self.point_picked.emit(index, bary)
        else:
            patch = next(i for i, item in enumerate(self.patches) if index in item.triangles)
            self.patch_clicked.emit(patch, bool(event.modifiers() & (Qt.KeyboardModifier.ControlModifier | Qt.KeyboardModifier.MetaModifier)))

    def wheelEvent(self, event):
        self.camera_controller.dolly(event.angleDelta().y()/120)
        self.update()

    def keyPressEvent(self, event):
        if self.camera_controller.key_press(event):
            return
        if event.key() == Qt.Key.Key_Escape:
            self.placement_cancelled.emit()
        elif event.key() == Qt.Key.Key_F:
            if event.modifiers() & Qt.KeyboardModifier.ShiftModifier:
                self.frame_all()
            else:
                self.frame_requested.emit()
        else:
            super().keyPressEvent(event)

    def keyReleaseEvent(self, event):
        if not self.camera_controller.key_release(event):
            super().keyReleaseEvent(event)

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
