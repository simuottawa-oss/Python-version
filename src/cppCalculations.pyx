# cython: boundscheck=False, wraparound=False, cdivision=True, initializedcheck=False
# To build the Cython file, use the following command:
# python setup.py build_ext --inplace

from libcpp.vector cimport vector
from libc.math cimport tan, cos, sin, sqrt
import numpy as np
cimport numpy as cnp

cdef struct vec3d:
    float x, y, z, w

cdef struct triangle:
    vec3d p[3];

cdef cppclass mesh:
    vector[triangle] tris;

cdef cppclass mat4x4:
    float m[4][4];


cdef inline float edge(
    float ax, float ay,
    float bx, float by,
    float px, float py
):
    return (px - ax) * (by - ay) - (py - ay) * (bx - ax)


cdef inline float min3f(float a, float b, float c):
    cdef float m = a
    if b < m:
        m = b
    if c < m:
        m = c
    return m


cdef inline float max3f(float a, float b, float c):
    cdef float m = a
    if b > m:
        m = b
    if c > m:
        m = c
    return m


cdef class pyMesh:
    cdef float screenWidth, screenHeight, fTheta, fYaw, fPitch
    cdef mesh* m
    cdef mat4x4 matProj,matRotX, matRotZ
    cdef vec3d vCamera, vLookDir
    def __cinit__(self, screenWidth=800.0, screenHeight=600.0):
        self.m = new mesh()
        self.screenHeight = screenHeight
        self.screenWidth = screenWidth
        self.fTheta = 0.0
        self.fYaw = 0.0
        self.fPitch = 0.0
    def moveCamera(self, x, y, z):
        self.vCamera.x += x
        self.vCamera.y += y
        self.vCamera.z += z


    def moveCameraRelative(
    self,
    float forwardAmount,
    float rightAmount
):
        cdef float rightX
        cdef float rightZ

        # Right stays parallel to the XZ plane
        rightX = cos(self.fYaw)
        rightZ = sin(self.fYaw)

        # Forward follows BOTH yaw and pitch
        self.vCamera.x += (
            self.vLookDir.x * forwardAmount
            + rightX * rightAmount
        )

        self.vCamera.y += (
            self.vLookDir.y * forwardAmount
        )

        self.vCamera.z += (
            self.vLookDir.z * forwardAmount
            + rightZ * rightAmount
        )

    cpdef rotateCamera(self, float yaw, float pitch):
        self.fYaw += yaw
        self.fPitch += pitch

        cdef float maxPitch = 1.50

        if self.fPitch > maxPitch:
            self.fPitch = maxPitch
        elif self.fPitch < -maxPitch:
            self.fPitch = -maxPitch
    def __dealloc__(self):
        if self.m != NULL:
            del self.m
    cdef mat4x4 zeroMatrix(self):
        cdef mat4x4 m
        cdef int r, c
        for r in range(4):
            for c in range(4):
                m.m[r][c] = 0.0
        return m
    def getTris(self):
        return self.m.tris

    def setTris(self, list values):
        self.m.tris.clear()

        cdef triangle t
        cdef list v

        for v in values:
            t.p[0].x = v[0]
            t.p[0].y = v[1]
            t.p[0].z = v[2]
            t.p[0].w = 1.0

            t.p[1].x = v[3]
            t.p[1].y = v[4]
            t.p[1].z = v[5]
            t.p[1].w = 1.0

            t.p[2].x = v[6]
            t.p[2].y = v[7]
            t.p[2].z = v[8]
            t.p[2].w = 1.0
            self.m.tris.push_back(t)
    cdef vec3d addVector(self, vec3d &v1, vec3d &v2):
        cdef vec3d v
        v.x = v1.x + v2.x
        v.y = v1.y + v2.y
        v.z = v1.z + v2.z
        v.w = 1.0
        return v
    cdef vec3d subVector(self, vec3d &v1, vec3d &v2):
        cdef vec3d v
        v.x = v1.x - v2.x
        v.y = v1.y - v2.y
        v.z = v1.z - v2.z
        v.w = 1.0
        return v
    cdef vec3d mulVector(self, vec3d &v1, float k ):
        cdef vec3d v
        v.x = v1.x * k
        v.y = v1.y * k
        v.z = v1.z * k
        v.w = 1
        return v
    cdef vec3d divVector(self, vec3d &v1, float k ):


        cdef vec3d v
        v.x = v1.x / k
        v.y = v1.y / k
        v.z = v1.z / k
        v.w = 1
        return v
    cdef float dotProduct(self,vec3d &v1, vec3d &v2):
        return  v1.x *v2.x + v1.y * v2.y + v1.z * v2.z
    cdef vec3d crossProduct(self, vec3d &v1, vec3d &v2):
            cdef vec3d v
            v.x = v1.y * v2.z - v1.z * v2.y
            v.y = v1.z * v2.x - v1.x * v2.z
            v.z = v1.x * v2.y - v1.y * v2.x
            v.w = 1
            
            return v
    cdef mat4x4 matrixMultiplyMatrix(self, mat4x4 m1, mat4x4 m2):
        cdef mat4x4 matrix = self.zeroMatrix()
        cdef int c,r
        c = 0
        r = 0
        for c in range(4):
            for r in range(4):
                matrix.m[r][c] = m1.m[r][0] * m2.m[0][c] + m1.m[r][1] * m2.m[1][c] + m1.m[r][2] * m2.m[2][c] + m1.m[r][3] * m2.m[3][c]
        return matrix
    def loadProjectionMatrix(self):
        self.matProj = self.zeroMatrix()
        cdef float fnear = 0.1
        cdef float ffar = 1000.0
        cdef float fFov = 60.0
        cdef float aspectRatio = self.screenHeight / self.screenWidth
        cdef float fov_rad = 1.0 / tan(fFov * 0.5 / 180.0 * 3.14159)

        self.matProj.m[0][0] = aspectRatio * fov_rad
        self.matProj.m[1][1] = fov_rad
        self.matProj.m[2][2] = ffar / (ffar - fnear)
        self.matProj.m[3][2] = (-ffar * fnear) / (ffar - fnear)
        self.matProj.m[2][3] = 1.0
        self.matProj.m[3][3] = 0.0



    def updateTheta(self, float delta):
        self.fTheta += delta



    cdef vec3d multiplyMatrixVector(self, mat4x4 &m, vec3d i):
        cdef vec3d v

        v.x = i.x * m.m[0][0] + i.y * m.m[1][0] + i.z * m.m[2][0] + i.w * m.m[3][0]
        v.y = i.x * m.m[0][1] + i.y * m.m[1][1] + i.z * m.m[2][1] + i.w * m.m[3][1]
        v.z = i.x * m.m[0][2] + i.y * m.m[1][2] + i.z * m.m[2][2] + i.w * m.m[3][2]
        v.w = i.x * m.m[0][3] + i.y * m.m[1][3] + i.z * m.m[2][3] + i.w * m.m[3][3]
        
        return v
    cdef vec3d vectorNormalize(self, vec3d v):
        cdef vec3d normal
        cdef float l
        l = sqrt(v.x * v.x + v.y * v.y + v.z * v.z)
        if l == 0.0:
            normal.x = 0.0
            normal.y = 0.0
            normal.z = 0.0
            normal.w = 0.0
            return normal
        normal = self.divVector(v,l)
        return normal
    cdef mat4x4 makeMatrixIdentity(self):
        cdef mat4x4 matrix = self.zeroMatrix()
        matrix.m[0][0] = 1.0
        matrix.m[1][1] = 1.0
        matrix.m[2][2] = 1.0
        matrix.m[3][3] = 1.0
        return matrix
    cdef mat4x4 matrixMakeRotationX(self, float fAngleRad):
        cdef mat4x4 matrix = self.zeroMatrix()
        matrix.m[0][0] = 1.0
        matrix.m[1][1] = cos(fAngleRad)
        matrix.m[1][2] = sin(fAngleRad)
        matrix.m[2][1] = -sin(fAngleRad)
        matrix.m[2][2] = cos(fAngleRad)
        matrix.m[3][3] = 1.0
        return matrix
    cdef mat4x4 matrixMakeRotationY(self, float fAngleRad):
        cdef mat4x4 matrix = self.zeroMatrix()
        matrix.m[0][0] = cos(fAngleRad)
        matrix.m[0][2] = sin(fAngleRad)
        matrix.m[2][0] = -sin(fAngleRad)
        matrix.m[1][1] = 1.0
        matrix.m[2][2] = cos(fAngleRad)
        matrix.m[3][3] = 1.0
        return matrix
    cdef mat4x4 matrixMakeRotationZ(self, float fAngleRad):
        cdef mat4x4 matrix = self.zeroMatrix()
        matrix.m[0][0] = cos(fAngleRad)
        matrix.m[0][1] = sin(fAngleRad)
        matrix.m[1][0] = -sin(fAngleRad)
        matrix.m[1][1] = cos(fAngleRad)
        matrix.m[2][2] = 1.0
        matrix.m[3][3] = 1.0
        return matrix
    cdef mat4x4 matrixMakeTranslation(self, float x, float y, float z):
        cdef mat4x4 matrix = self.zeroMatrix()
        matrix.m[0][0] = 1.0
        matrix.m[1][1] = 1.0
        matrix.m[2][2] = 1.0
        matrix.m[3][3] = 1.0
        matrix.m[3][0] = x
        matrix.m[3][1] = y
        matrix.m[3][2] = z
        return matrix
    cdef mat4x4 matrixPointAt(
        self,
        vec3d &pos,
        vec3d &target,
        vec3d &up
    ):
        cdef vec3d newForward
        cdef vec3d a
        cdef vec3d newUp
        cdef vec3d newRight

        # Forward direction
        newForward = self.subVector(target, pos)
        newForward = self.vectorNormalize(newForward)

        # Corrected up direction
        a = self.mulVector(
            newForward,
            self.dotProduct(up, newForward)
        )

        newUp = self.subVector(up, a)
        newUp = self.vectorNormalize(newUp)

        # Right direction
        newRight = self.crossProduct(
            newUp,
            newForward
        )

        # IMPORTANT:
        # Initialize every matrix element to zero first.
        cdef mat4x4 matrix = self.zeroMatrix()

        matrix.m[0][0] = newRight.x
        matrix.m[0][1] = newRight.y
        matrix.m[0][2] = newRight.z

        matrix.m[1][0] = newUp.x
        matrix.m[1][1] = newUp.y
        matrix.m[1][2] = newUp.z

        matrix.m[2][0] = newForward.x
        matrix.m[2][1] = newForward.y
        matrix.m[2][2] = newForward.z

        matrix.m[3][0] = pos.x
        matrix.m[3][1] = pos.y
        matrix.m[3][2] = pos.z

        matrix.m[3][3] = 1.0

        return matrix

    cdef mat4x4 matrixQuickInverse(self, mat4x4 &m): # Only for this matrix
            cdef mat4x4 matrix

            matrix.m[0][0] = m.m[0][0]
            matrix.m[0][1] = m.m[1][0]
            matrix.m[0][2] = m.m[2][0]
            matrix.m[0][3] = 0.0

            matrix.m[1][0] = m.m[0][1]
            matrix.m[1][1] = m.m[1][1]
            matrix.m[1][2] = m.m[2][1]
            matrix.m[1][3] = 0.0

            matrix.m[2][0] = m.m[0][2]
            matrix.m[2][1] = m.m[1][2]
            matrix.m[2][2] = m.m[2][2]
            matrix.m[2][3] = 0.0

            matrix.m[3][0] = -(m.m[3][0] * matrix.m[0][0] + m.m[3][1] * matrix.m[1][0] + m.m[3][2] * matrix.m[2][0])
            matrix.m[3][1] = -(m.m[3][0] * matrix.m[0][1] + m.m[3][1] * matrix.m[1][1] + m.m[3][2] * matrix.m[2][1])
            matrix.m[3][2] = -(m.m[3][0] * matrix.m[0][2] + m.m[3][1] * matrix.m[1][2] + m.m[3][2] * matrix.m[2][2])
            matrix.m[3][3] = 1.0

            return matrix



    
    
    cdef vec3d initVec(self):
        cdef vec3d v
        v.x = 0
        v.y = 0
        v.z = 0
        v.w = 1.0
        return v

    def projectMesh(self):
        cdef triangle triProjected, triTransformed, triViewed
        cdef list trianglesToRaster = []
        cdef float halfW = self.screenWidth / 2.0
        cdef float halfH = self.screenHeight / 2.0
        cdef vec3d line1, line2, normal, vCameraRay, vUp, vTarget
        cdef vec3d lightDir = vec3d(0.0, 0.0, -1.0)
        cdef mat4x4 matCamera, matView, matCameraRot
        # Rotation Z
        matRotZ = self.matrixMakeRotationZ(self.fTheta * 0.5)
        matRotX = self.matrixMakeRotationX(self.fTheta)

        cdef mat4x4 matTrans
        matTrans = self.matrixMakeTranslation(0.0,0.0,16.0)

        cdef mat4x4 matWorld
        matWorld = self.makeMatrixIdentity()
        matWorld = self.matrixMultiplyMatrix(matRotZ,matRotX)
        matWorld = self.matrixMultiplyMatrix(matWorld,matTrans)

        

        vTarget.x = 0
        vTarget.y = 0
        vTarget.z = 1
        matCameraRot = self.matrixMakeRotationY(self.fYaw)
        self.vLookDir = self.multiplyMatrixVector(matCameraRot,vTarget)
        vTarget = self.addVector(self.vCamera,self.vLookDir)
        vUp.x = 0
        vUp.y = 1
        vUp.z = 0
        
        matCamera = self.matrixPointAt(self.vCamera,vTarget,vUp)
        
        matView = self.matrixQuickInverse(matCamera)


        

        # Project triangles
        for tri in self.m.tris:
            triTransformed.p[0] = self.multiplyMatrixVector(matWorld,tri.p[0])
            triTransformed.p[1] = self.multiplyMatrixVector(matWorld,tri.p[1])
            triTransformed.p[2] = self.multiplyMatrixVector(matWorld,tri.p[2])
            

            # Find normals
            
            line1 = self.subVector(triTransformed.p[1],triTransformed.p[0])
            line2 = self.subVector(triTransformed.p[2], triTransformed.p[0])


            normal = self.crossProduct(line1,line2)

            # Normalise normal
            normal = self.vectorNormalize(normal)

            # If normal is pointing towards camera

            vCameraRay = self.subVector(triTransformed.p[0],self.vCamera)
            if (self.dotProduct(normal, vCameraRay) < 0.0):
                
                # Illuminate cube
                lightDir = self.vectorNormalize(lightDir)
                dp = self.dotProduct(normal, lightDir)


                # Greyscale triangle
                color = dp * 255

                # Convert world space -> viewSpace
                triViewed.p[0] = self.multiplyMatrixVector(matView,triTransformed.p[0])
                triViewed.p[1] = self.multiplyMatrixVector(matView,triTransformed.p[1])
                triViewed.p[2] = self.multiplyMatrixVector(matView,triTransformed.p[2])
                

                # Project triangle from 3D-->2D

                triProjected.p[0] = self.multiplyMatrixVector(self.matProj,triViewed.p[0])
                triProjected.p[1] = self.multiplyMatrixVector(self.matProj,triViewed.p[1])
                triProjected.p[2] = self.multiplyMatrixVector(self.matProj,triViewed.p[2])

                triProjected.p[0] = self.divVector(triProjected.p[0],triProjected.p[0].w)
                triProjected.p[1] = self.divVector(triProjected.p[1],triProjected.p[1].w)
                triProjected.p[2] = self.divVector(triProjected.p[2],triProjected.p[2].w)

                
                trianglesToRaster.append([
                    (triProjected.p[0].x + 1.0) * 0.5 * self.screenWidth,
                    (triProjected.p[0].y + 1.0) * 0.5 * self.screenHeight,

                    (triProjected.p[1].x + 1.0) * 0.5 * self.screenWidth,
                    (triProjected.p[1].y + 1.0) * 0.5 * self.screenHeight,

                    (triProjected.p[2].x + 1.0) * 0.5 * self.screenWidth,
                    (triProjected.p[2].y + 1.0) * 0.5 * self.screenHeight,

                    color,
                    triProjected.p[0].z,
                    triProjected.p[1].z,
                    triProjected.p[2].z
                ])
        trianglesToRaster.sort(key=lambda t: (t[7] + t[8] + t[9])/3, reverse=True)
        return trianglesToRaster
    def getScreenWidth(self):
        return self.screenWidth
    def getScreenHeight(self):
        return self.screenHeight
    def loadMesh(self, data):
        self.setTris(data)
        return True
#####TEST##########
    cdef void drawTriangle(
        self,
        cnp.ndarray[cnp.uint8_t, ndim=3] framebuffer,
        cnp.ndarray[cnp.float32_t, ndim=2] depthbuffer,
        float x1, float y1, float z1,
        float x2, float y2, float z2,
        float x3, float y3, float z3,
        unsigned char shade
    ):
        cdef int width = framebuffer.shape[1]
        cdef int height = framebuffer.shape[0]

        cdef int minX = <int>min3f(x1, x2, x3)
        cdef int maxX = <int>max3f(x1, x2, x3)
        cdef int minY = <int>min3f(y1, y2, y3)
        cdef int maxY = <int>max3f(y1, y2, y3)

        cdef int x, y
        cdef float px, py

        # Edge-function values. These also become barycentric numerators.
        cdef float w0, w1, w2
        cdef float area
        cdef float invArea

        cdef float lambda0, lambda1, lambda2
        cdef float z

        # Clip the triangle bounding box to the framebuffer.
        if minX < 0:
            minX = 0
        if minY < 0:
            minY = 0
        if maxX >= width:
            maxX = width - 1
        if maxY >= height:
            maxY = height - 1

        # Triangle is completely outside the framebuffer.
        if minX > maxX or minY > maxY:
            return

        # Signed triangle area.
        area = edge(x2, y2, x3, y3, x1, y1)

        # Degenerate triangle.
        if area == 0.0:
            return

        invArea = 1.0 / area

        for y in range(minY, maxY + 1):
            py = y + 0.5

            for x in range(minX, maxX + 1):
                px = x + 0.5

                # Each edge is opposite the corresponding vertex.
                w0 = edge(x2, y2, x3, y3, px, py)
                w1 = edge(x3, y3, x1, y1, px, py)
                w2 = edge(x1, y1, x2, y2, px, py)

                # Inside-triangle test that works for both winding orders.
                if area > 0.0:
                    if w0 < 0.0 or w1 < 0.0 or w2 < 0.0:
                        continue
                else:
                    if w0 > 0.0 or w1 > 0.0 or w2 > 0.0:
                        continue

                # Barycentric coordinates.
                lambda0 = w0 * invArea
                lambda1 = w1 * invArea
                lambda2 = w2 * invArea

                # Interpolate NDC depth across the triangle.
                z = (
                    lambda0 * z1 +
                    lambda1 * z2 +
                    lambda2 * z3
                )

                # Z-buffer test: smaller depth is closer.
                if z < depthbuffer[y, x]:
                    depthbuffer[y, x] = z

                    framebuffer[y, x, 0] = shade
                    framebuffer[y, x, 1] = shade
                    framebuffer[y, x, 2] = shade

###############

    def renderToFramebuffer(
        self,
        cnp.ndarray[cnp.uint8_t, ndim=3] framebuffer,
        cnp.ndarray[cnp.float32_t, ndim=2] depthbuffer
    ):
        """
        Optimized render path.

        Projection and rasterization stay inside Cython, so Python no longer
        receives a list of projected triangles and no longer calls
        drawTriangle() once per triangle.
        """
        cdef triangle tri
        cdef triangle triProjected
        cdef triangle triTransformed
        cdef triangle triViewed

        cdef vec3d line1, line2, normal
        cdef vec3d vCameraRay, vUp, vTarget
        cdef vec3d lightDir

        cdef mat4x4 matCamera
        cdef mat4x4 matView
        cdef mat4x4 matCameraRot
        cdef mat4x4 matRotZLocal
        cdef mat4x4 matRotXLocal
        cdef mat4x4 matTrans
        cdef mat4x4 matWorld

        cdef float dp
        cdef float color

        cdef float x1, y1
        cdef float x2, y2
        cdef float x3, y3

        cdef unsigned char shade
        cdef Py_ssize_t i
        cdef Py_ssize_t triCount = self.m.tris.size()

        # The color and depth buffers must describe the same screen.
        if (
            framebuffer.shape[0] != depthbuffer.shape[0] or
            framebuffer.shape[1] != depthbuffer.shape[1]
        ):
            raise ValueError("framebuffer and depthbuffer dimensions must match")

        # Build the world matrix once per frame.
        matRotZLocal = self.matrixMakeRotationZ(self.fTheta * 0.5)
        matRotXLocal = self.matrixMakeRotationX(self.fTheta)

        matTrans = self.matrixMakeTranslation(0.0, 0.0, 16.0)

        matWorld = self.matrixMultiplyMatrix(matRotZLocal, matRotXLocal)
        matWorld = self.matrixMultiplyMatrix(matWorld, matTrans)

        # Build full 3D camera direction from yaw + pitch
        self.vLookDir.x = -sin(self.fYaw) * cos(self.fPitch)
        self.vLookDir.y =  sin(self.fPitch)
        self.vLookDir.z =  cos(self.fYaw) * cos(self.fPitch)
        self.vLookDir.w = 1.0

        # Point the camera toward:
        # camera position + look direction
        vTarget = self.addVector(
            self.vCamera,
            self.vLookDir
        )

        # World up direction
        vUp.x = 0.0
        vUp.y = 1.0
        vUp.z = 0.0
        vUp.w = 1.0

        # Build camera/view matrices
        matCamera = self.matrixPointAt(
            self.vCamera,
            vTarget,
            vUp
        )

        matView = self.matrixQuickInverse(matCamera)

        # The light is attached to the camera position.
        # A direction toward the camera is calculated per visible triangle.
        for i in range(triCount):
            tri = self.m.tris[i]

            # World transform.
            triTransformed.p[0] = self.multiplyMatrixVector(matWorld, tri.p[0])
            triTransformed.p[1] = self.multiplyMatrixVector(matWorld, tri.p[1])
            triTransformed.p[2] = self.multiplyMatrixVector(matWorld, tri.p[2])

            # Surface normal.
            line1 = self.subVector(triTransformed.p[1], triTransformed.p[0])
            line2 = self.subVector(triTransformed.p[2], triTransformed.p[0])

            normal = self.crossProduct(line1, line2)
            normal = self.vectorNormalize(normal)

            # Back-face culling.
            vCameraRay = self.subVector(triTransformed.p[0], self.vCamera)
            if self.dotProduct(normal, vCameraRay) >= 0.0:
                continue

            # Camera-following point light.
            # Direction from this triangle toward the camera/light position.
            lightDir = self.subVector(
                self.vCamera,
                triTransformed.p[0]
            )
            lightDir = self.vectorNormalize(lightDir)

            dp = self.dotProduct(normal, lightDir)

            # Surfaces facing away from the light receive no diffuse light.
            if dp < 0.0:
                dp = 0.0
            elif dp > 1.0:
                dp = 1.0

            color = dp * 255.0
            shade = <unsigned char>color

            # World -> view.
            triViewed.p[0] = self.multiplyMatrixVector(matView, triTransformed.p[0])
            triViewed.p[1] = self.multiplyMatrixVector(matView, triTransformed.p[1])
            triViewed.p[2] = self.multiplyMatrixVector(matView, triTransformed.p[2])

            # Reject triangles that are behind the camera or cross the near plane.
            # This prevents negative-W / behind-camera projection from appearing
            # mirrored or inverted when the camera turns away from the model.
            if (
                triViewed.p[0].z <= 0.1 or
                triViewed.p[1].z <= 0.1 or
                triViewed.p[2].z <= 0.1
            ):
                continue

            # View -> projected clip space.
            triProjected.p[0] = self.multiplyMatrixVector(self.matProj, triViewed.p[0])
            triProjected.p[1] = self.multiplyMatrixVector(self.matProj, triViewed.p[1])
            triProjected.p[2] = self.multiplyMatrixVector(self.matProj, triViewed.p[2])

            # Avoid division by zero for geometry on the camera plane.
            if (
                triProjected.p[0].w == 0.0 or
                triProjected.p[1].w == 0.0 or
                triProjected.p[2].w == 0.0
            ):
                continue

            # Perspective divide.
            triProjected.p[0] = self.divVector(triProjected.p[0], triProjected.p[0].w)
            triProjected.p[1] = self.divVector(triProjected.p[1], triProjected.p[1].w)
            triProjected.p[2] = self.divVector(triProjected.p[2], triProjected.p[2].w)

            # Normalized device coordinates [-1,+1] -> framebuffer pixels.
            x1 = (triProjected.p[0].x + 1.0) * 0.5 * self.screenWidth
            y1 = (1.0 - triProjected.p[0].y) * 0.5 * self.screenHeight

            x2 = (triProjected.p[1].x + 1.0) * 0.5 * self.screenWidth
            y2 = (1.0 - triProjected.p[1].y) * 0.5 * self.screenHeight

            x3 = (triProjected.p[2].x + 1.0) * 0.5 * self.screenWidth
            y3 = (1.0 - triProjected.p[2].y) * 0.5 * self.screenHeight

            # Rasterize immediately. No Python list, Python sort, or
            # Python -> Cython call per triangle.
            self.drawTriangle(
                framebuffer,
                depthbuffer,
                x1, y1, triProjected.p[0].z,
                x2, y2, triProjected.p[1].z,
                x3, y3, triProjected.p[2].z,
                shade
            )

        return triCount





    def loadCubeMesh(self):
        self.setTris([
            # South
            [0.0,0.0,0.0,0.0,1.0,0.0,1.0,1.0,0.0],
            [0.0,0.0,0.0,1.0,1.0,0.0,1.0,0.0,0.0],

            # East
            [1.0,0.0,0.0,1.0,1.0,0.0,1.0,1.0,1.0],
            [1.0,0.0,0.0,1.0,1.0,1.0,1.0,0.0,1.0],

            # North
            [1.0,0.0,1.0,1.0,1.0,1.0,0.0,1.0,1.0],
            [1.0,0.0,1.0,0.0,1.0,1.0,0.0,0.0,1.0],

            # West
            [0.0,0.0,1.0,0.0,1.0,1.0,0.0,1.0,0.0],
            [0.0,0.0,1.0,0.0,1.0,0.0,0.0,0.0,0.0],

            # Top
            [0.0,1.0,0.0,0.0,1.0,1.0,1.0,1.0,1.0],
            [0.0,1.0,0.0,1.0,1.0,1.0,1.0,1.0,0.0],

            # Bottom
            [1.0,0.0,1.0,0.0,0.0,1.0,0.0,0.0,0.0],
            [1.0,0.0,1.0,0.0,0.0,0.0,1.0,0.0,0.0],
        ])
def createMesh(screenWidth,screenHeight):
    return pyMesh(screenWidth, screenHeight)

def createTriangle():
    return triangle()

