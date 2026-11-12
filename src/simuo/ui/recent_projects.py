from pathlib import Path
from datetime import datetime
import hashlib
import json
import os

from PySide6.QtCore import QSettings, QStandardPaths, Qt
from PySide6.QtOpenGLWidgets import QOpenGLWidget

MAX_RECENT_PROJECTS = 10


def recent_projects():
    settings = QSettings("SimuOttawa", "SimuO")
    paths = settings.value("recent/projects", [], type=list)

    # Hide files that no longer exist.
    return [path for path in paths if isinstance(path, str) and Path(path).is_file()]


def remember_project(filepath):
    path = str(Path(filepath).resolve())
    paths = recent_projects()

    # Move this file to the front without creating duplicates.
    paths = [item for item in paths if os.path.normcase(item) != os.path.normcase(path)]
    paths.insert(0, path)

    settings = QSettings("SimuOttawa", "SimuO")
    settings.setValue("recent/projects", paths[:MAX_RECENT_PROJECTS])


def forget_project(filepath):
    """Remove a recent-file entry without deleting any files."""
    path = os.path.normcase(str(Path(filepath).resolve()))
    paths = [item for item in recent_projects() if os.path.normcase(item) != path]
    QSettings("SimuOttawa", "SimuO").setValue("recent/projects", paths)


def thumbnail_path(filepath):
    """Locate an optional preview independently of the project's file format."""
    key = os.path.normcase(str(Path(filepath).resolve()))
    digest = hashlib.sha256(key.encode("utf-8")).hexdigest()
    return Path(QStandardPaths.writableLocation(
        QStandardPaths.StandardLocation.CacheLocation
    )) / "SimuO" / "thumbnails" / f"{digest}.png"


def record_saved_project(filepath, viewport):
    """Remember a successful save; preview failures must never fail the save itself."""
    remember_project(filepath)
    try:
        if not viewport.isVisible():
            return
        if isinstance(viewport, QOpenGLWidget):
            if not viewport.isValid():
                return
            image = viewport.grabFramebuffer()
        else:
            viewport.repaint()
            image = viewport.grab().toImage()
        if image.isNull():
            return
        image = image.scaled(640, 400, Qt.AspectRatioMode.KeepAspectRatio,
                             Qt.TransformationMode.SmoothTransformation)
        target = thumbnail_path(filepath)
        target.parent.mkdir(parents=True, exist_ok=True)
        temporary = target.with_suffix(".tmp.png")
        try:
            if image.save(str(temporary), "PNG"):
                temporary.replace(target)
        finally:
            temporary.unlink(missing_ok=True)
    except (OSError, RuntimeError, ValueError):
        pass


def project_summary(filepath):
    """Read display metadata without loading meshes or editor windows."""
    path = Path(filepath)
    is_part = path.suffix.lower() == ".simuopart"
    kind = "Part" if is_part else "Scene"
    data = {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(data, dict):
            data = {}
    except (OSError, ValueError, UnicodeError):
        pass
    name = data.get("name")
    if not isinstance(name, str) or not name.strip():
        name = path.stem
    try:
        modified = datetime.fromtimestamp(path.stat().st_mtime)
        description = f"Modified {modified:%b} {modified.day}, {modified.year}"
    except OSError:
        description = ""
    return name, description, kind
