"""GLSL programs used by the scene, helpers, and selection outline."""

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

MASK_VERTEX = """
#version 330 core
layout(location = 0) in vec3 position;
uniform mat4 model;
uniform mat4 view;
uniform mat4 projection;
void main() { gl_Position = projection * view * model * vec4(position, 1.0); }
"""

MASK_FRAGMENT = """
#version 330 core
uniform float selected;
out float mask;
void main() { mask = selected; }
"""

OUTLINE_VERTEX = """
#version 330 core
void main() {
    vec2 position = vec2((gl_VertexID << 1) & 2, gl_VertexID & 2);
    gl_Position = vec4(position * 2.0 - 1.0, 0.0, 1.0);
}
"""

OUTLINE_FRAGMENT = """
#version 330 core
uniform sampler2D selection_mask;
uniform int radius;
out vec4 color;
void main() {
    ivec2 pixel = ivec2(gl_FragCoord.xy);
    ivec2 maximum = textureSize(selection_mask, 0) - 1;
    // Keep every pixel inside the selected mesh exactly as it was shaded.
    if (texelFetch(selection_mask, pixel, 0).r > 0.5) discard;
    for (int y = -6; y <= 6; ++y) {
        for (int x = -6; x <= 6; ++x) {
            if (x*x + y*y > radius*radius) continue;
            ivec2 neighbor = clamp(pixel + ivec2(x, y), ivec2(0), maximum);
            if (texelFetch(selection_mask, neighbor, 0).r > 0.5) {
                color = vec4(0.25, 0.58, 1.0, 1.0);
                return;
            }
        }
    }
    discard;
}
"""
