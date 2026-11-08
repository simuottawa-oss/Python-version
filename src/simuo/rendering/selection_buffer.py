"""Depth-tested object IDs for box selection, read only when a drag completes."""

import math

import glm
import numpy as np
from OpenGL.GL import *
from OpenGL.GL.shaders import compileProgram, compileShader

from simuo.rendering.picking import object_matrix

VERTEX = '''#version 330 core
layout(location=0) in vec3 position;
uniform mat4 model;
uniform mat4 view;
uniform mat4 projection;
void main() { gl_Position = projection * view * model * vec4(position, 1.0); }
'''
FRAGMENT = '''#version 330 core
uniform uint object_id;
layout(location=0) out uint result;
void main() { result = object_id; }
'''


class SelectionBuffer:
    def __init__(self):
        self.program = compileProgram(compileShader(VERTEX, GL_VERTEX_SHADER),
                                      compileShader(FRAGMENT, GL_FRAGMENT_SHADER), validate=False)
        self.uniforms = {name: glGetUniformLocation(self.program, name) for name in ('model', 'view', 'projection', 'object_id')}
        self.framebuffer = self.texture = self.depth = 0
        self.size = (0, 0)

    def _resize(self, width, height):
        if self.size == (width, height):
            return
        self._delete_buffers()
        self.framebuffer = glGenFramebuffers(1)
        self.texture = glGenTextures(1)
        self.depth = glGenRenderbuffers(1)
        glBindFramebuffer(GL_FRAMEBUFFER, self.framebuffer)
        glBindTexture(GL_TEXTURE_2D, self.texture)
        glTexImage2D(GL_TEXTURE_2D, 0, GL_R32UI, width, height, 0, GL_RED_INTEGER, GL_UNSIGNED_INT, None)
        glTexParameteri(GL_TEXTURE_2D, GL_TEXTURE_MIN_FILTER, GL_NEAREST)
        glTexParameteri(GL_TEXTURE_2D, GL_TEXTURE_MAG_FILTER, GL_NEAREST)
        glFramebufferTexture2D(GL_FRAMEBUFFER, GL_COLOR_ATTACHMENT0, GL_TEXTURE_2D, self.texture, 0)
        glBindRenderbuffer(GL_RENDERBUFFER, self.depth)
        glRenderbufferStorage(GL_RENDERBUFFER, GL_DEPTH_COMPONENT24, width, height)
        glFramebufferRenderbuffer(GL_FRAMEBUFFER, GL_DEPTH_ATTACHMENT, GL_RENDERBUFFER, self.depth)
        if glCheckFramebufferStatus(GL_FRAMEBUFFER) != GL_FRAMEBUFFER_COMPLETE:
            raise RuntimeError('Could not create box-selection buffer')
        self.size = width, height

    def select(self, rendered, projection, rect, width, height, ratio, target):
        left = max(0, min(width, math.floor(rect[0]*ratio)))
        right = max(0, min(width, math.ceil(rect[2]*ratio)))
        bottom = max(0, min(height, height-math.ceil(rect[3]*ratio)))
        top = max(0, min(height, height-math.floor(rect[1]*ratio)))
        if right <= left or top <= bottom:
            return []
        try:
            self._resize(width, height)
            glBindFramebuffer(GL_FRAMEBUFFER, self.framebuffer)
            glViewport(0, 0, width, height)
            glEnable(GL_DEPTH_TEST)
            glDepthMask(GL_TRUE)
            glDepthFunc(GL_LESS)
            glColorMask(GL_TRUE, GL_TRUE, GL_TRUE, GL_TRUE)
            glDisable(GL_CULL_FACE)
            glDisable(GL_BLEND)
            glDisable(GL_SCISSOR_TEST)
            glClearBufferuiv(GL_COLOR, 0, np.zeros(4, dtype=np.uint32))
            glClear(GL_DEPTH_BUFFER_BIT)
            glUseProgram(self.program)
            glUniformMatrix4fv(self.uniforms['view'], 1, GL_FALSE, glm.value_ptr(projection.view))
            glUniformMatrix4fv(self.uniforms['projection'], 1, GL_FALSE, glm.value_ptr(projection.projection))
            identifiers = {}
            for number, item in enumerate(rendered, 1):
                obj = item['SceneObject']
                if not obj.viewport_visible:
                    continue
                identifiers[number] = obj.identifier
                glUniform1ui(self.uniforms['object_id'], 0 if obj.viewport_locked else number)
                matrix = object_matrix(obj)
                glUniformMatrix4fv(self.uniforms['model'], 1, GL_FALSE, glm.value_ptr(matrix))
                glBindVertexArray(item['vao'])
                glDrawArrays(GL_TRIANGLES, 0, item['vertexCount'])
            pixels = np.empty((top-bottom, right-left), dtype=np.uint32)
            glReadPixels(left, bottom, right-left, top-bottom, GL_RED_INTEGER, GL_UNSIGNED_INT, pixels)
            visible = set(np.unique(pixels))
            return [key for number, key in identifiers.items() if number in visible and number != 0]
        finally:
            glBindFramebuffer(GL_FRAMEBUFFER, target)
            glViewport(0, 0, width, height)
            glBindTexture(GL_TEXTURE_2D, 0)
            glBindRenderbuffer(GL_RENDERBUFFER, 0)
            glBindVertexArray(0)
            glUseProgram(0)

    def _delete_buffers(self):
        if self.framebuffer:
            glDeleteFramebuffers(1, [self.framebuffer])
            glDeleteTextures(1, [self.texture])
            glDeleteRenderbuffers(1, [self.depth])
        self.framebuffer = self.texture = self.depth = 0
        self.size = (0, 0)

    def cleanup(self):
        self._delete_buffers()
        if self.program:
            glDeleteProgram(self.program)
            self.program = 0
