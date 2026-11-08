"""Startup chooser for the scene and part editors."""

from PySide6.QtCore import QRectF, Qt
from PySide6.QtGui import QPainter, QPainterPath, QPixmap
from PySide6.QtWidgets import (
    QDialog, QFileDialog, QFrame, QHBoxLayout, QLabel, QLayout, QPushButton, QVBoxLayout, QWidget,
)

from simuo.resources.paths import resource_path
from simuo.ui.theme import load_stylesheet


class StartupDialog(QDialog):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("SimuO")
        self.setWindowFlag(Qt.WindowType.WindowMaximizeButtonHint, False)
        self.setObjectName("startupDialog")
        self.setStyleSheet(load_stylesheet("startup"))
        self.choice = (None, None)

        window_layout = QVBoxLayout(self)
        window_layout.setSizeConstraint(QLayout.SizeConstraint.SetFixedSize)
        window_layout.setContentsMargins(28, 28, 28, 28)
        content = QWidget()
        content.setFixedWidth(444)
        window_layout.addWidget(content, alignment=Qt.AlignmentFlag.AlignCenter)
        layout = QVBoxLayout(content)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(14)
        brand = QHBoxLayout()
        brand.setSpacing(16)
        logo = QPixmap(str(resource_path("Images", "simuo_logo.png")))
        if not logo.isNull():
            image = QLabel()
            ratio = self.devicePixelRatioF()
            size = round(88 * ratio)
            mark = QPixmap(size, size)
            mark.fill(Qt.GlobalColor.transparent)
            bounds = QRectF(0, 0, size, size)
            clip = QPainterPath()
            clip.addEllipse(bounds)
            with QPainter(mark) as painter:
                painter.setRenderHints(QPainter.RenderHint.Antialiasing | QPainter.RenderHint.SmoothPixmapTransform)
                painter.setClipPath(clip)
                # The circular mark is inset inside the source image's matte.
                painter.drawPixmap(bounds, logo, QRectF(62, 34, 595, 595))
            mark.setDevicePixelRatio(ratio)
            image.setPixmap(mark)
            brand.addWidget(image, alignment=Qt.AlignmentFlag.AlignVCenter)
        identity = QVBoxLayout()
        identity.setSpacing(3)
        title = QLabel("SimuO")
        title.setObjectName("startupTitle")
        identity.addWidget(title)
        subtitle = QLabel("3D physics simulator")
        subtitle.setObjectName("startupSubtitle")
        identity.addWidget(subtitle)
        brand.addLayout(identity, 1)
        brand.setAlignment(identity, Qt.AlignmentFlag.AlignVCenter)
        layout.addLayout(brand)

        scene_actions = (
            ("New Scene", "new", None),
            ("Import Scene", "import", "SimuO Projects (*.simuO);;All Files (*)"),
        )
        part_actions = (
            ("New Part", "new_part", None),
            ("Open Part…", "open_part", "SimuO Parts (*.simuOPart)"),
        )
        layout.addWidget(self.editor_card(
            "Scene Editor", "Arrange objects and simulate their motion.", scene_actions,
        ))
        layout.addWidget(self.editor_card(
            "Part Editor", "Sketch and extrude parts for your scenes.", part_actions,
        ))

    def editor_card(self, title, description, actions):
        card = QFrame()
        card.setObjectName("startupCard")
        layout = QVBoxLayout(card)
        layout.setContentsMargins(16, 14, 16, 16)
        layout.setSpacing(5)
        heading = QLabel(title)
        heading.setObjectName("startupHeading")
        layout.addWidget(heading)
        detail = QLabel(description)
        detail.setObjectName("startupDescription")
        layout.addWidget(detail)
        layout.addSpacing(7)

        buttons = QHBoxLayout()
        buttons.setSpacing(8)
        for label, action, file_filter in actions:
            button = QPushButton(label)
            button.setMinimumHeight(37)
            button.setCursor(Qt.CursorShape.PointingHandCursor)
            button.setAutoDefault(False)
            if action == "new":
                button.setObjectName("startupPrimary")
                button.setDefault(True)
            button.clicked.connect(
                lambda checked=False, a=action, caption=label, f=file_filter: self.choose(a, caption, f)
            )
            buttons.addWidget(button, 1)
        layout.addLayout(buttons)
        return card

    def choose(self, action, caption, file_filter):
        path = None
        if file_filter:
            path, _ = QFileDialog.getOpenFileName(self, caption, filter=file_filter)
            if not path:
                return
        self.choice = (action, path)
        self.accept()
