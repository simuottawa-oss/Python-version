"""Qt startup chooser for the SimuO application."""

from pathlib import Path

from PySide6.QtCore import (Qt, QSize, QRectF, QFile)
from PySide6.QtGui import (QPixmap, QIcon, QPainter, QPainterPath)
from PySide6.QtSvg import QSvgRenderer
from PySide6.QtWidgets import (
    QApplication,
    QDialog,
    QFileDialog,
    QFrame,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QSizePolicy,
    QVBoxLayout,
    QGridLayout,
    QScrollArea,
    QMenu,
    QMessageBox,
    QWidget,
    QDialogButtonBox,
    QButtonGroup,
    QToolButton)

from simuo.ui.recent_projects import recent_projects, thumbnail_path, project_summary, forget_project
from simuo.resources.paths import resource_path
from simuo.ui.theme import load_stylesheet


def _svg_icon(path, size=24):
    
    renderer = QSvgRenderer(str(Path(path)))
    if not renderer.isValid():
        return QIcon()

    pixmap = QPixmap(size, size)
    pixmap.fill(Qt.GlobalColor.transparent)
    painter = QPainter(pixmap)
    renderer.render(painter)
    painter.end()
    return QIcon(pixmap)


class CardDetails(QWidget):
    """Reserve enough height for the caption as its text wraps."""

    def resizeEvent(self, event):
        super().resizeEvent(event)
        if self.layout() is not None:
            layout = self.layout()
            margins = layout.contentsMargins()
            width = max(1, self.width() - margins.left() - margins.right())
            labels = self.findChildren(QLabel)
            height = 0
            for label in labels:
                label_height = max(label.minimumSizeHint().height(),
                label.heightForWidth(width))
                label.setFixedHeight(label_height)
                height += label_height
            self.setFixedHeight(height + margins.top() + margins.bottom()
                                + layout.spacing() * max(0, len(labels) - 1))
            self.parentWidget().setMinimumHeight(max(380, self.height() + 222))


class CardThumbnail(QWidget):
    """Fill the available card space with an undistorted, center-cropped image."""

    def __init__(self, image_path, parent=None):
        super().__init__(parent)
        self._pixmap = QPixmap(str(image_path))
        self.setMinimumHeight(220)
        self.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Expanding)
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)

    def paintEvent(self, event):
        if self._pixmap.isNull():
            return

        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)
        if not self.isEnabled():
            painter.setOpacity(0.35)

        # Keep the image inside the card's rounded top corners.
        clip = QPainterPath()
        clip.setFillRule(Qt.FillRule.WindingFill)
        clip.addRoundedRect(QRectF(self.rect()), 13, 13)
        clip.addRect(QRectF(0, 13, self.width(), max(0, self.height() - 13)))
        painter.setClipPath(clip.simplified())

        scale = max(self.width() / self._pixmap.width(),
                    self.height() / self._pixmap.height())
        source_width = self.width() / scale
        source_height = self.height() / scale
        offsetx = 0     
        offsety = 0
        source = QRectF(
            (self._pixmap.width() - source_width) / 2 + offsetx,
            (self._pixmap.height() - source_height) / 2 + offsety,
            source_width,
            source_height,
        )
        painter.drawPixmap(QRectF(self.rect()), self._pixmap, source)


class RecentProjectCard(QToolButton):
    """Keep the preview at 16:9 and the caption at its natural height."""

    def resizeEvent(self, event):
        super().resizeEvent(event)
        preview = self.findChild(CardThumbnail)
        details = self.findChild(QWidget, "recentProjectDetails")
        if preview is not None and details is not None:
            height = round(max(1, self.width() - 2) * 9 / 16)
            preview.setFixedHeight(height)
            self.setFixedHeight(height + details.sizeHint().height() + 2)
            title = details.findChild(QLabel, "recentProjectName")
            if title is not None:
                title.setText(title.fontMetrics().elidedText(
                    self.property("projectName"), Qt.TextElideMode.ElideRight,
                    max(1, self.width() - 30),
                ))


class RecentProjectsGrid(QWidget):
    """Reflow recent cards to fit the available startup-panel width."""

    def __init__(self, cards, parent=None):
        super().__init__(parent)
        self._cards = cards
        self._columns = 0
        self._grid = QGridLayout(self)
        self._grid.setContentsMargins(0, 0, 0, 0)
        self._grid.setSpacing(16)
        self._grid.setAlignment(Qt.AlignmentFlag.AlignTop)
        self._reflow(1)

    def _reflow(self, columns):
        if columns == self._columns:
            return
        for card in self._cards:
            self._grid.removeWidget(card)
        for column in range(self._columns):
            self._grid.setColumnStretch(column, 0)
        self._columns = columns
        for index, card in enumerate(self._cards):
            self._grid.addWidget(card, index // columns, index % columns)
        for column in range(columns):
            self._grid.setColumnStretch(column, 1)

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self._reflow(max(1, min(3, (self.width() + 16) // 276)))

    def remove_card(self, card):
        self._grid.removeWidget(card)
        self._cards.remove(card)
        card.hide()
        card.deleteLater()
        columns = self._columns
        self._columns = 0
        self._reflow(columns)
        if not self._cards:
            message = QLabel("No recent projects yet", self)
            message.setObjectName("welcomeSubtitle")
            self._grid.addWidget(message, 0, 0)


class SimuOStartMenu(QDialog):
    """Modal Qt dialog for choosing a scene or part-editor startup action."""

    def __init__(
        self,
        parent=None,
        logo_path=None,
        on_new=None,
        on_import=None,
        title="SimuO",
        width=1100,
        height=700,
        on_new_part=None,
        on_open_part=None,
    ):
        super().__init__(parent)

        self.on_new = on_new
        self.on_import = on_import
        self.on_new_part = on_new_part
        self.on_open_part = on_open_part

        self.setObjectName("startupDialog")
        self.setWindowTitle(title)
        self.setWindowModality(Qt.WindowModality.ApplicationModal)
        self.setModal(True)
        self.setFixedSize(max(740, width), max(560, height))
        self.setStyleSheet(load_stylesheet("startup"))

        self._build_ui(logo_path)

    def showEvent(self, event):
        """Center the fixed-size chooser on its current screen."""
        super().showEvent(event)
        screen = self.screen() or QApplication.primaryScreen()
        if screen is not None:
            geometry = self.frameGeometry()
            geometry.moveCenter(screen.availableGeometry().center())
            self.move(geometry.topLeft())

    def _build_ui(self, logo_path):
        """Build the action panel and welcome panel."""
        outer = QHBoxLayout(self)
        outer.setContentsMargins(1, 1, 1, 1)
        outer.setSpacing(0)

        actions = QFrame(self)
        actions.setObjectName("actionPanel")
        actions.setMinimumWidth(280)
        actions.setMaximumWidth(520)
        actions_layout = QVBoxLayout(actions)
        actions_layout.setContentsMargins(20, 56, 20, 56)
        actions_layout.setSpacing(10)

        title_label = QLabel("Welcome!", actions)
        title_label.setObjectName("Title")
        title_label.setAlignment(Qt.AlignmentFlag.AlignLeft)
        actions_layout.addWidget(title_label)
        actions_layout.setSpacing(0)
        subtitle = QLabel("What will you make today?", actions)
        subtitle.setObjectName("welcomeSubtitle")
        subtitle.setAlignment(Qt.AlignmentFlag.AlignLeft)
        actions_layout.addWidget(subtitle)
        actions_layout.addSpacing(20)
        actions_layout.setSpacing(10)


        scene_editor = QLabel("SCENE EDITOR", actions)
        scene_editor.setObjectName("sectionHeading")
        scene_editor.setAlignment(Qt.AlignmentFlag.AlignLeft)
        actions_layout.addWidget(scene_editor)

        actions_layout.addWidget(self._action_button("New Scene", self._show_new_scene_options, actions, resource_path("Images", "plus-circle.svg")))

        actions_layout.addWidget(
            self._action_button("Import Scene…", self._import_project, actions, resource_path("Images", "folder.svg"))
        )
        
        # Separator line
        separator = QFrame(actions)
        separator.setObjectName("actionSeparator")
        separator.setFrameShape(QFrame.Shape.NoFrame)
        separator.setFixedHeight(1)

        actions_layout.addSpacing(10)
        actions_layout.addWidget(separator)
        actions_layout.addSpacing(2)


        # Part editor section
        part_editor = QLabel("PART EDITOR", actions)
        part_editor.setObjectName("sectionHeading")
        part_editor.setAlignment(Qt.AlignmentFlag.AlignLeft)
        actions_layout.addWidget(part_editor)


        actions_layout.addWidget(self._action_button("New Part", self._new_part, actions, resource_path("Images", "plus-circle.svg")))
        actions_layout.addWidget(self._action_button("Open Part…", self._open_part, actions, resource_path("Images", "folder.svg")))
        
        
        actions_layout.addStretch(1)

        recent = QWidget(self)
        recent.setObjectName("recentProjectsPanel")

        recent_layout = QVBoxLayout(recent)
        recent_layout.setContentsMargins(48, 48, 48, 48)
        recent_layout.setSpacing(14)

        paths = recent_projects()
        if paths:
            heading = QLabel("Recent Projects", recent)
            heading.setObjectName("menuTitle")
            recent_layout.addWidget(heading)
            scroll = QScrollArea(recent)
            scroll.setObjectName("recentProjectsScroll")
            scroll.setWidgetResizable(True)
            scroll.setFrameShape(QFrame.Shape.NoFrame)
            scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
            cards = [self._recent_project_card(path) for path in paths]
            grid = RecentProjectsGrid(cards)
            grid.setObjectName("recentProjectsGrid")
            scroll.setWidget(grid)
            recent_layout.addWidget(scroll, 1)
        else:
            recent_layout.addStretch(1)
            # Rounded icon background
            icon_tile = QLabel(recent)
            icon_tile.setObjectName("emptyIconTile")
            icon_tile.setFixedSize(80, 80)
            icon_tile.setAlignment(Qt.AlignmentFlag.AlignCenter)

            folder_icon = _svg_icon(
                resource_path("Images", "folder.svg"),
                size=36,
            )
            icon_tile.setPixmap(folder_icon.pixmap(36, 36))

            recent_layout.addWidget(
                icon_tile,
                alignment=Qt.AlignmentFlag.AlignHCenter,
            )

            # Heading
            empty_title = QLabel("No recent projects yet :(", recent)
            empty_title.setObjectName("emptyTitle")
            empty_title.setAlignment(Qt.AlignmentFlag.AlignCenter)
            recent_layout.addWidget(empty_title)

            # Description
            empty_description = QLabel(
                "Create a scene or part to get started."
            )
            empty_description.setObjectName("emptyDescription")
            empty_description.setAlignment(Qt.AlignmentFlag.AlignCenter)
            empty_description.setWordWrap(True)
            empty_description.setMinimumWidth(360)
            empty_description.setMaximumWidth(640)

            recent_layout.addWidget(
                empty_description,
                alignment=Qt.AlignmentFlag.AlignHCenter,
            )

            recent_layout.addStretch(1)

        outer.addWidget(actions)
        outer.addWidget(recent, 1)

    def _recent_project_card(self, filepath):
        name, description, kind = project_summary(filepath)
        card = RecentProjectCard(self)
        card.setObjectName("recentProjectCard")
        card.setProperty("projectName", name)
        card.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Fixed)
        card.setToolTip(f"{name}\n{description}\n\n{filepath}")
        card.setAccessibleName(f"Open {kind.lower()}: {name}")
        card.clicked.connect(lambda checked=False, path=filepath: self._open_recent(path))
        layout = QVBoxLayout(card)
        layout.setContentsMargins(1, 1, 1, 1)
        layout.setSpacing(0)

        preview = CardThumbnail(thumbnail_path(filepath), card)
        preview.setFixedHeight(150)
        if preview._pixmap.isNull():
            placeholder_layout = QVBoxLayout(preview)
            placeholder_layout.setAlignment(Qt.AlignmentFlag.AlignCenter)
            icon = QLabel(preview)
            icon.setAlignment(Qt.AlignmentFlag.AlignCenter)
            icon.setPixmap(_svg_icon(resource_path("Images", "folder.svg"), 36).pixmap(36, 36))
            placeholder_layout.addWidget(icon)
            hint = QLabel("Preview available after saving", preview)
            hint.setObjectName("recentPreviewHint")
            hint.setAlignment(Qt.AlignmentFlag.AlignCenter)
            placeholder_layout.addWidget(hint)
        layout.addWidget(preview)

        details = QWidget(card)
        details.setObjectName("recentProjectDetails")
        text_layout = QVBoxLayout(details)
        text_layout.setContentsMargins(14, 14, 14, 14)
        text_layout.setSpacing(12)
        kind_label = QLabel("KINEMATICS SCENE" if kind == "Scene" else "PART", details)
        kind_label.setObjectName("recentProjectKind")
        text_layout.addWidget(kind_label)
        title = QLabel(name, details)
        title.setTextFormat(Qt.TextFormat.PlainText)
        title.setObjectName("recentProjectName")
        title.setWordWrap(False)
        title.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Fixed)
        title.setMinimumWidth(0)
        title.ensurePolished()
        title.setFixedHeight(title.sizeHint().height())
        text_layout.addWidget(title)
        caption = QLabel(description, details)
        caption.setTextFormat(Qt.TextFormat.PlainText)
        caption.setObjectName("recentProjectDescription")
        caption.setWordWrap(False)
        caption.setMinimumWidth(0)
        caption.ensurePolished()
        caption.setFixedHeight(caption.sizeHint().height())
        footer = QHBoxLayout()
        footer.setContentsMargins(0, 0, 0, 0)
        footer.addWidget(caption, 1)
        options = QToolButton(details)
        options.setObjectName("recentProjectOptions")
        options.setText("\u2022\u2022\u2022")
        options.setFixedSize(28, 24)
        options.setToolTip("Project options")
        options.setAccessibleName(f"Options for {name}")
        options.setPopupMode(QToolButton.ToolButtonPopupMode.InstantPopup)
        menu = QMenu(options)
        menu.addAction("Open project", lambda: self._open_recent(filepath))
        menu.addAction("Copy file path", lambda: QApplication.clipboard().setText(str(filepath)))
        menu.addSeparator()
        menu.addAction("Delete project\u2026", lambda: self._delete_recent_project(filepath, card))
        options.setMenu(menu)
        footer.addWidget(options)
        text_layout.addLayout(footer)
        for label in (kind_label, title, caption):
            label.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
        layout.addWidget(details)
        card.setFixedHeight(150 + details.sizeHint().height() + 2)
        return card

    def _open_recent(self, filepath):
        callback = (self.on_open_part if Path(filepath).suffix.lower() == ".simuopart"
                    else self.on_import)
        self._finish(callback, filepath)

    def _delete_recent_project(self, filepath, card):
        path = Path(filepath)
        answer = QMessageBox.question(
            self,
            "Delete Project",
            f'Move "{path.name}" to the Recycle Bin?\n\n{path}\n\n'
            "Only this project file will be moved. Referenced parts and other assets "
            "will be kept. You can restore the file from the Recycle Bin.",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.Cancel,
            QMessageBox.StandardButton.Cancel,
        )
        if answer != QMessageBox.StandardButton.Yes:
            return
        # QFile uses the system trash; never fall back to permanent deletion.
        try:
            result = QFile.moveToTrash(str(path))
            moved = result[0] if isinstance(result, tuple) else result
        except (OSError, RuntimeError):
            moved = False
        if not moved:
            QMessageBox.warning(
                self, "Cannot Delete Project",
                "The project could not be moved to the Recycle Bin. "
                "It has not been removed from Recent Projects.",
            )
            return
        forget_project(filepath)
        grid = card.parentWidget()
        if isinstance(grid, RecentProjectsGrid):
            grid.remove_card(card)


    @staticmethod

    def _menu_button(text, parent, icon_path=None):
        button = QPushButton(text, parent)
        button.setObjectName("menuButton")
        button.setFixedHeight(38)
        button.setMinimumHeight(14)
        button.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)

        if icon_path:
            button.setIcon(_svg_icon(icon_path))
            button.setIconSize(QSize(14, 14))
        return button

    @staticmethod
    def _action_button(text, callback, parent, icon_path=None):
        button = QPushButton(text, parent)
        button.setObjectName("startupAction")
        button.setFixedHeight(38)
        button.setMinimumHeight(14)
        button.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        button.clicked.connect(callback)
        if icon_path:
            button.setIcon(_svg_icon(icon_path))
            button.setIconSize(QSize(14, 14))

        return button

    @staticmethod
    def _logo_widget(logo_path, parent):
        """Return the supplied logo, or a text mark when it cannot be loaded."""
        label = QLabel(parent)
        label.setAlignment(Qt.AlignmentFlag.AlignCenter)

        if logo_path:
            pixmap = QPixmap(str(Path(logo_path)))
            if not pixmap.isNull():
                label.setPixmap(
                    pixmap.scaled(
                        300,
                        150,
                        Qt.AspectRatioMode.KeepAspectRatio,
                        Qt.TransformationMode.SmoothTransformation,
                    )
                )
                return label

        label.setText("SimuO")
        return label

    def _finish(self, callback, *args):
        """Close the chooser, then report the selected action."""
        self.accept()
        if callback is not None:
            callback(*args)

    def _new_project(self):
        self._finish(self.on_new)

    def _show_new_scene_options(self):
        dialog = QDialog(self)
        dialog.setObjectName("scenePicker")
        dialog.setWindowTitle("Create New Scene")
        dialog.resize(960, 560)

        layout = QVBoxLayout(dialog)
        layout.setContentsMargins(24, 24, 24, 24)
        layout.setSpacing(18)

        title = QLabel("Create New Scene", dialog)
        title.setObjectName("Title")
        layout.addWidget(title)

        subtitle = QLabel(
            "Choose the type of simulation you want to create.",
            dialog,
        )
        subtitle.setObjectName("welcomeSubtitle")
        layout.addWidget(subtitle)

        separator = QFrame(dialog)
        separator.setObjectName("actionSeparator")
        separator.setFixedHeight(1)
        layout.addWidget(separator)

        cards_layout = QHBoxLayout()
        cards_layout.setSpacing(12)

        group = QButtonGroup(dialog)
        group.setExclusive(True)

        # These image files need to be added to your Images folder.
        choices = [
            (
                "Kinematics & Dynamics",
                "Model motion, forces, collisions,\nand mechanical systems.",
                "kinematics-preview.png",
                True,
            ),
            (
                "CFD Analysis",
                "Simulate airflow, pressure, and fluid\nbehavior around geometry.",
                "cfd-preview.png",
                False,
            ),
            (
                "Structural Analysis",
                "Evaluate stress, strain, and deformation\nunder applied loads.",
                "structural-preview.png",
                False,
            ),
        ]

        for index, (name, description, image, available) in enumerate(choices):
            card = QToolButton(dialog)
            card.setObjectName("sceneTypeCard")
            card.setCheckable(True)
            card.setToolButtonStyle(
                Qt.ToolButtonStyle.ToolButtonTextUnderIcon
            )
            card.setSizePolicy(
                QSizePolicy.Policy.Expanding,
                QSizePolicy.Policy.Expanding,
            )
            card.setMinimumSize(300, 380)

            card.setText("")

            card_layout = QVBoxLayout(card)
            card_layout.setContentsMargins(1, 1, 1, 1)
            card_layout.setSpacing(0)

            preview = CardThumbnail(resource_path("Images", image), card)
            card_layout.addWidget(preview, 1)

            if not available:
                preview_layout = QVBoxLayout(preview)
                preview_layout.setContentsMargins(14, 14, 14, 14)
                preview_layout.addStretch()

            # Reserve the text's natural height; give the remaining space to the image.
            details = CardDetails(card)
            details.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Fixed)
            details.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
            details_layout = QVBoxLayout(details)
            details_layout.setContentsMargins(12, 16, 12, 16)
            details_layout.setSpacing(10)

            name_label = QLabel(name, details)
            name_label.setObjectName("menuTitle")
            name_label.setWordWrap(True)
            details_layout.addWidget(name_label)

            description_label = QLabel(description.replace("\n", " "), details)
            description_label.setObjectName("welcomeSubtitle")
            description_label.setWordWrap(True)
            details_layout.addWidget(description_label)
            card_layout.addWidget(details)

            # Let clicks on the labels reach the checkable card.
            for label in (preview, name_label, description_label):
                label.setAttribute(
                    Qt.WidgetAttribute.WA_TransparentForMouseEvents
                )

            # Enable these once the corresponding editors exist.
            card.setEnabled(available)
            if not available:
                card.setToolTip("Not yet implemented. This simulation type is coming soon.")
                card.setAccessibleDescription("Coming soon. Not yet available for creation.")

            group.addButton(card, index)
            cards_layout.addWidget(card)

            if index == 0:
                card.setChecked(True)

        layout.addLayout(cards_layout, 1)

        bottom = QHBoxLayout()
        bottom.addStretch()

        cancel_button = QPushButton("Cancel", dialog)
        cancel_button.clicked.connect(dialog.reject)

        create_button = QPushButton("Create Scene", dialog)
        create_button.setObjectName("menuButton")
        create_button.clicked.connect(dialog.accept)
        create_button.setDefault(True)

        bottom.addWidget(cancel_button)
        bottom.addWidget(create_button)
        layout.addLayout(bottom)

        if dialog.exec() == QDialog.DialogCode.Accepted:
            self._new_project()     
            
    def _import_project(self):
        filename, _ = QFileDialog.getOpenFileName(
            self,
            "Import SimuO Project",
            "",
            "SimuO Projects (*.simuO);;All Files (*)",
        )
        if filename:
            self._finish(self.on_import, filename)

    def _new_part(self):
        self._finish(self.on_new_part)

    def _open_part(self):
        filename, _ = QFileDialog.getOpenFileName(
            self,
            "Open SimuO Part",
            "",
            "SimuO Parts (*.simuOPart)",
        )
        if filename:
            self._finish(self.on_open_part, filename)

    def _close(self):
        """Compatibility helper for callers that closed the former Tk dialog."""
        self.reject()


def showStartMenu(
    parent=None,
    logo_path=None,
    on_new=None,
    on_import=None,
    on_new_part=None,
    on_open_part=None,
):
    """Construct and return the modal Qt startup chooser."""
    return SimuOStartMenu(
        parent=parent,
        logo_path=logo_path,
        on_new=on_new,
        on_import=on_import,
        on_new_part=on_new_part,
        on_open_part=on_open_part,
    )


if __name__ == "__main__":
    app = QApplication.instance() or QApplication([])
    menu = showStartMenu(
        logo_path=resource_path("Images", "simuo_logo.png"),
        on_new=lambda: print("New .simuO build selected"),
        on_import=lambda filepath: print("Imported:", filepath),
        on_new_part=lambda: print("New part selected"),
        on_open_part=lambda filepath: print("Opened part:", filepath),
    )
    menu.exec()
