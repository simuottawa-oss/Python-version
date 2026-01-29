from libcpp.vector cimport vector

cdef struct vec3d:
    float x, y, z

cdef struct triangle:
    vec3d p[3];

cdef cppclass mesh:
    vector[triangle] tris;


cdef class pyMesh:

    cdef mesh* m

    def __cinit__(self):
        self.m = new mesh()

    def __dealloc__(self):
        if self.m != NULL:
            del self.m
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

            t.p[1].x = v[3]
            t.p[1].y = v[4]
            t.p[1].z = v[5]

            t.p[2].x = v[6]
            t.p[2].y = v[7]
            t.p[2].z = v[8]

            self.m.tris.push_back(t)
def createMesh():
    return pyMesh()
