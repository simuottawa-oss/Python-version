"""OpenGL rendering pipeline for the SimuO 3D editor.

This module loads OBJ meshes, builds transformation matrices, and renders scene
objects in a Qt-based OpenGL viewport.
"""

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

def loadObjFlatShaded(filename):
    """Load a Wavefront OBJ file and convert it to flat-shaded OpenGL vertex data.

    Args:
        filename: Path to the OBJ mesh file.

    Returns:
        numpy.ndarray: Interleaved position and normal data for each triangle.
    """
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
    """Represents the viewer's position and orientation in the 3D scene. Only tracks position and orientation."""

    def __init__(self):
        """Initialize the camera at a default viewing position.

        The camera starts facing down the negative Z axis with a standard world-up
        vector and recalculates its orientation vectors.
        """
        # Camera pose state.
        self.position = glm.vec3(
            0.0,
            2.0,
            28.0
        )

        # Euler orientation state.
        self.yaw = -90.0
        self.pitch = 0.0

        # World reference vector used to rebuild the camera basis.
        self.world_up = glm.vec3(
            0.0,
            1.0,
            0.0
        )

        # Initial forward-facing direction.
        self.front = glm.vec3(
            0.0,
            0.0,
            -1.0
        )

        # Initial right-facing direction.
        self.right = glm.vec3(
            1.0,
            0.0,
            0.0
        )

        # Initial up-facing direction.
        self.up = glm.vec3(
            0.0,
            1.0,
            0.0
        )

        self.update_vectors()

    def update_vectors(self):
        """Recompute camera direction vectors from yaw and pitch.

        This updates the front, right, and up vectors used for movement and view
        matrix construction.
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

        # Refresh the camera basis vectors after orientation changes.
        self.front = glm.normalize(
            front
        )

        # Rebuild the right vector from the updated forward direction.
        self.right = glm.normalize(
            glm.cross(
                self.front,
                self.world_up
            )
        )

        # Rebuild the up vector from the updated basis.
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
        """Rotate the camera based on mouse movement.

        Args:
            dx: Horizontal mouse movement delta.
            dy: Vertical mouse movement delta.
            sensitivity: Mouse sensitivity multiplier.
        """
        # Apply mouse motion to the persistent yaw state.
        self.yaw += (
            dx * sensitivity
        )

        # Apply mouse motion to the persistent pitch state.
        self.pitch += (
            dy * sensitivity
        )

        # Keep pitch inside the safe range before rebuilding vectors.
        self.pitch = max(
            -89.0,
            min(
                89.0,
                self.pitch
            )
        )

        self.update_vectors()

    def view_matrix(self):
        """Build the OpenGL view matrix for the current camera orientation.

        Returns:
            glm.mat4: The camera view matrix used by the scene renderer.
        """
        return glm.lookAt(
            self.position,
            self.position
            + self.front,
            self.up,
        )

    def mouse_ray(self, event, width, height, projection, view):
        """Creates a ray from global mouse position and casts a ray to projected view location
        
        Arguments:
            event Obj: mouse tracking
            width integer(i think?): openGl viewport width
            height integer
            projection glm.mat4: projection matrix as glm.perspective data
            view ... : camera view matrix
        
        """
    
        """
        projection and view matrices convert numpy.array 
        O(1) btw
        """

        #Normal device coordinates, so where the mouse is
        x_ndc = (2.0 * event.position().x() / width) - 1.0
        y_ndc = 1.0 - (2.0 * event.position().y() / height)


        #floating types ftw
        clip = np.array([x_ndc, y_ndc, -1.0, 1.0], dtype=np.float32)

        inv_projection = np.linalg.inv(np.array(projection, dtype=np.float32))
        near = inv_projection @ clip
        near = near / near[3]

        inv_view = np.linalg.inv(np.array(view, dtype=np.float32))
        near_world = inv_view @ near
        near_world = near_world[:3]

        origin = self.position
        direction = glm.normalize(glm.vec3(near_world) - origin)

        return origin, direction


    
       


class OpenGLViewport(QOpenGLWidget):
    """Qt widget that renders the 3D scene and handles camera interaction.

    Camera interaction here means the user is effectively piloting a first-person
    camera through the scene. The camera has a position and a local basis
    (forward/right/up) derived from yaw and pitch, and input changes that basis
    or the camera's world position.

    Keyboard movement is relative to the current camera orientation:
    - W/S move along the camera's forward vector
    - A/D strafe left/right along the camera's right vector
    - Space/Ctrl move vertically along the world's up vector

    Mouse interaction is used for looking around the scene. While the right mouse
    button is held, the cursor is recentered inside the widget so the user can
    drag continuously without the pointer leaving the viewport. Horizontal motion
    changes yaw and vertical motion changes pitch, producing a look-around feel
    similar to a free-fly viewer.
    """

    def __init__(
        self,
        parent=None,
        scene=None,
        
    ):
        # OpenGL axis helper state.
        self.axisShader = None
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

        # Cached uniform locations for the main shader.
        self.model_location = None
        self.view_location = None
        self.projection_location = None
        self.camera_location = None

        # Frame timing state.
        self.last_time = (
            time.perf_counter()
        )

        # Repaint timer used to drive continuous updates.
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
        
    def addNewObject(self, object):
        """Load a SceneObject mesh into GPU memory and add it to the viewport.

        Args:
            object: SceneObject instance whose mesh should be uploaded.

        Raises:
            FileNotFoundError: If the OBJ file does not exist.
        """
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
        )

        # Cache the main shader uniform locations.
        self.model_location = (
            glGetUniformLocation(
                self.shader,
                "model"
            )
        )

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

        axisData = createAxisLines(-2000,2000)
        
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
                
                # Cache the GPU-backed render object for later drawing and cleanup.
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

        This method updates the camera, clears the framebuffer, calculates the
        projection and view matrices, and draws both the axis helper and scene
        objects.
        """
        current_time = (
            time.perf_counter()
        )

        # Update the frame timer state before camera motion is applied.
        delta_time = (
            current_time
            - self.last_time
        )

        # Store the current frame time for the next update.
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

        if Qt.Key_Control in self.keys:
            self.camera.position -= (
                self.camera.world_up
                * speed
            )

    def keyPressEvent(
        self,
        event
    ):
        """Track key presses and close the app when Escape is pressed.

        Args:
            event: Qt keyboard event.
        """
        # Add the pressed key to the active input set.
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
        """Remove a key from the active input set when released.

        Args:
            event: Qt keyboard event.
        """
        # Remove the released key from the active input set.
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
        if event.button() == Qt.LeftButton:
            x = event.position().x()
            y = event.position().y()

            width = max(1, self.width())
            height = max(1, self.height())

            projection = glm.perspective(
                glm.radians(60.0),
                width / height,
                0.1,
                1000.0,
            )

            view = self.camera.view_matrix()

            origin, direction = self.camera.mouse_ray(
                event,
                width,
                height,
                projection,
                view
            )

            # RenderRay is paused for now. Keep the ray-generation logic active,
            # but do not draw the debug line while the feature is under pause.
            # OpenGLViewport.RenderRay(origin, direction, 100)

            print("click ray:", origin, direction)
            # later: intersect against scene objects here

        elif event.button() == Qt.RightButton:
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
        """Paused for now: debug ray rendering is temporarily disabled.

        This function is intentionally left inactive so the rest of the viewport
        camera and input pipeline can continue running without the ray debug path
        interfering with the app.
        """
        # Paused: render-debug ray drawing is temporarily disabled.
        # end = position + direction * length
        # glBegin(GL_LINES)
        # glVertex3f(position.x, position.y, position.z)
        # glVertex3f(end.x, end.y, end.z)
        # glEnd()
        return None
