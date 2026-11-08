"""Select the application GL format before creating any Qt windows."""

from PySide6.QtGui import QSurfaceFormat


def configure_opengl():
    # The format must be selected before QApplication creates any windows.
    surface_format = QSurfaceFormat()
    surface_format.setVersion(3, 3)
    surface_format.setProfile(QSurfaceFormat.CoreProfile)
    surface_format.setDepthBufferSize(24)
    QSurfaceFormat.setDefaultFormat(surface_format)
