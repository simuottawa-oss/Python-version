"""

Controls
--------
WASD               Move
Right mouse + move Look around
Space              Move up
Left Ctrl          Move down
Esc                Close

"""

from pathlib import Path
import math
import time

import glfw
import glm
import moderngl
import numpy as np


WINDOW_WIDTH = 1280
WINDOW_HEIGHT = 720

MOVE_SPEED = 10.0
MOUSE_SENSITIVITY = 0.12


VERTEX_SHADER = """
#version 330

in vec3 in_position;
in vec3 in_normal;

uniform mat4 model;
uniform mat4 view;
uniform mat4 projection;

out vec3 frag_position;
out vec3 frag_normal;

void main() {
    vec4 world_position = model * vec4(in_position, 1.0);

    frag_position = world_position.xyz;
    frag_normal = mat3(transpose(inverse(model))) * in_normal;

    gl_Position =
        projection *
        view *
        world_position;
}
"""


FRAGMENT_SHADER = """
#version 330

in vec3 frag_position;
in vec3 frag_normal;

uniform vec3 camera_position;

out vec4 frag_color;

void main() {
    vec3 normal = normalize(frag_normal);

    // Camera-following light:
    // light position is the camera position.
    vec3 light_direction =
        normalize(camera_position - frag_position);

    float diffuse =
        max(dot(normal, light_direction), 0.0);

    // Small ambient component so faces never become completely black.
    float ambient = 0.18;

    float brightness =
        min(ambient + diffuse * 0.82, 1.0);

    vec3 base_color = vec3(0.72, 0.76, 0.82);

    frag_color = vec4(
        base_color * brightness,
        1.0
    );
}
"""


def load_obj_flat_shaded(filename):
    """
    Loads OBJ positions and creates a flat normal for each triangle.

    Output layout per vertex:
        x, y, z, nx, ny, nz
    """
    positions = []
    output = []

    with open(filename, "r", encoding="utf-8", errors="ignore") as file:
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
                # OBJ faces can have 3+ vertices.
                # Convert the polygon to triangles using a triangle fan.
                indices = []

                for token in data[1:]:
                    vertex_index = int(token.split("/")[0])

                    # OBJ allows negative indices.
                    if vertex_index < 0:
                        vertex_index = len(positions) + vertex_index
                    else:
                        vertex_index -= 1

                    indices.append(vertex_index)

                for i in range(1, len(indices) - 1):
                    p0 = positions[indices[0]]
                    p1 = positions[indices[i]]
                    p2 = positions[indices[i + 1]]

                    edge1 = p1 - p0
                    edge2 = p2 - p0

                    normal = np.cross(edge1, edge2)

                    length = np.linalg.norm(normal)

                    if length > 0.0:
                        normal = normal / length
                    else:
                        normal = np.array(
                            [0.0, 1.0, 0.0],
                            dtype=np.float32,
                        )

                    for point in (p0, p1, p2):
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

    return np.array(
        output,
        dtype=np.float32,
    )


class Camera:
    def __init__(self):
        # axis.obj is centered roughly around the origin and extends
        # about 10-12 units in each axis, so start farther back.
        self.position = glm.vec3(0.0, 2.0, 28.0)

        # Standard OpenGL-style camera:
        # yaw -90 degrees points approximately along -Z.
        self.yaw = -90.0
        self.pitch = 0.0

        self.front = glm.vec3(0.0, 0.0, -1.0)
        self.world_up = glm.vec3(0.0, 1.0, 0.0)

        self.right = glm.vec3(1.0, 0.0, 0.0)
        self.up = glm.vec3(0.0, 1.0, 0.0)

        self.update_vectors()

    def update_vectors(self):
        yaw_radians = math.radians(self.yaw)
        pitch_radians = math.radians(self.pitch)

        front = glm.vec3(
            math.cos(yaw_radians) * math.cos(pitch_radians),
            math.sin(pitch_radians),
            math.sin(yaw_radians) * math.cos(pitch_radians),
        )

        self.front = glm.normalize(front)

        self.right = glm.normalize(
            glm.cross(
                self.front,
                self.world_up,
            )
        )

        self.up = glm.normalize(
            glm.cross(
                self.right,
                self.front,
            )
        )

    def rotate(self, delta_x, delta_y):
        self.yaw += delta_x * MOUSE_SENSITIVITY
        self.pitch += delta_y * MOUSE_SENSITIVITY

        # Prevent camera inversion at the vertical poles.
        self.pitch = max(
            -89.0,
            min(89.0, self.pitch),
        )

        self.update_vectors()

    def get_view_matrix(self):
        return glm.lookAt(
            self.position,
            self.position + self.front,
            self.up,
        )


class App:
    def __init__(self):
        if not glfw.init():
            raise RuntimeError("GLFW could not be initialized.")

        glfw.window_hint(
            glfw.CONTEXT_VERSION_MAJOR,
            3,
        )
        glfw.window_hint(
            glfw.CONTEXT_VERSION_MINOR,
            3,
        )
        glfw.window_hint(
            glfw.OPENGL_PROFILE,
            glfw.OPENGL_CORE_PROFILE,
        )

        self.window = glfw.create_window(
            WINDOW_WIDTH,
            WINDOW_HEIGHT,
            "SimuO - OpenGL Test",
            None,
            None,
        )

        if not self.window:
            glfw.terminate()
            raise RuntimeError(
                "GLFW could not create an OpenGL window."
            )

        glfw.make_context_current(self.window)

        # 1 = VSync on.
        # Change to 0 later if you want uncapped benchmarking.
        glfw.swap_interval(1)

        self.ctx = moderngl.create_context()

        self.ctx.enable(
            moderngl.DEPTH_TEST
        )

        # Don't enable face culling yet.
        # It avoids winding-order surprises while validating the OBJ loader.

        self.program = self.ctx.program(
            vertex_shader=VERTEX_SHADER,
            fragment_shader=FRAGMENT_SHADER,
        )

        project_root = (
            Path(__file__).resolve().parent.parent
        )

        obj_path = (
            project_root
            / "screw.obj"
        )

        if not obj_path.exists():
            raise FileNotFoundError(
                f"Could not find screw.obj at: {obj_path}"
            )

        vertex_data = load_obj_flat_shaded(
            obj_path
        )

        print(
            f"Loaded {len(vertex_data) // 6:,} vertices "
            f"({len(vertex_data) // 18:,} triangles)"
        )

        self.vbo = self.ctx.buffer(
            vertex_data.tobytes()
        )

        self.vao = self.ctx.vertex_array(
            self.program,
            [
                (
                    self.vbo,
                    "3f 3f",
                    "in_position",
                    "in_normal",
                )
            ],
        )

        self.camera = Camera()

        self.right_mouse_down = False
        self.first_mouse_event = True
        self.last_mouse_x = 0.0
        self.last_mouse_y = 0.0

        glfw.set_cursor_pos_callback(
            self.window,
            self.on_mouse_move,
        )

        glfw.set_mouse_button_callback(
            self.window,
            self.on_mouse_button,
        )

        glfw.set_framebuffer_size_callback(
            self.window,
            self.on_resize,
        )

        self.last_time = time.perf_counter()

    def on_resize(
        self,
        window,
        width,
        height,
    ):
        if width <= 0 or height <= 0:
            return

        self.ctx.viewport = (
            0,
            0,
            width,
            height,
        )

    def on_mouse_button(
        self,
        window,
        button,
        action,
        mods,
    ):
        if button != glfw.MOUSE_BUTTON_RIGHT:
            return

        if action == glfw.PRESS:
            self.right_mouse_down = True
            self.first_mouse_event = True

            # GLFW gives us proper captured relative-style mouse movement.
            # No ctypes cursor warping is needed.
            glfw.set_input_mode(
                self.window,
                glfw.CURSOR,
                glfw.CURSOR_DISABLED,
            )

        elif action == glfw.RELEASE:
            self.right_mouse_down = False
            self.first_mouse_event = True

            glfw.set_input_mode(
                self.window,
                glfw.CURSOR,
                glfw.CURSOR_NORMAL,
            )

    def on_mouse_move(
        self,
        window,
        xpos,
        ypos,
    ):
        if not self.right_mouse_down:
            return

        if self.first_mouse_event:
            self.last_mouse_x = xpos
            self.last_mouse_y = ypos
            self.first_mouse_event = False
            return

        delta_x = xpos - self.last_mouse_x

        # Screen y increases downward, so reverse this.
        delta_y = self.last_mouse_y - ypos

        self.last_mouse_x = xpos
        self.last_mouse_y = ypos

        self.camera.rotate(
            delta_x,
            delta_y,
        )

    def update(self, delta_time):
        speed = MOVE_SPEED * delta_time

        if glfw.get_key(
            self.window,
            glfw.KEY_W,
        ) == glfw.PRESS:
            self.camera.position += (
                self.camera.front * speed
            )

        if glfw.get_key(
            self.window,
            glfw.KEY_S,
        ) == glfw.PRESS:
            self.camera.position -= (
                self.camera.front * speed
            )

        if glfw.get_key(
            self.window,
            glfw.KEY_D,
        ) == glfw.PRESS:
            self.camera.position += (
                self.camera.right * speed
            )

        if glfw.get_key(
            self.window,
            glfw.KEY_A,
        ) == glfw.PRESS:
            self.camera.position -= (
                self.camera.right * speed
            )

        if glfw.get_key(
            self.window,
            glfw.KEY_SPACE,
        ) == glfw.PRESS:
            self.camera.position += (
                self.camera.world_up * speed
            )

        if (
            glfw.get_key(
                self.window,
                glfw.KEY_LEFT_CONTROL,
            )
            == glfw.PRESS
        ):
            self.camera.position -= (
                self.camera.world_up * speed
            )

        if glfw.get_key(
            self.window,
            glfw.KEY_ESCAPE,
        ) == glfw.PRESS:
            glfw.set_window_should_close(
                self.window,
                True,
            )

    def render(self):
        startTime = time.time()
        framebuffer_width, framebuffer_height = (
            glfw.get_framebuffer_size(
                self.window
            )
        )

        if (
            framebuffer_width <= 0
            or framebuffer_height <= 0
        ):
            return

        self.ctx.viewport = (
            0,
            0,
            framebuffer_width,
            framebuffer_height,
        )

        self.ctx.clear(
            0.035,
            0.035,
            0.045,
            1.0,
            depth=1.0,
        )

        aspect = (
            framebuffer_width
            / framebuffer_height
        )

        projection = glm.perspective(
            glm.radians(60.0),
            aspect,
            0.1,
            1000.0,
        )

        view = self.camera.get_view_matrix()

        model = glm.mat4(1.0)

        self.program["model"].write(
            model.to_bytes()
        )

        self.program["view"].write(
            view.to_bytes()
        )

        self.program["projection"].write(
            projection.to_bytes()
        )

        self.program[
            "camera_position"
        ].value = (
            self.camera.position.x,
            self.camera.position.y,
            self.camera.position.z,
        )

        self.vao.render(
            mode=moderngl.TRIANGLES
        )
        renderTime = time.time()
        print(f"Render time: {(renderTime - startTime) * 1000:f} ms")

    def run(self):
        while not glfw.window_should_close(
            self.window
        ):
            current_time = time.perf_counter()

            delta_time = (
                current_time
                - self.last_time
            )

            self.last_time = current_time

            # Avoid giant jumps after debugging / dragging the window.
            delta_time = min(
                delta_time,
                0.1,
            )

            glfw.poll_events()

            self.update(
                delta_time
            )

            self.render()

            glfw.swap_buffers(
                self.window
            )

        self.close()

    def close(self):
        try:
            self.vao.release()
            self.vbo.release()
            self.program.release()
        finally:
            glfw.destroy_window(
                self.window
            )

            glfw.terminate()


if __name__ == "__main__":
    App().run()
