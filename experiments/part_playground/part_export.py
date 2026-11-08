"""Part-file saves and local, metre-based box geometry exports."""
import os
from pathlib import Path
import tempfile


FACES = (
    ((0, 3, 2, 1), (0, 0, -1)),
    ((4, 5, 6, 7), (0, 0, 1)),
    ((0, 4, 7, 3), (-1, 0, 0)),
    ((1, 2, 6, 5), (1, 0, 0)),
    ((0, 1, 5, 4), (0, -1, 0)),
    ((3, 7, 6, 2), (0, 1, 0)),
)


def write_text(path, text):
    """Keep an existing destination intact if writing the new file fails."""
    path = Path(path)
    staging = None
    try:
        with tempfile.NamedTemporaryFile(dir=path.parent, prefix=f".{path.name}.", delete=False) as stream:
            staging = Path(stream.name)
            stream.write(text.encode("utf-8"))
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(staging, path)
    finally:
        if staging is not None:
            staging.unlink(missing_ok=True)


def save_part(path, document):
    # Retain the validated source document, including explicit/density mass
    # selection, description and custom properties. Playback is not an edit.
    write_text(path, document)


def export_obj(path, part):
    vertices = part.vertices((0, 0, 0))
    lines = ["# SimuO Part geometry; coordinates in metres; local origin", "o SimuOPart"]
    lines.extend("v " + " ".join(format(v, ".17g") for v in point) for point in vertices)
    lines.extend("vn " + " ".join(str(v) for v in normal) for _, normal in FACES)
    for normal_index, (face, _) in enumerate(FACES, 1):
        for a, b, c in ((face[0], face[1], face[2]), (face[0], face[2], face[3])):
            lines.append("f " + " ".join(f"{i + 1}//{normal_index}" for i in (a, b, c)))
    write_text(path, "\n".join(lines) + "\n")


def export_stl(path, part):
    # STL has no unit field; use the same metre coordinates as the part/OBJ.
    vertices = part.vertices((0, 0, 0))
    lines = ["solid SimuOPart"]
    for face, normal in FACES:
        for triangle in ((face[0], face[1], face[2]), (face[0], face[2], face[3])):
            lines.append("  facet normal " + " ".join(str(v) for v in normal))
            lines.append("    outer loop")
            for index in triangle:
                lines.append("      vertex " + " ".join(format(v, ".17g") for v in vertices[index]))
            lines.extend(("    endloop", "  endfacet"))
    lines.append("endsolid SimuOPart")
    write_text(path, "\n".join(lines) + "\n")
