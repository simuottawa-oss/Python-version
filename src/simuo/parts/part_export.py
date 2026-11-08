"""Export a closed sketch's extruded geometry without changing its document."""
import numpy as np

from simuo.parts.sketch_geometry import prism_vertices
from simuo.project.temporary_parts import atomic_write


def export_sketch(path, sketch, kind):
    """Build a closed sketch's local prism mesh and atomically export it without modifying
    the document.

    Args:
        path (str or Path): Source or destination file path used by this operation.
        sketch (Sketch): Outline and thickness used by this operation, in metres.
        kind (str): Output mesh format, obj or stl.

    Returns:
        None. Writes OBJ or ASCII STL in metres; invalid geometry/format raises
        ValueError and I/O errors propagate.
    """
    if kind not in ("obj", "stl"):
        raise ValueError("Choose OBJ or STL for mesh export")
    if not sketch.closed:
        raise ValueError("Close the sketch outline before exporting a solid mesh. You can save an unfinished sketch as a SimuO Part.")
    triangles = prism_vertices(sketch).reshape(-1, 3, 6)
    export_vertices(path,triangles,kind)


def export_vertices(path,vertices,kind):
    """Atomically export local triangle geometry to OBJ or ASCII STL. Editable history,
    physics, and scene transforms are not included; STL carries no units.

    Args:
        path (str or Path): Source or destination file path used by this operation.
        vertices (array-like): Triangle XYZ/normal values reshapeable to
            (triangle_count, 3, 6), in local metres.
        kind (str): Output mesh format, obj or stl.

    Returns:
        None. Writes the destination; an empty mesh, invalid format, or degenerate STL
        triangle raises ValueError.
    """
    if kind not in ("obj","stl"):
        raise ValueError("Choose OBJ or STL for mesh export")
    triangles = np.asarray(vertices).reshape(-1,3,6)
    if not len(triangles):
        raise ValueError("Extrude a closed sketch before exporting a solid mesh")
    if kind == "obj":
        lines = ["# SimuO Part; local geometry in metres", "o SimuOPart"]
        for triangle in triangles:
            for vertex in triangle:
                lines.append("v " + " ".join(format(float(v), ".9g") for v in vertex[:3]))
        for triangle in triangles:
            lines.append("vn " + " ".join(format(float(v), ".9g") for v in triangle[0, 3:]))
        for i in range(len(triangles)):
            lines.append("f " + " ".join(f"{i*3+j+1}//{i+1}" for j in range(3)))
    else:
        # STL carries no unit metadata. Match the part's SI metre coordinates.
        lines = ["solid SimuOPart"]
        for triangle in triangles:
            a, b, c = triangle[:, :3].astype(float)
            normal = np.cross(b-a, c-a)
            length = np.linalg.norm(normal)
            if not np.isfinite(length) or length <= 0:
                raise ValueError("The sketch contains a degenerate mesh triangle")
            normal /= length
            lines.append("  facet normal " + " ".join(format(float(v), ".17g") for v in normal))
            lines.append("    outer loop")
            for point in (a, b, c):
                lines.append("      vertex " + " ".join(format(float(v), ".9g") for v in point))
            lines.extend(("    endloop", "  endfacet"))
        lines.append("endsolid SimuOPart")
    atomic_write(path, ("\n".join(lines)+"\n").encode("utf-8"))
