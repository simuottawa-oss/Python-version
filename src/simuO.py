import sys
from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtGui import QAction, QSurfaceFormat
from PySide6.QtWidgets import (
    QApplication,
    QMainWindow,
    QToolBar,
    QFileDialog,
    QDialog,
    QVBoxLayout,
    QFormLayout,
    QListWidget,
    QPushButton,
    QDoubleSpinBox,
    QDialogButtonBox,
    QLabel,
)

from scene import Scene, SceneObject
from renderer import OpenGLViewport


class SimuOMainWindow(QMainWindow):

    def __init__(
        self,
        projectPath=None,
        scene=None
    ):
        super().__init__()

        self.projectPath = projectPath

        if scene is None:
            scene = Scene()

        self.scene = scene

        self.setWindowTitle(
            "SimuO - Untitled"
        )

        self.resize(
            1280,
            800
        )

        self.setStyleSheet(
            """
            QMainWindow {
                background-color: #2b2b2b;
            }

            QMenuBar {
                background-color: #222222;
                color: #e8e8e8;
            }

            QMenuBar::item {
                padding: 6px 12px;
            }

            QMenuBar::item:selected {
                background-color: #3a3a3a;
            }

            QMenu {
                background-color: #2b2b2b;
                color: #eeeeee;
            }

            QMenu::item:selected {
                background-color: #444444;
            }

            QToolBar {
                background-color: #292929;
                border: none;
                spacing: 6px;
                padding: 8px;
            }

            QToolButton {
                color: white;
                background-color: #343434;
                border: 1px solid #666666;
                border-radius: 3px;
                min-width: 34px;
                min-height: 34px;
                font-size: 17px;
            }

            QToolButton:hover {
                background-color: #484848;
            }

            QToolButton:checked {
                background-color: #595959;
            }

            QDialog {
                background-color: #2b2b2b;
                color: white;
            }

            QLabel {
                color: white;
            }

            QListWidget {
                background-color: #222222;
                color: white;
                border: 1px solid #555555;
            }

            QListWidget::item {
                padding: 7px;
            }

            QListWidget::item:selected {
                background-color: #4a4a4a;
            }

            QPushButton {
                background-color: #3a3a3a;
                color: white;
                border: 1px solid #666666;
                padding: 7px;
                border-radius: 3px;
            }

            QPushButton:hover {
                background-color: #505050;
            }

            QDoubleSpinBox {
                background-color: #222222;
                color: white;
                border: 1px solid #666666;
                padding: 5px;
            }
            """
        )

        self.createMenus()
        self.createToolbar()

        self.viewport = OpenGLViewport(
            self,
            scene=self.scene
        )

        self.setCentralWidget(
            self.viewport
        )

    # ---------------------------------------------------------
    # FILE OPERATIONS
    # ---------------------------------------------------------

    def openFile(self):
        filePath, _ = QFileDialog.getOpenFileName(
            self,
            "Open File",
            "",
            "SimuO Project Files (*.simuO);;All Files (*)",
        )

        if not filePath:
            return

        print(
            "Opening project:",
            filePath
        )

        path = Path(
            filePath
        )

        if path.suffix == ".simuO":
            self.projectPath = path

            self.setWindowTitle(
                f"SimuO - {path.stem}"
            )

    def importFile(self):
        filePath, _ = QFileDialog.getOpenFileName(
            self,
            "Import File",
            "",
            "3D Model Files (*.obj);;All Files (*)",
        )

        if not filePath:
            return

        print(
            "Importing model:",
            filePath
        )

        path = Path(
            filePath
        )

        importedObject = SceneObject(
            name=path.stem,
            meshPath=path
        )

        self.scene.addObject(
            importedObject
        )

        self.viewport.addNewObject(
            importedObject
        )

    # ---------------------------------------------------------
    # REPOSITION TOOL
    # ---------------------------------------------------------

    def openRepositionObjectList(self):
        dialog = QDialog(
            self
        )

        dialog.setWindowTitle(
            "Reposition Object"
        )

        dialog.resize(
            350,
            400
        )

        layout = QVBoxLayout(
            dialog
        )

        label = QLabel(
            "Select an object to reposition:"
        )

        layout.addWidget(
            label
        )

        objectList = QListWidget()

        layout.addWidget(
            objectList
        )

        for sceneObject in self.scene.objects:
            if sceneObject.name == "Axis":
                continue
            objectList.addItem(
                sceneObject.name
            )

        selectButton = QPushButton(
            "Select"
        )

        layout.addWidget(
            selectButton
        )

        def selectObject():
            index = objectList.currentRow()

            if index < 0:
                return

            sceneObject = (
                self.scene.objects[
                    index + 1 # Skip the axis object
                ]
            )

            dialog.accept()

            self.openPositionDialog(
                sceneObject
            )

        selectButton.clicked.connect(
            selectObject
        )

        objectList.itemDoubleClicked.connect(
            lambda item: selectObject()
        )

        dialog.exec()

    def openPositionDialog(
        self,
        sceneObject
    ):
        dialog = QDialog(
            self
        )

        dialog.setWindowTitle(
            f"Reposition - {sceneObject.name}"
        )

        dialog.setMinimumWidth(
            300
        )

        mainLayout = QVBoxLayout(
            dialog
        )

        title = QLabel(
            f"Position: {sceneObject.name}"
        )

        mainLayout.addWidget(
            title
        )

        formLayout = QFormLayout()

        mainLayout.addLayout(
            formLayout
        )

        # -----------------------------------------------------
        # X POSITION
        # -----------------------------------------------------

        xInput = QDoubleSpinBox()

        xInput.setRange(
            -1000000.0,
            1000000.0
        )

        xInput.setDecimals(
            3
        )

        xInput.setValue(
            float(
                sceneObject.position[0]
            )
        )

        # -----------------------------------------------------
        # Y POSITION
        # -----------------------------------------------------

        yInput = QDoubleSpinBox()

        yInput.setRange(
            -1000000.0,
            1000000.0
        )

        yInput.setDecimals(
            3
        )

        yInput.setValue(
            float(
                sceneObject.position[1]
            )
        )

        # -----------------------------------------------------
        # Z POSITION
        # -----------------------------------------------------

        zInput = QDoubleSpinBox()

        zInput.setRange(
            -1000000.0,
            1000000.0
        )

        zInput.setDecimals(
            3
        )

        zInput.setValue(
            float(
                sceneObject.position[2]
            )
        )

        formLayout.addRow(
            "X:",
            xInput
        )

        formLayout.addRow(
            "Y:",
            yInput
        )

        formLayout.addRow(
            "Z:",
            zInput
        )

        # -----------------------------------------------------
        # OK / CANCEL
        # -----------------------------------------------------

        buttons = QDialogButtonBox(
            QDialogButtonBox.Ok
            | QDialogButtonBox.Cancel
        )

        mainLayout.addWidget(
            buttons
        )

        def applyPosition():
            x = xInput.value()
            y = yInput.value()
            z = zInput.value()

            sceneObject.setPosition(
                x,
                y,
                z
            )

            print(
                f"Moved {sceneObject.name} "
                f"to ({x}, {y}, {z})"
            )

            self.viewport.update()

            dialog.accept()

        buttons.accepted.connect(
            applyPosition
        )

        buttons.rejected.connect(
            dialog.reject
        )

        dialog.exec()

    # ---------------------------------------------------------
    # MENUS
    # ---------------------------------------------------------

    def createMenus(self):

        fileMenu = (
            self.menuBar()
            .addMenu("File")
        )

        self.menuBar().addMenu(
            "Edit"
        )

        self.menuBar().addMenu(
            "Window"
        )

        self.menuBar().addMenu(
            "Help"
        )

        newAction = QAction(
            "New",
            self
        )

        openAction = QAction(
            "Open",
            self
        )

        importAction = QAction(
            "Import",
            self
        )

        exitAction = QAction(
            "Exit",
            self
        )

        openAction.triggered.connect(
            self.openFile
        )

        importAction.triggered.connect(
            self.importFile
        )

        exitAction.triggered.connect(
            self.close
        )

        fileMenu.addAction(
            newAction
        )

        fileMenu.addAction(
            openAction
        )

        fileMenu.addAction(
            importAction
        )

        fileMenu.addSeparator()

        fileMenu.addAction(
            exitAction
        )

    # ---------------------------------------------------------
    # LEFT TOOLBAR
    # ---------------------------------------------------------

    def createToolbar(self):

        toolbar = QToolBar(
            "Tools",
            self
        )

        toolbar.setMovable(
            False
        )

        self.addToolBar(
            Qt.LeftToolBarArea,
            toolbar
        )

        self.toolActions = []

        tools = [
            ("Select", "➤"),
            ("Reposition", "⇄"),
            ("Pan", "✋"),
            ("Rotate", "⟳"),
            ("Move", "✥"),
        ]

        for index, (
            name,
            symbol
        ) in enumerate(
            tools
        ):

            action = QAction(
                symbol,
                self
            )

            action.setToolTip(
                name
            )

            action.setCheckable(
                True
            )

            action.triggered.connect(
                lambda checked,
                n=name:
                self.toolSelected(n)
            )

            toolbar.addAction(
                action
            )

            self.toolActions.append(
                action
            )

            if index == 0:
                action.setChecked(
                    True
                )

    def toolSelected(
        self,
        name
    ):

        sender = self.sender()

        for action in self.toolActions:
            action.setChecked(
                action is sender
            )

        print(
            "Selected tool:",
            name
        )

        if name == "Reposition":
            self.openRepositionObjectList()


class App:

    def __init__(
        self,
        projectPath=None,
        scene=None
    ):

        self.projectPath = (
            projectPath
        )

        self.scene = scene

        self.window = None

        if self.scene is None:
            self.scene = Scene()

    def run(self):

        # Must be configured before QApplication is created.
        surfaceFormat = QSurfaceFormat()

        surfaceFormat.setVersion(
            3,
            3
        )

        surfaceFormat.setProfile(
            QSurfaceFormat.CoreProfile
        )

        surfaceFormat.setDepthBufferSize(
            24
        )

        QSurfaceFormat.setDefaultFormat(
            surfaceFormat
        )

        app = QApplication.instance()

        ownsApp = (
            app is None
        )

        if app is None:
            app = QApplication(
                sys.argv
            )

        projectRoot = (
            Path(__file__)
            .resolve()
            .parent
            .parent
        )

        axis = SceneObject(
            name="Axis",
            meshPath=(
                projectRoot
                / "axis.obj"
            )
        )

        self.scene.addObject(
            axis
        )

        self.window = SimuOMainWindow(
            projectPath=self.projectPath,
            scene=self.scene
        )

        self.window.show()

        if ownsApp:
            return app.exec()

        return 0