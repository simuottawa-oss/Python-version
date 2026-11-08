"""Portable mesh references for SimuO project files."""

import os
from pathlib import Path, PureWindowsPath

from simuo.resources.paths import resource_path


def resolve_mesh_path(value, project_path):
    # Old Windows scenes contain backslashes and sometimes absolute drive paths.
    """Resolve a saved mesh reference, recovering legacy Windows paths beside the project
    or in project/bundled Assets folders.

    Args:
        value (str): Saved model reference, including relative paths or legacy Windows
            paths.
        project_path (str or Path): Scene file whose parent anchors portable asset
            references.

    Returns:
        pathlib.Path: Resolved existing model; raises FileNotFoundError if no candidate
        exists.
    """
    normalized = value.replace("\\", "/")
    mesh = Path(normalized).expanduser()
    project_dir = Path(project_path).resolve().parent
    windows_absolute = PureWindowsPath(value).is_absolute()
    candidates = []
    # On Windows, an existing drive/UNC path is a native absolute path and
    # must be tried before falling back to a different file with the same name.
    if mesh.is_absolute():
        candidates.append(mesh)
    elif not windows_absolute:
        candidates.append(project_dir / mesh)

    # Recover legacy absolute references when the mesh travelled with the scene
    # or is one of the assets shipped with this application.
    candidates.extend((project_dir / mesh.name, project_dir / "Assets" / mesh.name,
                       resource_path("Assets", mesh.name)))
    for candidate in candidates:
        if candidate.is_file():
            return candidate.resolve()
    raise FileNotFoundError(f"Could not find model '{value}' for project '{project_path}'. "
                            "Place the model beside the project or in its Assets folder.")


def stored_mesh_path(mesh_path, project_path):
    """Express a model path relative to its scene for portable persistence.

    Args:
        mesh_path (str or Path): Model file to reference from the scene.
        project_path (str or Path): Scene file whose parent anchors portable asset
            references.

    Returns:
        str: POSIX-style relative path, or an absolute path when Windows drives differ.
    """
    mesh = Path(mesh_path).resolve()
    try:
        return Path(os.path.relpath(mesh, Path(project_path).resolve().parent)).as_posix()
    except ValueError:
        # Windows cannot express a relative path between separate drives.
        return str(mesh)
