"""Qt OpenGL viewport, GPU resources, rendering, and camera input."""

import math
import sys
import time
import ctypes

import glm
from OpenGL.GL import *
from OpenGL.GL.shaders import compileProgram, compileShader
from PySide6.QtOpenGLWidgets import QOpenGLWidget
from PySide6.QtCore import Qt, QTimer, QPoint, Signal, Slot
from PySide6.QtGui import QCursor

from simuo.rendering.camera import Camera
from simuo.rendering.geometry import create_axis_lines
from simuo.rendering.picking import PickMesh, object_matrix, pick_object
from simuo.rendering.ray import Ray
from simuo.rendering.outline import SelectionOutline
from simuo.rendering.manipulation import MoveDrag, MoveGizmo, Projection, box_candidates
from simuo.rendering.overlays import InteractionOverlay
from simuo.rendering.selection_buffer import SelectionBuffer
from simuo.rendering.shaders import (
    AXIS_VERTEX_SHADER, AXIS_FRAGMENT_SHADER,
    DEBUG_RAY_VERTEX_SHADER, DEBUG_RAY_FRAGMENT_SHADER,
    VERTEX_SHADER, FRAGMENT_SHADER,
)


class OpenGLViewport(QOpenGLWidget):
    """Qt widget that renders the 3D scene and handles camera interaction.

    Camera interaction here means the user is effectively piloting a first-person
    camera through the scene. The camera has a position and a local basis
    (forward/right/up) derived from yaw and pitch, and input changes that basis
    or the camera's world position.

    Keyboard movement is relative to the current camera orientation:
    - W/S move along the camera's forward vector
    - A/D strafe left/right along the camera's right vector
    - Space/C move vertically along the world's up vector

    Mouse interaction is used for looking around the scene. While the right mouse
    button is held, the cursor is recentered inside the widget so the user can
    drag continuously without the pointer leaving the viewport. Horizontal motion
    changes yaw and vertical motion changes pitch, producing a look-around feel
    similar to a free-fly viewer.
    """

    object_picked = Signal(object)
    frame_requested = Signal()
    frame_scene_requested = Signal()
    escape_requested = Signal()
    box_selection_requested = Signal(object)
    transform_started = Signal(object, str)
    transform_previewed = Signal(object)
    transform_finished = Signal(bool)
    tools_visibility_requested = Signal()

    CAMERA_KEYS = frozenset((Qt.Key_W, Qt.Key_A, Qt.Key_S, Qt.Key_D, Qt.Key_Space, Qt.Key_C, Qt.Key_Left, Qt.Key_Right))
    SHORTCUT_KEYS = frozenset((Qt.Key_Control, Qt.Key_Meta, Qt.Key_Alt, Qt.Key_AltGr))
    SHORTCUT_MODIFIERS = Qt.ControlModifier | Qt.MetaModifier | Qt.AltModifier | Qt.GroupSwitchModifier

    def __init__(
        self,
        parent=None,
        scene=None,

    ):
        # OpenGL axis helper state.
        self.axisShader = None
        self.debugRayShader = None
        self.axisVAO = None
        self.axisVBO = None
        self.axisVertexCount = 0
        super().__init__(
            parent
        )
        # Mouse recenter guard state.
        self.ignore_center_event = False
        # Scene reference used during rendering.
        self.scene = scene
        self.selected_object_id = None
        self.selected_object_ids = set()
        self.selected_objects = ()
        self.active_tool = "select"
        self.tool_options = {"xray": False}
        self.drag = None
        self.hover_handle = None
        self._box_start = self._box_end = None
        self._box_dragged = False
        self._selection_before = ()
        self._selection_modifiers = Qt.NoModifier
        self.selection_buffer = None
        self.pick_modifiers = Qt.KeyboardModifier.NoModifier

        self.setFocusPolicy(
            Qt.StrongFocus
        )

        self.setMouseTracking(
            True
        )

        # Active camera state.
        self.camera = Camera()

        # Keyboard input state.
        self.keys = set()

        # Mouse drag state.
        self.right_mouse_down = False
        self.last_mouse_position = None

        # Main scene shader and generated render-object cache.
        self.shader = None
        self.renderObjects = []
        self.debug_ray = None
        self.debug_ray_vao = None
        self.debug_ray_vbo = None

        # Cached uniform locations for the main shader.
        self.model_location = None
        self.view_location = None
        self.projection_location = None
        self.camera_location = None
        self.selection_outline = None
        self.interaction_overlay = InteractionOverlay(self)

        # Frame timing state.
        self.last_time = (
            time.perf_counter()
        )

        # The timer drives keyboard navigation without repainting an idle scene.
        self.timer = QTimer(
            self
        )

        self.timer.timeout.connect(
            self._tick_camera
        )

        self.timer.start(
            8
        )

    def _tick_camera(self):
        now = time.perf_counter()
        delta_time = min(now - self.last_time, 0.1)
        self.last_time = now
        if self.keys and self.drag is None and self._box_start is None:
            self.update_camera(delta_time)
            self.request_frame()

    def request_frame(self):
        self.update()
        if self.active_tool == "move":
            self.interaction_overlay.update()

    # ---------------------------------------------------------
    # OPENGL SETUP
    # ---------------------------------------------------------

    def set_selected_object(self, obj):
        self.selected_object_id = obj.identifier if obj is not None else None
        self.selected_object_ids = {obj.identifier} if obj is not None else set()
        self.selected_objects = (obj,) if obj is not None else ()
        self.interaction_overlay.update()
        self.update()

    def set_selected_objects(self, objects):
        self.selected_objects = tuple(objects)
        self.selected_object_ids = {obj.identifier for obj in objects}
        self.selected_object_id = objects[-1].identifier if objects else None
        self.request_frame()

    def set_tool(self, tool):
        self.cancel_interaction()
        self.active_tool = tool
        self.hover_handle = None
        self.interaction_overlay.update()

    def set_tool_options(self, options):
        self.cancel_interaction()
        self.tool_options = dict(options)
        self.interaction_overlay.update()

    def projection(self):
        return Projection(self.camera, self.width(), self.height())

    def gizmo(self):
        if self.active_tool != "move" or len(self.selected_objects) != 1:
            return None
        obj = self.selected_objects[0]
        if not obj.viewport_visible or obj.viewport_locked:
            return None
        for item in self.renderObjects:
            mesh = item.get('pick_mesh')
            if item['SceneObject'] is obj and mesh is not None and len(mesh.triangles):
                return MoveGizmo(obj, self.projection())
        return None

    def box_rect(self):
        if not self._box_dragged or self._box_start is None:
            return None
        a, b = self._box_start, self._box_end
        return min(a[0], b[0]), min(a[1], b[1]), max(a[0], b[0]), max(a[1], b[1])

    def select_box(self, rect):
        projection = self.projection()
        if self.tool_options['xray'] or not self.isValid():
            return box_candidates(self.renderObjects, projection, rect)
        self.makeCurrent()
        try:
            if self.selection_buffer is None:
                self.selection_buffer = SelectionBuffer()
            ratio = self.devicePixelRatioF()
            return self.selection_buffer.select(self.renderObjects, projection, rect,
                                                max(1, round(self.width()*ratio)), max(1, round(self.height()*ratio)),
                                                ratio, self.defaultFramebufferObject())
        finally:
            self.doneCurrent()
            self.update()

    def discard_transform(self):
        self.drag = None
        self.keys.clear()
        if self.isVisible() and not self.right_mouse_down:
            self.releaseMouse()
        self.unsetCursor()
        self.interaction_overlay.update()

    def cancel_interaction(self):
        if self.drag is not None:
            self.drag = None
            self.transform_finished.emit(False)
            self.discard_transform()
        if self._box_start is not None:
            if self._box_dragged:
                self.box_selection_requested.emit(self._selection_before)
            self._box_start = self._box_end = None
            self._box_dragged = False
            self.keys.clear()
            self.unsetCursor()
            self.interaction_overlay.update()

    def resizeEvent(self, event):
        if hasattr(self, 'interaction_overlay'):
            self.cancel_interaction()
            self.interaction_overlay.setGeometry(self.rect())
            self.layout_tools()
        super().resizeEvent(event)

    def layout_tools(self):
        toolbar = getattr(self, 'tool_sidebar', None)
        context = getattr(self, 'tool_context', None)
        if context is not None:
            context.fit_to_width(max(1, self.width()-16))
            context.raise_()
        if toolbar is not None:
            toolbar.adjustSize()
            toolbar.move(8, context.geometry().bottom()+9 if context is not None else 8)
            toolbar.raise_()

    def frame_object(self, obj):
        """Fit the transformed mesh to the view while preserving camera rotation."""
        from itertools import product

        self.cancel_interaction()
        self.keys.clear()
        objects = (obj,) if hasattr(obj, "identifier") else tuple(obj)
        keys = {item.identifier for item in objects if item.viewport_visible}
        corners = []
        records = list(self.renderObjects)
        uploaded = {record["SceneObject"].identifier for record in records}
        records.extend({"SceneObject": item, "pick_mesh": PickMesh(item.asset.vertices)}
                       for item in objects if item.asset is not None and item.identifier not in uploaded)
        for rendered in records:
            if rendered["SceneObject"].identifier not in keys:
                continue
            mesh = rendered.get("pick_mesh")
            if mesh is None or not len(mesh.triangles):
                continue
            model = object_matrix(rendered["SceneObject"])
            corners.extend(glm.vec3(model * glm.vec4(x, y, z, 1.0)) for x, y, z in product(
                (float(mesh.minimum[0]), float(mesh.maximum[0])),
                (float(mesh.minimum[1]), float(mesh.maximum[1])),
                (float(mesh.minimum[2]), float(mesh.maximum[2])),
            ))
        if not corners:
            return False
        center = glm.vec3(*[(min(point[axis] for point in corners) + max(point[axis] for point in corners)) / 2
                           for axis in range(3)])
        vertical = math.tan(math.radians(self.camera.field_of_view / 2))
        horizontal = vertical * max(1, self.width()) / max(1, self.height())
        distance = self.camera.near_plane
        depths = []
        for corner in corners:
            delta = corner - center
            depth = glm.dot(delta, self.camera.front)
            depths.append(depth)
            distance = max(distance,
                           abs(glm.dot(delta, self.camera.right)) * 1.15 / horizontal - depth,
                           abs(glm.dot(delta, self.camera.up)) * 1.15 / vertical - depth,
                           self.camera.near_plane * 2 - depth)
        self.camera.position = center - self.camera.front * distance
        self.camera.far_plane = max(1000.0, (distance + max(depths)) * 1.2)
        self.keys.clear()
        self.request_frame()
        return True

    def frameObject(self, obj):
        """Frame an imported part, including before the first GL upload."""
        return self.frame_object(obj)

    def sync_scene_objects(self):
        """Update only added/removed GPU meshes; keep the others untouched."""
        if not self.isValid():
            return  # initializeGL will upload the current scene when shown.
        current = {obj.identifier: obj for obj in self.scene.objects if obj.asset is not None}
        self.makeCurrent()
        for item in list(self.renderObjects):
            key = item["SceneObject"].identifier
            if key not in current or current[key] is not item["SceneObject"]:
                glDeleteVertexArrays(1, [item["vao"]])
                glDeleteBuffers(1, [item["vbo"]])
                self.renderObjects.remove(item)
        self.doneCurrent()
        rendered = {item["SceneObject"].identifier for item in self.renderObjects}
        for key, obj in current.items():
            if key not in rendered:
                self.addNewObject(obj)
        self.request_frame()

    @Slot()
    def cleanup_outline(self):
        """Release outline resources while their OpenGL context is still alive."""
        if self.selection_outline is not None:
            self.makeCurrent()
            self.selection_outline.cleanup()
            self.selection_outline = None
            self.doneCurrent()
        if self.selection_buffer is not None:
            self.makeCurrent()
            self.selection_buffer.cleanup()
            self.selection_buffer = None
            self.doneCurrent()

    def clearRenderObjects(self):
        """Delete all OpenGL vertex buffers and arrays belonging to scene objects."""
        self.makeCurrent()

        for renderObject in self.renderObjects:
            vao = renderObject[
                "vao"
            ]

            vbo = renderObject[
                "vbo"
            ]

            glDeleteVertexArrays(
                1,
                [vao]
            )

            glDeleteBuffers(
                1,
                [vbo]
            )

        # Clear the cached render-object list after GPU resources are released.
        self.renderObjects.clear()

        self.doneCurrent()

        self.update()

    def addNewObject(self, obj):
        """Upload an already parsed asset if the context is ready."""
        if obj.asset is None or not self.isValid():
            return
        self.makeCurrent()
        try:
            self._uploadObject(obj)
        finally:
            self.doneCurrent()
        self.update()

    def _uploadObject(self, sceneObject):
        """Upload validated CPU position/normal data and append a VAO/VBO render record.
        The caller must own a current OpenGL context.

        Args:
            sceneObject (SceneObject): Instance to display, remove, or edit.

        Returns:
            None. Allocates GPU resources; partial allocations are released if setup
            fails.
        """
        vertexData = sceneObject.asset.vertices
        points = vertexData.reshape(-1, 6)[:, :3]
        sceneObject.localMin = points.min(axis=0)
        sceneObject.localMax = points.max(axis=0)
        vao = glGenVertexArrays(1)
        vbo = glGenBuffers(1)
        try:
            glBindVertexArray(vao)
            glBindBuffer(GL_ARRAY_BUFFER, vbo)
            glBufferData(GL_ARRAY_BUFFER, vertexData.nbytes, vertexData, GL_STATIC_DRAW)
            stride = 6 * vertexData.itemsize
            for location, offset in ((0, 0), (1, 3 * vertexData.itemsize)):
                glEnableVertexAttribArray(location)
                glVertexAttribPointer(location, 3, GL_FLOAT, GL_FALSE, stride,
                                      ctypes.c_void_p(offset))
            glBindVertexArray(0)
        except Exception:
            glDeleteBuffers(1, [vbo])
            glDeleteVertexArrays(1, [vao])
            raise
        self.renderObjects.append({
            "SceneObject": sceneObject, "vao": vao, "vbo": vbo,
            "vertexCount": len(vertexData) // 6, "pick_mesh": PickMesh(vertexData),
        })
        print(f"Loaded {len(vertexData) // 6:,} vertices for {sceneObject.name}")

    def initializeGL(self):
        """Initialize OpenGL state, shaders, and scene buffers.

        This method compiles the shader programs, configures depth buffering, and
        uploads the axis and scene meshes for rendering.
        """
        print(
            "initializeGL called"
        )

        print(
            "OpenGL version:",
            glGetString(
                GL_VERSION
            )
        )

        print(
            "GPU:",
            glGetString(
                GL_RENDERER
            )
        )

        glEnable(
            GL_DEPTH_TEST
        )

        # Compile and cache the main scene shader.
        self.shader = compileProgram(
            compileShader(
                VERTEX_SHADER,
                GL_VERTEX_SHADER
            ),
            compileShader(
                FRAGMENT_SHADER,
                GL_FRAGMENT_SHADER
            ),
            # Validation checks the current drawing state. Qt's framebuffer
            # and our VAOs are not ready here, so macOS rejects validation.
            # Shader compilation and program linking are still checked.
            validate=sys.platform != "darwin",
        )

        # Compile and cache the axis helper shader.
        self.axisShader = compileProgram(
            compileShader(
                AXIS_VERTEX_SHADER,
                GL_VERTEX_SHADER
            ),
            compileShader(
                AXIS_FRAGMENT_SHADER,
                GL_FRAGMENT_SHADER
            ),
            validate=sys.platform != "darwin",
        )

        self.debugRayShader = compileProgram(
            compileShader(
                DEBUG_RAY_VERTEX_SHADER,
                GL_VERTEX_SHADER
            ),
            compileShader(
                DEBUG_RAY_FRAGMENT_SHADER,
                GL_FRAGMENT_SHADER
            ),
            validate=sys.platform != "darwin",
        )

        # Cache the main shader uniform locations.
        self.model_location = (
            glGetUniformLocation(
                self.shader,
                "model"
            )
        )
        self.color_location = glGetUniformLocation(self.shader, "base_color")
        self.selection_outline = SelectionOutline()
        self.context().aboutToBeDestroyed.connect(self.cleanup_outline)

        # Cache the view matrix uniform location.
        self.view_location = (
            glGetUniformLocation(
                self.shader,
                "view"
            )
        )

        # Cache the projection matrix uniform location.
        self.projection_location = (
            glGetUniformLocation(
                self.shader,
                "projection"
            )
        )

        # Cache the camera position uniform location.
        self.camera_location = (
            glGetUniformLocation(
                self.shader,
                "camera_position"
            )
        )

        axisData = create_axis_lines(-2000,2000)

        # Cache the generated axis geometry state.
        self.axisVertexCount  = len(axisData) // 3
        self.axisVAO = glGenVertexArrays(1)
        glBindVertexArray(
            self.axisVAO
        )

        self.axisVBO = glGenBuffers(
            1
        )

        glBindBuffer(
            GL_ARRAY_BUFFER,
            self.axisVBO
        )

        glBufferData(
            GL_ARRAY_BUFFER,
            axisData.nbytes,
            axisData,
            GL_STATIC_DRAW
        )

        glEnableVertexAttribArray(
            0
        )

        glVertexAttribPointer(
            0,
            3,
            GL_FLOAT,
            GL_FALSE,
            3 * axisData.itemsize,
            ctypes.c_void_p(0)
        )

        glBindVertexArray(
            0
        )

        if self.debug_ray_vao is None:
            self.debug_ray_vao = glGenVertexArrays(1)
            self.debug_ray_vbo = glGenBuffers(1)

        if self.scene is not None:
            for obj in self.scene.objects:
                if obj.asset is not None:
                    self._uploadObject(obj)

        print(
            "OpenGL viewport initialized"
        )

    def resizeGL(
        self,
        width,
        height
    ):
        """Handle resize events and update the OpenGL viewport size.

        Args:
            width: New viewport width.
            height: New viewport height.
        """
        ratio = (
            self.devicePixelRatioF()
        )

        glViewport(
            0,
            0,
            max(
                1,
                int(
                    width
                    * ratio
                )
            ),
            max(
                1,
                int(
                    height
                    * ratio
                )
            ),
        )

    # ---------------------------------------------------------
    # RENDER
    # ---------------------------------------------------------

    def paintGL(self):
        """Render one frame of the 3D scene.

        Clear the framebuffer, calculate the projection and view matrices,
        and draw the axis helper and scene objects.
        """
        # Qt paints child controls/overlays with its own GL state between frames.
        glEnable(GL_DEPTH_TEST)
        glDepthMask(GL_TRUE)
        glDepthFunc(GL_LESS)
        glDisable(GL_BLEND)
        glDisable(GL_SCISSOR_TEST)
        glDisable(GL_CULL_FACE)
        glColorMask(GL_TRUE, GL_TRUE, GL_TRUE, GL_TRUE)

        ratio = (
            self.devicePixelRatioF()
        )

        width = max(
            1,
            int(
                self.width()
                * ratio
            )
        )

        height = max(
            1,
            int(
                self.height()
                * ratio
            )
        )

        glViewport(
            0,
            0,
            width,
            height,
        )

        glClearColor(
            0.18,
            0.18,
            0.20,
            1.0
        )

        glClear(
            GL_COLOR_BUFFER_BIT
            | GL_DEPTH_BUFFER_BIT
        )

        if self.shader is None:
            return

        glUseProgram(
            self.shader
        )

        aspect = (
            width
            / height
        )

        projection = glm.perspective(
            glm.radians(
                self.camera.field_of_view
            ),
            aspect,
            self.camera.near_plane,
            self.camera.far_plane,
        )

        view = (
            self.camera.view_matrix()
        )

        # ---------------------------------------------------------
        # DRAW AXIS
        # ---------------------------------------------------------

        glUseProgram(
            self.axisShader
        )


        axisViewLocation = glGetUniformLocation(
            self.axisShader,
            "view"
        )

        axisProjectionLocation = glGetUniformLocation(
            self.axisShader,
            "projection"
        )

        glUniformMatrix4fv(
            axisViewLocation,
            1,
            GL_FALSE,
            glm.value_ptr(view)
        )

        glUniformMatrix4fv(
            axisProjectionLocation,
            1,
            GL_FALSE,
            glm.value_ptr(projection)
        )

        glBindVertexArray(
            self.axisVAO
        )

        glDrawArrays(
            GL_LINES,
            0,
            self.axisVertexCount
        )

        glBindVertexArray(
            0
        )

        if self.debug_ray is not None:
            glUseProgram(self.debugRayShader)

            debugViewLocation = glGetUniformLocation(self.debugRayShader, "view")
            debugProjectionLocation = glGetUniformLocation(self.debugRayShader, "projection")

            glUniformMatrix4fv(debugViewLocation, 1, GL_FALSE, glm.value_ptr(view))
            glUniformMatrix4fv(debugProjectionLocation, 1, GL_FALSE, glm.value_ptr(projection))

            glBindVertexArray(self.debug_ray_vao)
            glBindBuffer(GL_ARRAY_BUFFER, self.debug_ray_vbo)
            glBufferData(GL_ARRAY_BUFFER, self.debug_ray.nbytes, self.debug_ray, GL_DYNAMIC_DRAW)
            glEnableVertexAttribArray(0)
            glVertexAttribPointer(0, 3, GL_FLOAT, GL_FALSE, 3 * self.debug_ray.itemsize, ctypes.c_void_p(0))
            glDrawArrays(GL_LINES, 0, 2)
            glBindVertexArray(0)
            glUseProgram(0)

        # ---------------------------------------------------------
        # DRAW SCENE OBJECTS
        # ---------------------------------------------------------

        glUseProgram(
            self.shader
        )
        glUniformMatrix4fv(
            self.view_location,
            1,
            GL_FALSE,
            glm.value_ptr(
                view
            )
        )

        glUniformMatrix4fv(
            self.projection_location,
            1,
            GL_FALSE,
            glm.value_ptr(
                projection
            )
        )

        glUniform3f(
            self.camera_location,
            self.camera.position.x,
            self.camera.position.y,
            self.camera.position.z
        )


        for renderObject in self.renderObjects:

            sceneObject = (
                renderObject[
                    "SceneObject"
                ]
            )
            if not sceneObject.viewport_visible:
                continue

            glUniform3f(self.color_location, *sceneObject.asset.color)
            model = object_matrix(sceneObject)

            glUniformMatrix4fv(
                self.model_location,
                1,
                GL_FALSE,
                glm.value_ptr(
                    model
                )
            )

            glBindVertexArray(
                renderObject[
                    "vao"
                ]
            )

            glDrawArrays(
                GL_TRIANGLES,
                0,
                renderObject[
                    "vertexCount"
                ]
            )

        glBindVertexArray(
            0
        )

        glUseProgram(
            0
        )

        self.selection_outline.draw(
            self.renderObjects, self.selected_object_ids, view, projection,
            self.defaultFramebufferObject(), width, height, ratio,
        )




    # ---------------------------------------------------------
    # CAMERA INPUT
    # ---------------------------------------------------------

    def update_camera(
        self,
        delta_time
    ):
        """Apply keyboard-driven camera movement relative to the current view.

        "Camera interaction" in this class is a free-fly camera: the user moves the
        camera itself through the 3D scene instead of orbiting around a target. The
        camera's current forward/right/up vectors define the local axes, so motion is
        always relative to the direction the viewer is facing.

        Args:
            delta_time: Time elapsed since the previous frame.
        """
        if self.drag is not None or self._box_start is not None:
            return
        turn = int(Qt.Key_Right in self.keys) - int(Qt.Key_Left in self.keys)
        if turn:
            self.camera.yaw += turn * 90.0 * delta_time
            self.camera.update_vectors()
        speed = (
            10.0
            * delta_time
        )

        # Move forward/back along the camera's viewing direction.
        if Qt.Key_W in self.keys:
            self.camera.position += (
                self.camera.front
                * speed
            )

        if Qt.Key_S in self.keys:
            self.camera.position -= (
                self.camera.front
                * speed
            )

        # Side-step relative to the camera's local right axis.
        if Qt.Key_D in self.keys:
            self.camera.position += (
                self.camera.right
                * speed
            )

        if Qt.Key_A in self.keys:
            self.camera.position -= (
                self.camera.right
                * speed
            )

        # Vertical movement is independent of the viewing direction and tracks the
        # scene's world-up axis, which makes it easier to inspect the model from
        # above or below while still looking around.
        if Qt.Key_Space in self.keys:
            self.camera.position += (
                self.camera.world_up
                * speed
            )

        if Qt.Key_C in self.keys:
            self.camera.position -= (
                self.camera.world_up
                * speed
            )

    def focusOutEvent(self, event):
        """Stop camera input when the user moves focus into an editor panel."""
        self.keys.clear()
        self.cancel_interaction()
        if self.right_mouse_down:
            self.right_mouse_down = False
            self.ignore_center_event = False
            self.releaseMouse()
            self.unsetCursor()
        super().focusOutEvent(event)

    def keyPressEvent(
        self,
        event
    ):
        """Track camera keys and delegate Escape to the editor's current mode.

        Args:
            event: Qt keyboard event.
        """
        # Selection modifiers and editor shortcuts must never start (or keep)
        # camera movement. Qt maps the macOS Command key to Key_Control.
        if event.key() in self.SHORTCUT_KEYS or event.modifiers() & self.SHORTCUT_MODIFIERS:
            self.keys.clear()
            event.ignore()
            return
        if event.isAutoRepeat():
            event.accept()
            return
        if event.key() == Qt.Key_F and event.modifiers() == Qt.NoModifier:
            self.frame_requested.emit()
            event.accept()
            return
        if event.key() == Qt.Key_F and event.modifiers() == Qt.ShiftModifier:
            self.frame_scene_requested.emit()
            event.accept()
            return
        if event.key() == Qt.Key_Escape:
            if self.drag is not None or self._box_start is not None:
                self.cancel_interaction()
                event.accept()
                return
            self.escape_requested.emit()
            event.accept()
            return
        if event.key() == Qt.Key_T and event.modifiers() == Qt.NoModifier:
            self.tools_visibility_requested.emit()
            event.accept()
            return
        if event.key() in self.CAMERA_KEYS:
            self.keys.add(event.key())
            event.accept()
        else:
            super().keyPressEvent(event)

    def keyReleaseEvent(
        self,
        event
    ):
        """Remove a key from the active input set when released.

        Args:
            event: Qt keyboard event.
        """
        if event.isAutoRepeat():
            return
        # Shortcut letters stay unarmed until pressed again without modifiers.
        self.keys.discard(
            event.key()
        )

    def mousePressEvent(self, event):
        """Start look-around camera control while the right mouse button is held.

        The user is not orbiting around an object; they are turning the camera as if
        they are looking around from inside the scene. Pressing the right mouse button
        locks the cursor to the viewport and forces the pointer back to the center on
        each movement step so continuous dragging feels smooth and stable.

        Args:
            event: Qt mouse event.
        """
        if event.modifiers() & self.SHORTCUT_MODIFIERS:
            self.keys.clear()
        if event.button() == Qt.LeftButton:
            if self.right_mouse_down:
                return
            self.setFocus()
            self.keys.clear()
            point = (event.position().x(), event.position().y())
            gizmo = self.gizmo()
            handle = gizmo.hit(point) if gizmo is not None else None
            modifiers = event.modifiers() & (Qt.ControlModifier | Qt.MetaModifier | Qt.ShiftModifier | Qt.AltModifier)
            if handle is not None and not modifiers:
                self.drag = MoveDrag(gizmo, handle, point)
                self.transform_started.emit((gizmo.mover.scene_object.identifier,), 'Move Object')
                if self.isVisible():
                    self.grabMouse()
                self.interaction_overlay.update()
                event.accept()
                return
            if self.active_tool == 'select':
                self._box_start = self._box_end = point
                self._box_dragged = False
                self._selection_before = tuple(obj.identifier for obj in self.selected_objects)
                self._selection_modifiers = event.modifiers()
            width, height = max(1, self.width()), max(1, self.height())
            projection = glm.perspective(
                glm.radians(self.camera.field_of_view), width / height,
                self.camera.near_plane, self.camera.far_plane,
            )
            origin, direction = self.camera.mouse_ray(
                event, width, height, projection, self.camera.view_matrix()
            )
            # Match the near/far view planes, including rays away from the center.
            depth = float(glm.dot(direction, self.camera.front))
            selected = pick_object(
                self.renderObjects, origin, direction,
                self.camera.near_plane / depth, self.camera.far_plane / depth,
            )
            self.pick_modifiers = event.modifiers()
            self.object_picked.emit(selected.identifier if selected is not None else None)
            self.pick_modifiers = Qt.KeyboardModifier.NoModifier
            event.accept()

        elif event.button() == Qt.RightButton:
            if self.drag is not None or self._box_start is not None:
                self.cancel_interaction()
                event.accept()
                return
            self.right_mouse_down = True
            self.setCursor(Qt.BlankCursor)
            self.grabMouse()
            self.setFocus()
            self.ignore_center_event = True
            self.center_mouse()

    def mouseReleaseEvent(self, event):
        """Stop camera look-around control when the right mouse button is released.

        Releasing the button returns cursor control to the desktop and ends the
        persistent drag state used for camera yaw/pitch updates.

        Args:
            event: Qt mouse event.
        """
        if event.button() == Qt.LeftButton:
            if self.drag is not None:
                point = (event.position().x(), event.position().y())
                if self.drag.feedback or self.drag.start != point:
                    self.transform_previewed.emit(self.drag.updates(point))
                self.drag = None
                self.transform_finished.emit(True)
                self.discard_transform()
            elif self._box_start is not None:
                self._box_end = (event.position().x(), event.position().y())
                rect = self.box_rect()
                if rect is not None:
                    found = self.select_box(rect)
                    before = self._selection_before
                    modifiers = self._selection_modifiers
                    if modifiers & (Qt.ControlModifier | Qt.MetaModifier):
                        selection = [key for key in before if key not in found] + [key for key in found if key not in before]
                    elif modifiers & Qt.ShiftModifier:
                        selection = list(dict.fromkeys((*before, *found)))
                    else:
                        selection = found
                    self.box_selection_requested.emit(tuple(selection))
                self._box_start = self._box_end = None
                self._box_dragged = False
                self.keys.clear()
                self.unsetCursor()
                self.interaction_overlay.update()
            event.accept()
            return
        if event.button() == Qt.RightButton:
            # Clear the drag state when rotation ends.
            self.right_mouse_down = False

            # Allow the next mouse move to be processed normally.
            self.ignore_center_event = False

            self.releaseMouse()
            self.unsetCursor()

    def mouseMoveEvent(self, event):
        """Rotate the camera based on drag movement while in look mode.

        Camera interaction here is implemented as a "look around" controller. The
        cursor delta is translated into yaw and pitch changes on the Camera object,
        so dragging left/right turns the view horizontally and dragging up/down tilts
        the view vertically. A recenter step keeps the pointer from reaching the edge
        of the widget, which would otherwise break the drag experience.

        Args:
            event: Qt mouse move event.
        """
        point = (event.position().x(), event.position().y())
        if self.drag is not None:
            self.transform_previewed.emit(self.drag.updates(point))
            self.interaction_overlay.update()
            event.accept()
            return
        if self._box_start is not None and event.buttons() & Qt.LeftButton:
            self._box_end = point
            if abs(point[0]-self._box_start[0])+abs(point[1]-self._box_start[1]) >= 5:
                self._box_dragged = True
                self.keys.clear()
                self.setCursor(Qt.CrossCursor)
            self.interaction_overlay.update()
            event.accept()
            return
        if not self.right_mouse_down:
            gizmo = self.gizmo()
            handle = gizmo.hit(point) if gizmo is not None else None
            self.hover_handle = handle.key if handle is not None else None
            self.setCursor(Qt.SizeAllCursor if handle is not None else Qt.ArrowCursor)
            self.interaction_overlay.update()
            return

        center = self.rect().center()

        dx = (
            event.position().x()
            - center.x()
        )

        dy = (
            center.y()
            - event.position().y()
        )

        # Ignore the artificial mouse event caused
        # by QCursor.setPos().
        if self.ignore_center_event:
            # Consume the synthetic recentering move event.
            self.ignore_center_event = False
            return

        if (
            abs(dx) <= 1
            and abs(dy) <= 1
        ):
            return

        self.camera.rotate(
            dx,
            dy
        )
        self.request_frame()

        # Mark the next recentering move event as synthetic.
        self.ignore_center_event = True

        self.center_mouse()

    def center_mouse(self):
        """Re-center the system cursor within the viewport to keep drag rotation stable."""
        center = self.rect().center()

        global_center = self.mapToGlobal(
            QPoint(
                center.x(),
                center.y()
            )
        )

        QCursor.setPos(
            global_center
        )

    def RenderRay(self, position, direction, length=100.0):
        """Queue a debug ray from origin to direction * length for the next paint."""
        ray = Ray(position, direction)
        self.debug_ray = ray.render(length)
        self.update()
        return ray
