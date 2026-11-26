"""Open a project in its declared workspace without entering another event loop."""
from simuo.project.project_format import read_project


def open_project_window(path, owner=None):
    document = read_project(path)
    if document.project_type == "structural":
        from simuo.structural.persistence import load_analysis
        from simuo.ui.structural_window import StructuralWindow
        load_analysis(path)  # Validate inputs/reference before opening a new window.
        window = StructuralWindow(path)
    else:
        from simuo.ui.scene_window import SimuOMainWindow
        window = SimuOMainWindow()
        try:
            window.loadFile(path, uploadToGPU=False)
        except BaseException:
            window.close()
            raise
    if owner is not None:
        if not hasattr(owner, "_opened_projects"):
            owner._opened_projects = []
        owner._opened_projects.append(window)
    window.show()
    return window
