from pathlib import Path
import math
import time
import ctypes

import glm
import numpy as np

from OpenGL.GL import *
from OpenGL.GL.shaders import compileProgram, compileShader

from PySide6.QtOpenGLWidgets import QOpenGLWidget
from PySide6.QtCore import Qt, QTimer, QPoint
from PySide6.QtGui import QCursor


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

    vec3 base_color =
        vec3(0.72, 0.76, 0.82);

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

def loadObjFlatShaded(filename):
    positions = []
    output = []

    with open(
        filename,
        "r",
        encoding="utf-8",
        errors="ignore"
    ) as file:

        for line in file:
            data = line.split()

            if not data:
                continue

            if data[0] == "v":
                positions.append(
                    np.array(
                        [
                            float(data[1]),
                            float(data[2]),
                            float(data[3]),
                        ],
                        dtype=np.float32,
                    )
                )

            elif data[0] == "f":
                indices = []

                for token in data[1:]:
                    vertex_index = int(
                        token.split("/")[0]
                    )

                    if vertex_index < 0:
                        vertex_index = (
                            len(positions)
                            + vertex_index
                        )
                    else:
                        vertex_index -= 1

                    indices.append(
                        vertex_index
                    )

                # Convert polygon faces to triangles.
                for i in range(
                    1,
                    len(indices) - 1
                ):
                    p0 = positions[
                        indices[0]
                    ]

                    p1 = positions[
                        indices[i]
                    ]

                    p2 = positions[
                        indices[i + 1]
                    ]

                    edge1 = p1 - p0
                    edge2 = p2 - p0

                    normal = np.cross(
                        edge1,
                        edge2
                    )

                    length = np.linalg.norm(
                        normal
                    )

                    if length > 0.0:
                        normal = (
                            normal / length
                        )
                    else:
                        normal = np.array(
                            [0.0, 1.0, 0.0],
                            dtype=np.float32,
                        )

                    for point in (
                        p0,
                        p1,
                        p2
                    ):
                        output.extend(
                            [
                                point[0],
                                point[1],
                                point[2],
                                normal[0],
                                normal[1],
                                normal[2],
                            ]
                        )

    return np.asarray(
        output,
        dtype=np.float32,
    )


class Camera:
    def __init__(self):
        
        
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
        return glm.lookAt(
            self.position,
            self.position
            + self.front,
            self.up,
        )


class OpenGLViewport(QOpenGLWidget):
    def __init__(
        self,
        parent=None,
        scene=None,
        
    ):
        
        self.axisShader = None
        self.axisVAO = None
        self.axisVBO = None
        self.axisVertexCount = 0
        super().__init__(
            parent
        )
        self.ignore_center_event = False
        self.scene = scene

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


    def addNewObject(self, object):
        meshPath = Path(
            object.meshPath
        )
        self.makeCurrent()
        
        if not meshPath.exists():
            self.doneCurrent()
            raise FileNotFoundError(

                f"Could not find OBJ at {meshPath}"
            )


        vertexData = loadObjFlatShaded(meshPath)

        vertexCount = (
            len(vertexData) // 6
        )

        print(
            f"Loaded {vertexCount:,} vertices for {object.name}"
        )

        vao = glGenVertexArrays(1)

        glBindVertexArray(
            vao
        )

        vbo = glGenBuffers(1)

        glBindBuffer(
            GL_ARRAY_BUFFER,
            vbo
        )
        glBufferData(
            GL_ARRAY_BUFFER,
            vertexData.nbytes,
            vertexData,
            GL_STATIC_DRAW,
        )

        stride = (
            6 * vertexData.itemsize
        )
        
        glEnableVertexAttribArray(
            0
        )
        glVertexAttribPointer(
            0,
            3,
            GL_FLOAT,
            GL_FALSE,
            stride,
            ctypes.c_void_p(0)
        )

        # Normal 
        glEnableVertexAttribArray(1)
        
        glVertexAttribPointer(
            1,
            3,
            GL_FLOAT,
            GL_FALSE,
            stride,
            ctypes.c_void_p(
                3 * vertexData.itemsize
            )
        )

        glBindVertexArray(0)
        self.renderObjects.append({
            "SceneObject": object,
            "vao": vao,
            "vbo": vbo,
            "vertexCount": vertexCount
        })
        
        self.doneCurrent()
        self.update()   
    def initializeGL(self):
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

        self.shader = compileProgram(
            compileShader(
                VERTEX_SHADER,
                GL_VERTEX_SHADER
            ),
            compileShader(
                FRAGMENT_SHADER,
                GL_FRAGMENT_SHADER
            ),
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
                
                meshPath = Path(sceneObject.meshPath)
                
                if not meshPath.exists():
                    raise FileNotFoundError(
                        f"Could not find OBJ at {meshPath}"
                    )
                    continue 
                
                vertexData = loadObjFlatShaded(meshPath)
                
                vertexCount = (
                    len(vertexData) // 6
                )
                
                print(
                    f"Loaded {vertexCount:,} vertices for {sceneObject.name}"
                )
                vao = glGenVertexArrays(1)
                
                glBindVertexArray(vao)
                
                vbo = glGenBuffers(1)
                
                glBindBuffer(
                    GL_ARRAY_BUFFER,
                    vbo
                )
                glBufferData(
                    GL_ARRAY_BUFFER,
                    vertexData.nbytes,
                    vertexData,
                    GL_STATIC_DRAW,
                )
                
                stride = (
                    6 * vertexData.itemsize
                    
                )
                glEnableVertexAttribArray(
                    0
                )

                glVertexAttribPointer(
                    0,
                    3,
                    GL_FLOAT,
                    GL_FALSE,
                    stride,
                    ctypes.c_void_p(0)
                )
                glEnableVertexAttribArray(1)
                
                
                glVertexAttribPointer(
                    1,
                    3,
                    GL_FLOAT,
                    GL_FALSE,
                    stride,
                    ctypes.c_void_p(
                        3*vertexData.itemsize
                    )
                    )
                
                glBindVertexArray(0)
                
                self.renderObjects.append({
                    "SceneObject": sceneObject,
                    "vao": vao,
                    "vbo": vbo,
                    "vertexCount": vertexCount
                }   
                )
                
        print(
            "OpenGL viewport initialized"
        )
        

    def resizeGL(
        self,
        width,
        height
    ):
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

            model = glm.mat4(
                1.0
            )

            model = glm.translate(
                model,
                glm.vec3(
                    *sceneObject.position
                )
            )

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




    # ---------------------------------------------------------
    # CAMERA INPUT
    # ---------------------------------------------------------

    def update_camera(
        self,
        delta_time
    ):
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
        self.keys.discard(
            event.key()
        )

    def mousePressEvent(self, event):
        if event.button() == Qt.RightButton:
            self.right_mouse_down = True

            self.setCursor(Qt.BlankCursor)

            self.grabMouse()
            self.setFocus()

            self.ignore_center_event = True
            self.center_mouse()
    def mouseReleaseEvent(self, event):
        if event.button() == Qt.RightButton:
            self.right_mouse_down = False

            self.ignore_center_event = False

            self.releaseMouse()
            self.unsetCursor()
            
    def mouseMoveEvent(self, event):
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
        
