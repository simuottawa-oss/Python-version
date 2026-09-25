import os
import stat
import sys
from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtCore import QLibraryInfo
from PySide6.QtGui import QPixmap, QSurfaceFormat
from PySide6.QtWidgets import (
    QApplication,
    QDialog,
    QFileDialog,
    QLabel,
    QPushButton,
    QVBoxLayout,
)

from simuO import SimuOMainWindow


class StartupDialog(QDialog):
    """Qt startup dialog, kept in the same event loop as the OpenGL window."""

    def __init__(self):
        super().__init__()

        self.action = None
        self.filepath = None

        self.setWindowTitle("SimuO")
        self.setFixedSize(520, 610)
        self.setStyleSheet(
            """
            QDialog { background-color: #1f1f1f; }
            QLabel { color: #f2f2f2; }
            QPushButton {
                color: #f5f5f5;
                background-color: #3f3f3f;
                border: 1px solid #5a5a5a;
                border-radius: 6px;
                padding: 10px;
                font-size: 13px;
                font-weight: bold;
            }
            QPushButton:hover { background-color: #525252; }
            """
        )

        layout = QVBoxLayout(self)
        layout.setContentsMargins(48, 36, 48, 42)
        layout.setSpacing(12)

        logo = QLabel()
        logo.setAlignment(Qt.AlignCenter)
        logo_path = (
            Path(__file__).resolve().parent.parent
            / "Images"
            / "simuo_logo.png"
        )
        pixmap = QPixmap(str(logo_path))
        if not pixmap.isNull():
            logo.setPixmap(
                pixmap.scaled(
                    390,
                    270,
                    Qt.KeepAspectRatio,
                    Qt.SmoothTransformation,
                )
            )
        layout.addWidget(logo, 1)

        title = QLabel("SimuO")
        title.setAlignment(Qt.AlignCenter)
        title.setStyleSheet("font-size: 24px; font-weight: bold;")
        layout.addWidget(title)

        subtitle = QLabel("3D Physics Simulator")
        subtitle.setAlignment(Qt.AlignCenter)
        subtitle.setStyleSheet("color: #9c9c9c; font-size: 12px;")
        layout.addWidget(subtitle)
        layout.addSpacing(18)

        new_button = QPushButton("New Scene")
        new_button.clicked.connect(self.new_project)
        layout.addWidget(new_button)

        import_button = QPushButton("Import Scene")
        import_button.clicked.connect(self.import_project)
        layout.addWidget(import_button)

    def new_project(self):
        self.action = "new"
        self.accept()

    def import_project(self):
        filepath, _ = QFileDialog.getOpenFileName(
            self,
            "Import SimuO Project",
            "",
            "SimuO Projects (*.simuO);;All Files (*)",
        )
        if filepath:
            self.action = "import"
            self.filepath = filepath
            self.accept()


def configure_opengl():
    # Desktop/iCloud can mark downloaded dylibs as hidden. Qt ignores hidden
    # files while scanning its plugin directories, including libqcocoa.dylib.
    cocoa_plugin = (
        Path(QLibraryInfo.path(QLibraryInfo.PluginsPath))
        / "platforms"
        / "libqcocoa.dylib"
    )
    if (
        sys.platform == "darwin"
        and hasattr(os, "chflags")
        and cocoa_plugin.exists()
    ):
        flags = cocoa_plugin.stat().st_flags
        if flags & stat.UF_HIDDEN:
            os.chflags(cocoa_plugin, flags & ~stat.UF_HIDDEN)

    # The format must be selected before QApplication creates any windows.
    surface_format = QSurfaceFormat()
    surface_format.setVersion(3, 3)
    surface_format.setProfile(QSurfaceFormat.CoreProfile)
    surface_format.setDepthBufferSize(24)
    QSurfaceFormat.setDefaultFormat(surface_format)


def main():
    configure_opengl()
    application = QApplication(sys.argv)

    startup = StartupDialog()
    if startup.exec() != QDialog.Accepted:
        return 0

    if startup.action == "new":
        print("Creating new SimuO build")
        window = SimuOMainWindow()
    else:
        print("Opening project:", startup.filepath)
        window = SimuOMainWindow(projectPath=startup.filepath)

    window.show()
    return application.exec()


if __name__ == "__main__":
    raise SystemExit(main())
