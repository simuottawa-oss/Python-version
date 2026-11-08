"""Depth-tested, screen-space blue selection silhouettes."""

from itertools import product
import math

import glm
from OpenGL.GL import *
from OpenGL.GL.shaders import compileProgram, compileShader

from simuo.rendering.picking import object_matrix
from simuo.rendering.shaders import MASK_VERTEX, MASK_FRAGMENT, OUTLINE_VERTEX, OUTLINE_FRAGMENT


def outline_bounds(rendered, view, projection, width, height, padding):
    """Limit outline work to the projected mesh bounds, in framebuffer pixels."""
    mesh = rendered["pick_mesh"]
    matrix = projection * view * object_matrix(rendered["SceneObject"])
    corners = [matrix * glm.vec4(x, y, z, 1.0) for x, y, z in product(
        (float(mesh.minimum[0]), float(mesh.maximum[0])),
        (float(mesh.minimum[1]), float(mesh.maximum[1])),
        (float(mesh.minimum[2]), float(mesh.maximum[2])),
    )]
    if any(point.w <= 0 for point in corners):
        return 0, 0, width, height
    xs = [(point.x / point.w + 1) * width / 2 for point in corners]
    ys = [(point.y / point.w + 1) * height / 2 for point in corners]
    left = max(0, min(width, math.floor(min(xs)) - padding))
    bottom = max(0, min(height, math.floor(min(ys)) - padding))
    right = max(0, min(width, math.ceil(max(xs)) + padding))
    top = max(0, min(height, math.ceil(max(ys)) + padding))
    return left, bottom, right - left, top - bottom


class SelectionOutline:
    """Own a visibility mask and a silhouette pass in the viewport's GL context."""

    def __init__(self):
        self.mask_shader = compileProgram(
            compileShader(MASK_VERTEX, GL_VERTEX_SHADER),
            compileShader(MASK_FRAGMENT, GL_FRAGMENT_SHADER), validate=False,
        )
        self.outline_shader = compileProgram(
            compileShader(OUTLINE_VERTEX, GL_VERTEX_SHADER),
            compileShader(OUTLINE_FRAGMENT, GL_FRAGMENT_SHADER), validate=False,
        )
        self.mask_uniforms = {name: glGetUniformLocation(self.mask_shader, name)
                              for name in ("model", "view", "projection", "selected")}
        self.radius_uniform = glGetUniformLocation(self.outline_shader, "radius")
        self.texture_uniform = glGetUniformLocation(self.outline_shader, "selection_mask")
        self.screen_vao = glGenVertexArrays(1)
        self.framebuffer = self.texture = self.depth_buffer = 0
        self.size = (0, 0)

    def _resize(self, width, height):
        if self.size == (width, height):
            return
        self._delete_buffers()
        self.framebuffer = glGenFramebuffers(1)
        self.texture = glGenTextures(1)
        self.depth_buffer = glGenRenderbuffers(1)
        glBindFramebuffer(GL_FRAMEBUFFER, self.framebuffer)
        glBindTexture(GL_TEXTURE_2D, self.texture)
        glTexImage2D(GL_TEXTURE_2D, 0, GL_R8, width, height, 0, GL_RED, GL_UNSIGNED_BYTE, None)
        glTexParameteri(GL_TEXTURE_2D, GL_TEXTURE_MIN_FILTER, GL_NEAREST)
        glTexParameteri(GL_TEXTURE_2D, GL_TEXTURE_MAG_FILTER, GL_NEAREST)
        glTexParameteri(GL_TEXTURE_2D, GL_TEXTURE_WRAP_S, GL_CLAMP_TO_EDGE)
        glTexParameteri(GL_TEXTURE_2D, GL_TEXTURE_WRAP_T, GL_CLAMP_TO_EDGE)
        glFramebufferTexture2D(GL_FRAMEBUFFER, GL_COLOR_ATTACHMENT0, GL_TEXTURE_2D, self.texture, 0)
        glBindRenderbuffer(GL_RENDERBUFFER, self.depth_buffer)
        glRenderbufferStorage(GL_RENDERBUFFER, GL_DEPTH_COMPONENT24, width, height)
        glFramebufferRenderbuffer(GL_FRAMEBUFFER, GL_DEPTH_ATTACHMENT, GL_RENDERBUFFER, self.depth_buffer)
        if glCheckFramebufferStatus(GL_FRAMEBUFFER) != GL_FRAMEBUFFER_COMPLETE:
            raise RuntimeError("Could not create the selection outline framebuffer")
        glBindRenderbuffer(GL_RENDERBUFFER, 0)
        glBindTexture(GL_TEXTURE_2D, 0)
        self.size = width, height

    def draw(self, rendered_objects, selected_ids, view, projection, target, width, height, pixel_ratio):
        rendered_objects = [item for item in rendered_objects if item["SceneObject"].viewport_visible]
        selected = [item for item in rendered_objects if item["SceneObject"].identifier in selected_ids]
        if not selected:
            return
        radius = max(1, min(6, round(1.5 * pixel_ratio)))
        rectangles = [outline_bounds(item, view, projection, width, height, radius + 1) for item in selected]
        rectangles = [rect for rect in rectangles if rect[2] and rect[3]]
        if not rectangles:
            return
        x, y = min(rect[0] for rect in rectangles), min(rect[1] for rect in rectangles)
        bounds = (x, y, max(rect[0] + rect[2] for rect in rectangles) - x,
                  max(rect[1] + rect[3] for rect in rectangles) - y)
        try:
            self._resize(width, height)
            glBindFramebuffer(GL_FRAMEBUFFER, self.framebuffer)
            glViewport(0, 0, width, height)
            glClearColor(0, 0, 0, 0)
            glClear(GL_COLOR_BUFFER_BIT | GL_DEPTH_BUFFER_BIT)
            glUseProgram(self.mask_shader)
            glUniformMatrix4fv(self.mask_uniforms["view"], 1, GL_FALSE, glm.value_ptr(view))
            glUniformMatrix4fv(self.mask_uniforms["projection"], 1, GL_FALSE, glm.value_ptr(projection))
            # The depth-tested mask excludes selected surfaces hidden by other meshes.
            for item in rendered_objects:
                obj = item["SceneObject"]
                model = object_matrix(obj)
                glUniformMatrix4fv(self.mask_uniforms["model"], 1, GL_FALSE, glm.value_ptr(model))
                glUniform1f(self.mask_uniforms["selected"], float(obj.identifier in selected_ids))
                glBindVertexArray(item["vao"])
                glDrawArrays(GL_TRIANGLES, 0, item["vertexCount"])

            glBindFramebuffer(GL_FRAMEBUFFER, target)
            glDisable(GL_DEPTH_TEST)
            glEnable(GL_SCISSOR_TEST)
            glScissor(*bounds)
            glUseProgram(self.outline_shader)
            glActiveTexture(GL_TEXTURE0)
            glBindTexture(GL_TEXTURE_2D, self.texture)
            glUniform1i(self.texture_uniform, 0)
            glUniform1i(self.radius_uniform, radius)
            glBindVertexArray(self.screen_vao)
            glDrawArrays(GL_TRIANGLES, 0, 3)
        finally:
            glBindFramebuffer(GL_FRAMEBUFFER, target)
            glViewport(0, 0, width, height)
            glDisable(GL_SCISSOR_TEST)
            glEnable(GL_DEPTH_TEST)
            glBindTexture(GL_TEXTURE_2D, 0)
            glBindVertexArray(0)
            glUseProgram(0)

    def _delete_buffers(self):
        if self.framebuffer:
            glDeleteFramebuffers(1, [self.framebuffer])
            glDeleteTextures(1, [self.texture])
            glDeleteRenderbuffers(1, [self.depth_buffer])
        self.framebuffer = self.texture = self.depth_buffer = 0
        self.size = (0, 0)

    def cleanup(self):
        self._delete_buffers()
        glDeleteVertexArrays(1, [self.screen_vao])
        glDeleteProgram(self.mask_shader)
        glDeleteProgram(self.outline_shader)
