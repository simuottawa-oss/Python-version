"""OpenGL rendering pipeline for the SimuO 3D editor.

This module loads OBJ meshes, builds transformation matrices, and renders scene
objects in a Qt-based OpenGL viewport.
"""
import math
import sys
import time
import ctypes

import glm
import numpy as np

from OpenGL.GL import *
from OpenGL.GL.shaders import compileProgram, compileShader

from PySide6.QtOpenGLWidgets import QOpenGLWidget
from PySide6.QtCore import Qt, QTimer, QPoint
from PySide6.QtGui import QCursor

from simuo.physics.viewport.ray import Ray
from simuo.physics.viewport.mover import Mover
from simuo.parts.part_assets import loadObjFlatShaded  # Compatibility export for existing callers


GIZMO_VERTEX_SHADER = """
#version 330 core

layout (location = 0) in vec3 in_position;

uniform mat4 view;
uniform mat4 projection;

void main()
{
    gl_Position = projection * view * vec4(in_position, 1.0);
}
"""

GIZMO_FRAGMENT_SHADER = """
#version 330 core

uniform vec3 color;

out vec4 frag_color;

void main()
{
    frag_color = vec4(color, 1.0);
}
"""

DEBUG_RAY_VERTEX_SHADER = """
#version 330 core

layout (location = 0) in vec3 in_position;

uniform mat4 view;
uniform mat4 projection;

void main()
{
    gl_Position = projection * view * vec4(in_position, 1.0);
}
"""

DEBUG_RAY_FRAGMENT_SHADER = """
#version 330 core

out vec4 frag_color;

void main()
{
    frag_color = vec4(1.0, 0.15, 0.15, 1.0);
}
"""

AXIS_VERTEX_SHADER = """
#version 330 core

layout (location = 0) in vec3 in_position;

uniform mat4 view;
uniform mat4 projection;

void main()
{
    gl_Position =
        projection
        * view
        * vec4(in_position, 1.0);
}
"""

AXIS_FRAGMENT_SHADER = """
#version 330 core

out vec4 frag_color;

void main()
{
    frag_color = vec4(
        0.8,
        0.8,
        0.8,
        1.0
    );
}
"""

VERTEX_SHADER = """
#version 330 core

layout (location = 0) in vec3 in_position;
layout (location = 1) in vec3 in_normal;

uniform mat4 model;
uniform mat4 view;
uniform mat4 projection;

out vec3 frag_position;
out vec3 frag_normal;

void main()
{
    vec4 world_position = model * vec4(in_position, 1.0);

    frag_position = world_position.xyz;
    frag_normal = mat3(transpose(inverse(model))) * in_normal;

    gl_Position = projection * view * world_position;
}
"""


FRAGMENT_SHADER = """
#version 330 core

in vec3 frag_position;
in vec3 frag_normal;

uniform vec3 camera_position;
uniform vec3 base_color;

out vec4 frag_color;

void main()
{
    vec3 normal = normalize(frag_normal);

    vec3 light_direction =
        normalize(camera_position - frag_position);

    float diffuse =
        max(dot(normal, light_direction), 0.0);

    float ambient = 0.18;

    float brightness =
        min(ambient + diffuse * 0.82, 1.0);

    frag_color =
        vec4(base_color * brightness, 1.0);
}
"""
def createAxisLines(
    minimum=-2000,
    maximum=2000
    ,
    tickSize=0.15
):
    """Generate three world axes with integer-spaced tick marks for GL_LINES.

    Args:
        minimum (int): Lowest world-axis coordinate and first integer tick.
        maximum (int): Highest world-axis coordinate and last integer tick, inclusive.
        tickSize (float): Half-length of each axis tick in world units.

    Returns:
        numpy.ndarray: Flat float32 XYZ positions, two vertices per line segment.
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

class Camera:
    def __init__(self):
        
        
        """Initialize camera position and Euler view angles, then compute its viewing
        basis.

        Returns:
            None.
        """
        self.position = glm.vec3(
            0.0,
            2.0,
            28.0
        )

        self.yaw = -90.0
        self.pitch = 0.0

        self.world_up = glm.vec3(
            0.0,
            1.0,
            0.0
        )

        self.front = glm.vec3(
            0.0,
            0.0,
            -1.0
        )

        self.right = glm.vec3(
            1.0,
            0.0,
            0.0
        )

        self.up = glm.vec3(
            0.0,
            1.0,
            0.0
        )

        self.update_vectors()

    def update_vectors(self):
        """Recompute normalized forward, right, and up vectors from yaw/pitch in degrees.

        Returns:
            None. Mutates the camera basis.
        """
        yaw = math.radians(
            self.yaw
        )

        pitch = math.radians(
            self.pitch
        )

        front = glm.vec3(
            math.cos(yaw)
            * math.cos(pitch),

            math.sin(pitch),

            math.sin(yaw)
            * math.cos(pitch),
        )

        self.front = glm.normalize(
            front
        )

        self.right = glm.normalize(
            glm.cross(
                self.front,
                self.world_up
            )
        )

        self.up = glm.normalize(
            glm.cross(
                self.right,
                self.front
            )
        )

    def rotate(
        self,
        dx,
        dy,
        sensitivity=0.12
    ):
        """Apply pointer deltas to yaw/pitch, clamp pitch to avoid flipping, and rebuild
        the basis.

        Args:
            dx (float): Horizontal pointer displacement in pixels.
            dy (float): Vertical pointer displacement in pixels, positive for upward
                look.
            sensitivity (float): Degrees of rotation per pointer pixel.

        Returns:
            None. Mutates camera angles and vectors.
        """
        self.yaw += (
            dx * sensitivity
        )

        self.pitch += (
            dy * sensitivity
        )

        self.pitch = max(
            -89.0,
            min(
                89.0,
                self.pitch
            )
        )

        self.update_vectors()

    def view_matrix(self):
        """Build the camera's world-to-view transform from position and basis.

        Returns:
            glm.mat4: Look-at view matrix.
        """
        return glm.lookAt(
            self.position,
            self.position
            + self.front,
            self.up,
        )


    def mouse_ray(self, event, width, height, projection, view):
        """Unproject a pointer location into a normalized world-space camera ray.

        Args:
            event: Qt mouse event with a widget-local position in logical pixels.
            width: Positive viewport width in logical pixels.
            height: Positive viewport height in logical pixels.
            projection: Perspective projection matrix matching the rendered view.
            view: Camera world-to-view matrix.

        Returns:
            tuple: Camera origin and normalized direction as glm.vec3 values.
        """
        x_ndc = 2.0 * event.position().x() / width - 1.0
        y_ndc = 1.0 - 2.0 * event.position().y() / height
        clip = np.array([x_ndc, y_ndc, -1.0, 1.0], dtype=np.float32)
        inv_projection = np.linalg.inv(np.array(projection, dtype=np.float32))
        near = inv_projection @ clip
        near = near / near[3]
        inv_view = np.linalg.inv(np.array(view, dtype=np.float32))
        near_world = inv_view @ near
        near_world = near_world[:3]
        origin = self.position
        direction = glm.normalize(glm.vec3(near_world) - origin)
        return (origin, direction)


class OpenGLViewport(QOpenGLWidget):
    def __init__(
        self,
        parent=None,
        scene=None,
        read_only=False,
    ):

            
        
        """Initialize viewport input/camera state and a repaint timer; GPU allocation is
        deferred until initializeGL.

        Args:
            parent (widget, optional): Owning Qt or Tk widget; None creates an
                independent Qt widget.
            scene (Scene, optional): Scene to display/use; None uses the constructor's
                empty or unbound default.
            read_only (bool): Disable object picking, gizmos, and manipulation while
                retaining camera navigation.

        Returns:
            None.
        """
        self.mover = None
        self.selectedObject = None
        self.gizmoShader = None
        self.gizmo_vao = None
        self.gizmo_vbo = None
        self.axisShader = None
        self.debugRayShader = None
        self.debug_ray = None
        self.debug_ray_vao = None
        self.debug_ray_vbo = None
        self.axisVAO = None
        self.axisVBO = None
        self.axisVertexCount = 0
        super().__init__(
            parent
        )
        self.ignore_center_event = False
        self.scene = scene
        self.read_only = read_only

        self.setFocusPolicy(
            Qt.StrongFocus
        )

        self.setMouseTracking(
            True
        )

        self.camera = Camera()

        self.keys = set()

        self.right_mouse_down = False
        self.last_mouse_position = None

        self.shader = None
        self.renderObjects = []


        self.model_location = None
        self.view_location = None
        self.projection_location = None
        self.camera_location = None

        self.last_time = (
            time.perf_counter()
        )

        self.timer = QTimer(
            self
        )

        self.timer.timeout.connect(
            self.update
        )

        # ~120 repaint requests/sec.
        self.timer.start(
            8
        )

    # ---------------------------------------------------------
    # OPENGL SETUP
    # ---------------------------------------------------------

            
    def clearRenderObjects(self):
        """Acquire the GL context, delete all uploaded object VAOs/VBOs, clear render
        records, and repaint.

        Returns:
            None. Leaves the CPU scene and axis resources intact.
        """
        self.mover = None
        self.selectedObject = None
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

        self.renderObjects.clear()

        self.doneCurrent()

        self.update()
        
    def removeObject(self, sceneObject):
        """Release uploaded buffers for an instance using the current widget context and
        remove its render records.

        Args:
            sceneObject (SceneObject): Instance to display, remove, or edit.

        Returns:
            None. Leaves the CPU scene list unchanged and schedules a repaint.
        """
        if self.selectedObject is sceneObject:
            self.mover = None
            self.selectedObject = None
        removed = [obj for obj in self.renderObjects if obj["SceneObject"] is sceneObject]
        if removed:
            self.makeCurrent()
            try:
                for obj in removed:
                    glDeleteVertexArrays(1, [obj["vao"]])
                    glDeleteBuffers(1, [obj["vbo"]])
                    self.renderObjects.remove(obj)
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
            "vertexCount": len(vertexData) // 6,
        })
        print(f"Loaded {len(vertexData) // 6:,} vertices for {sceneObject.name}")

    def addNewObject(self, sceneObject):
        """Acquire the viewport's GL context, upload one instance, then schedule repaint.

        Args:
            sceneObject (SceneObject): Instance to display, remove, or edit.

        Returns:
            None. Adds GPU render records without adding the instance to the scene list.
        """
        self.makeCurrent()
        try:
            self._uploadObject(sceneObject)
        finally:
            self.doneCurrent()
        self.update()

    def frameObject(self, sceneObject):
        """Position the camera around scaled/translated local mesh bounds so SI-sized
        assets are visible without resizing them. Bounds do not include instance
        rotation.

        Args:
            sceneObject (SceneObject): Instance to display, remove, or edit.

        Returns:
            None. Updates camera position/orientation and repaints.
        """
        points = sceneObject.asset.vertices.reshape(-1, 6)[:, :3]
        low, high = points.min(axis=0), points.max(axis=0)
        center = (low + high) / 2 * np.asarray(sceneObject.scale)
        radius = float(np.linalg.norm((high-low) * np.asarray(sceneObject.scale))) / 2
        distance = max(0.5, radius * 3)
        target = glm.vec3(*(center + np.asarray(sceneObject.position)))
        self.camera.position = target + glm.vec3(0, distance * 0.35, distance)
        self.camera.yaw = -90.0
        self.camera.pitch = -math.degrees(math.atan(0.35))
        self.camera.update_vectors()
        self.update()

    def initializeGL(self):
        """Enable depth testing, compile shaders, create axis buffers, and upload existing
        scene assets under Qt's current GL context.

        Returns:
            None. Initializes GPU handles and cached uniform locations.
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

        # On macOS, Qt has not finished setting up the draw framebuffer here.
        # Compile and link now without validating against incomplete GL state.
        validate_program = sys.platform != "darwin"

        self.shader = compileProgram(
            compileShader(
                VERTEX_SHADER,
                GL_VERTEX_SHADER
            ),
            compileShader(
                FRAGMENT_SHADER,
                GL_FRAGMENT_SHADER
            ),
            validate=validate_program,
        )
        
        self.axisShader = compileProgram(
            compileShader(
                AXIS_VERTEX_SHADER,
                GL_VERTEX_SHADER
            ),
            compileShader(
                AXIS_FRAGMENT_SHADER,
                GL_FRAGMENT_SHADER
            ),
            validate=validate_program,
        )

        self.model_location = (
            glGetUniformLocation(
                self.shader,
                "model"
            )
        )

        self.view_location = (
            glGetUniformLocation(
                self.shader,
                "view"
            )
        )

        self.projection_location = (
            glGetUniformLocation(
                self.shader,
                "projection"
            )
        )

        self.camera_location = (
            glGetUniformLocation(
                self.shader,
                "camera_position"
            )
        )

        self.color_location = glGetUniformLocation(self.shader, "base_color")

        axisData = createAxisLines(-2000,2000)
        
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

        if self.scene is not None:
            for sceneObject in self.scene.objects:
                self._uploadObject(sceneObject)

        print(
            "OpenGL viewport initialized"
        )

        self.debugRayShader = compileProgram(
            compileShader(DEBUG_RAY_VERTEX_SHADER, GL_VERTEX_SHADER),
            compileShader(DEBUG_RAY_FRAGMENT_SHADER, GL_FRAGMENT_SHADER),
            validate=validate_program,
        )
        if self.debug_ray_vao is None:
            self.debug_ray_vao = glGenVertexArrays(1)
            self.debug_ray_vbo = glGenBuffers(1)

        self.gizmoShader = compileProgram(
            compileShader(GIZMO_VERTEX_SHADER, GL_VERTEX_SHADER),
            compileShader(GIZMO_FRAGMENT_SHADER, GL_FRAGMENT_SHADER),
            validate=validate_program,
        )
        if self.gizmo_vao is None:
            self.gizmo_vao = glGenVertexArrays(1)
            self.gizmo_vbo = glGenBuffers(1)
        

    def resizeGL(
        self,
        width,
        height
    ):
        """Set the physical-pixel GL viewport using the widget's device-pixel ratio.

        Args:
            width (int): Widget/window width in logical pixels.
            height (int): Widget/window height in logical pixels.

        Returns:
            None. Updates GL viewport dimensions with a minimum of one pixel.
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
        """Update camera movement, clear buffers, and draw axes and uploaded triangles
        using current instance transforms and colors.

        Returns:
            None. Draws one frame; geometry remains in static GPU buffers.
        """
        current_time = (
            time.perf_counter()
        )

        delta_time = (
            current_time
            - self.last_time
        )

        self.last_time = (
            current_time
        )

        delta_time = min(
            delta_time,
            0.1
        )

        self.update_camera(
            delta_time
        )

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
                60.0
            ),
            aspect,
            0.1,
            1000.0,
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

            glUniform3f(self.color_location, *sceneObject.asset.color)

            model = glm.mat4(
                1.0
            )

            model = glm.translate(
                model,
                glm.vec3(
                    *sceneObject.position
                )
            )


            # X rotation
            model = glm.rotate(
                model,
                glm.radians(
                    sceneObject.rotation[0]
                ),
                glm.vec3(
                    1.0,
                    0.0,
                    0.0
                )
            )
            # Y rotation
            model = glm.rotate(
                model,
                glm.radians(
                    sceneObject.rotation[1]
                ),
                glm.vec3(
                    0.0,
                    1.0,
                    0.0
                )
            )
            # Z rotation
            model = glm.rotate(
                model,
                glm.radians(
                    sceneObject.rotation[2]
                ),
                glm.vec3(
                    0.0,
                    0.0,
                    1.0
                )
            )

            model = glm.scale(
                model,
                glm.vec3(
                    *sceneObject.scale
                )
            )

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

        if self.debug_ray is not None:
            glUseProgram(self.debugRayShader)
            debugViewLocation = glGetUniformLocation(self.debugRayShader, 'view')
            debugProjectionLocation = glGetUniformLocation(self.debugRayShader, 'projection')
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

        if not self.read_only and self.mover is not None:
            vertex_data, segments = self.mover.build_render_data()
            glDisable(GL_DEPTH_TEST)
            glUseProgram(self.gizmoShader)
            gizmoViewLocation = glGetUniformLocation(self.gizmoShader, 'view')
            gizmoProjectionLocation = glGetUniformLocation(self.gizmoShader, 'projection')
            gizmoColorLocation = glGetUniformLocation(self.gizmoShader, 'color')
            glUniformMatrix4fv(gizmoViewLocation, 1, GL_FALSE, glm.value_ptr(view))
            glUniformMatrix4fv(gizmoProjectionLocation, 1, GL_FALSE, glm.value_ptr(projection))
            glBindVertexArray(self.gizmo_vao)
            glBindBuffer(GL_ARRAY_BUFFER, self.gizmo_vbo)
            glBufferData(GL_ARRAY_BUFFER, vertex_data.nbytes, vertex_data, GL_DYNAMIC_DRAW)
            glEnableVertexAttribArray(0)
            glVertexAttribPointer(0, 3, GL_FLOAT, GL_FALSE, 3 * vertex_data.itemsize, ctypes.c_void_p(0))
            for name, color, start_vertex, vertex_count in segments:
                r, g, b = color
                if name == self.mover.hovered_axis:
                    r, g, b = (min(r + 0.3, 1.0), min(g + 0.3, 1.0), min(b + 0.3, 1.0))
                glUniform3f(gizmoColorLocation, r, g, b)
                glDrawArrays(GL_TRIANGLES, start_vertex, vertex_count)
            glBindVertexArray(0)
            glUseProgram(0)
            glEnable(GL_DEPTH_TEST)




    # ---------------------------------------------------------
    # CAMERA INPUT
    # ---------------------------------------------------------

    def update_camera(
        self,
        delta_time
    ):
        """Move and turn the camera from held keys, scaling speeds by elapsed time.

        Args:
            delta_time (float): Elapsed frame time in seconds used to scale movement.

        Returns:
            None. Updates camera position and viewing basis.
        """
        turn = int(Qt.Key_Right in self.keys) - int(Qt.Key_Left in self.keys)
        if turn:
            self.camera.yaw += turn * 90.0 * delta_time
            self.camera.update_vectors()

        speed = (
            10.0
            * delta_time
        )

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

        if Qt.Key_Space in self.keys:
            self.camera.position += (
                self.camera.world_up
                * speed
            )

        if Qt.Key_Control in self.keys:
            self.camera.position -= (
                self.camera.world_up
                * speed
            )

    def keyPressEvent(
        self,
        event
    ):
        """Track a pressed key for continuous movement and request window closure on
        Escape.

        Args:
            event (Qt event): Input, paint, resize, focus, or close event delivered by
                the framework.

        Returns:
            None. Mutates held-key state.
        """
        self.keys.add(
            event.key()
        )

        if (
            event.key()
            == Qt.Key_Escape
        ):
            self.window().close()

    def keyReleaseEvent(
        self,
        event
    ):
        """Remove a released key from held state, ignoring synthetic auto-repeat releases.

        Args:
            event (Qt event): Input, paint, resize, focus, or close event delivered by
                the framework.

        Returns:
            None.
        """
        if event.isAutoRepeat():
            return
        self.keys.discard(
            event.key()
        )

    def focusOutEvent(self, event):
        # File dialogs and switching applications can swallow key-up events.
        """Clear held keys and release mouse capture/cursor hiding when the viewport loses
        focus.

        Args:
            event (Qt event): Input, paint, resize, focus, or close event delivered by
                the framework.

        Returns:
            None. Delegates the focus event after resetting input state.
        """
        self.keys.clear()
        if self.mover is not None and self.mover.dragging_axis is not None:
            self.mover.end_drag()
        if self.right_mouse_down:
            self.right_mouse_down = False
            self.ignore_center_event = False
            self.releaseMouse()
            self.unsetCursor()
        super().focusOutEvent(event)

    def mousePressEvent(self, event):
        """Pick a part or movement arrow on left click; capture mouse look on right click.

        Args:
            event: Qt mouse event containing the button and logical-pixel position.

        Returns:
            None. Updates selection/drag state or captures the pointer for mouse look.
        """
        if event.button() == Qt.LeftButton and not self.read_only:
            width, height = max(1, self.width()), max(1, self.height())
            projection = glm.perspective(glm.radians(60.0), width / height, 0.1, 1000.0)
            origin, direction = self.camera.mouse_ray(
                event, width, height, projection, self.camera.view_matrix()
            )
            if self.mover is not None:
                axis = self.mover.hit_test(origin, direction)
                if axis is not None:
                    self.mover.begin_drag(axis, origin, direction)
                    return
            ray = self.RenderRay(origin, direction, 100.0)
            objects = self.scene.objects if self.scene is not None else []
            hit = ray.checkCollisions(obj for obj in objects if obj.name != "Axis")
            self.selectedObject = hit["object"] if hit is not None else None
            self.mover = Mover(self.selectedObject) if self.selectedObject is not None else None
            self.update()
        elif event.button() == Qt.RightButton:
            self.right_mouse_down = True
            self.setCursor(Qt.BlankCursor)
            self.grabMouse()
            self.setFocus()
            self.ignore_center_event = True
            self.center_mouse()
    def mouseReleaseEvent(self, event):
        """End a movement-arrow drag or release captured right-button mouse look.

        Args:
            event (Qt event): Input, paint, resize, focus, or close event delivered by
                the framework.

        Returns:
            None.
        """
        if event.button() == Qt.RightButton:
            self.right_mouse_down = False

            self.ignore_center_event = False

            self.releaseMouse()
            self.unsetCursor()

        if event.button() == Qt.LeftButton and not self.read_only and self.mover is not None:
            if self.mover.dragging_axis is not None:
                self.mover.end_drag()
            
    def mouseMoveEvent(self, event):
        """Drag the selected part, update arrow hover, or rotate captured mouse look.

        Args:
            event (Qt event): Input, paint, resize, focus, or close event delivered by
                the framework.

        Returns:
            None. Updates a selected part and dirty state, or the camera and pointer.
        """
        if not getattr(self, "read_only", False) and self.mover is not None:
            width, height = max(1, self.width()), max(1, self.height())
            projection = glm.perspective(glm.radians(60.0), width / height, 0.1, 1000.0)
            origin, direction = self.camera.mouse_ray(
                event, width, height, projection, self.camera.view_matrix()
            )
            if self.mover.dragging_axis is not None:
                before = list(self.mover.scene_object.position)
                self.mover.update_drag(origin, direction)
                if self.scene is not None and self.mover.scene_object.position != before:
                    self.scene.dirty = True
                self.update()
                return
            self.mover.hovered_axis = self.mover.hit_test(origin, direction)
            self.update()

        if not self.right_mouse_down:
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

        self.ignore_center_event = True

        self.center_mouse()
        
    def center_mouse(self):
        """Warp the system pointer to the widget center in global screen coordinates.

        Returns:
            None. Changes the desktop cursor position.
        """
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
        """Queue a world-space ray visualization for the next frame.

        Args:
            position: World XYZ ray origin in metres.
            direction: World XYZ direction; camera rays are normalized.
            length: Distance parameter in metres for a normalized direction.

        Returns:
            Ray: Queued ray; also updates float32 line data and requests repaint.
        """
        ray = Ray(position, direction)
        self.debug_ray = ray.render(length)
        self.update()
        return ray
        
