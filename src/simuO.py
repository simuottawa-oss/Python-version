import sys
from pathlib import Path
import json
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
    QMessageBox,
)

from scene import Scene, SceneObject
from renderer import OpenGLViewport


class SimuOMainWindow(QMainWindow):
    def __init__(self, projectPath=None, scene=None):
        super().__init__()

        self.projectPath = projectPath

        if scene is None:
            scene = Scene()

        self.scene = scene

        self.setWindowTitle("SimuO - Untitled")

        self.resize(1280, 800)

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

        self.viewport = OpenGLViewport(self, scene=self.scene)

        self.setCentralWidget(self.viewport)
        
        if projectPath is not None:
            self.loadFile(projectPath,uploadToGPU=False)


    # ---------------------------------------------------------
    # FILE OPERATIONS
    # ---------------------------------------------------------

    def newProject(self):

        if self.scene.sceneHasObjects():
            response = QMessageBox.question(
                self,
                "New Project",
                "The current project contains objects. "
                "Would you like to save before creating a new project?",
                QMessageBox.Save | QMessageBox.Discard | QMessageBox.Cancel,
            )

            if response == QMessageBox.Cancel:
                return

            if response == QMessageBox.Save:
                if self.projectPath is None:
                    self.saveAsFile()
                else:
                    self.saveFile()

                # If the user cancelled the Save dialog,
                # don't destroy the current scene.
                if self.projectPath is None:
                    return

        self.scene.objects.clear()

        self.viewport.clearRenderObjects()

        self.projectPath = None

        self.setWindowTitle("SimuO - Untitled")

        self.viewport.update()
        
        
    def loadFile(
        self,
        path,
        uploadToGPU=True
    ):
        with open(
            path,
            "r",
            encoding="utf-8"
        ) as file:
            data = json.load(
                file
            )

        self.scene.objects.clear()

        if uploadToGPU:
            self.viewport.clearRenderObjects()

        for objectData in data.get(
            "objects",
            []
        ):
            sceneObject = SceneObject(
                name=objectData["name"],
                meshPath=Path(
                    objectData["meshPath"]
                )
            )

            position = objectData.get(
                "position",
                [0.0, 0.0, 0.0]
            )

            rotation = objectData.get(
                "rotation",
                [0.0, 0.0, 0.0]
            )

            scale = objectData.get(
                "scale",
                [1.0, 1.0, 1.0]
            )

            sceneObject.setPosition(
                position[0],
                position[1],
                position[2]
            )

            sceneObject.setRotation(
                rotation[0],
                rotation[1],
                rotation[2]
            )

            sceneObject.scale = [
                scale[0],
                scale[1],
                scale[2]
            ]

            self.scene.addObject(
                sceneObject
            )

            if uploadToGPU:
                self.viewport.addNewObject(
                    sceneObject
                )

        self.projectPath = Path(
            path
        )

        self.setWindowTitle(
            f"SimuO - {self.projectPath.stem}"
        )

        if uploadToGPU:
            self.viewport.update()

        print(
            "Opened project:",
            path
        )
    def openFile(self):
        filePath, _ = QFileDialog.getOpenFileName(
            self,
            "Open SimuO Project",
            "",
            "SimuO Project Files (*.simuO);;All Files (*)",
        )

        if not filePath:
            return

        path = Path(filePath)

        self.loadFile(path, True)

    def importFile(self):
        filePath, _ = QFileDialog.getOpenFileName(
            self,
            "Import File",
            "",
            "3D Model Files (*.simuOPart);;All Files (*)",
        )

        if not filePath:
            return

        print("Importing model:", filePath)

        path = Path(filePath)

        importedObject = SceneObject(name=path.stem, meshPath=path)

        self.scene.addObject(importedObject)

        self.viewport.addNewObject(importedObject)

    def saveFile(self):
        if self.projectPath is None:
            filePath, _ = QFileDialog.getSaveFileName(
                self, "Save SimuO Project", "", "SimuO Project Files (*.simuO)"
            )

            if not filePath:
                return

            path = Path(filePath)

            if path.suffix.lower() != ".simuo":
                path = path.with_suffix(".simuO")

            self.projectPath = path

        data = {"version": 1, "objects": []}

        for sceneObject in self.scene.objects:
            # Skip editor-only objects like the axis
            if sceneObject.name == "Axis":
                continue

            objectData = {
                "name": sceneObject.name,
                "meshPath": str(sceneObject.meshPath),
                "position": list(sceneObject.position),
                "rotation": list(sceneObject.rotation),
                "scale": list(sceneObject.scale),
            }

            data["objects"].append(objectData)

        with open(self.projectPath, "w", encoding="utf-8") as file:
            json.dump(data, file, indent=4)

        self.setWindowTitle(f"SimuO - {self.projectPath.stem}")

        print("Saved project:", self.projectPath)

    def saveAsFile(self):
        filePath, _ = QFileDialog.getSaveFileName(
            self, "Save Scene as", "", "SimuO Project Files (*.simuO)"
        )

        if not filePath:
            return

        path = Path(filePath)

        if path.suffix.lower() != ".simuo":
            path = path.with_suffix(".simuO")

        self.projectPath = path

        self.saveFile()

    # ---------------------------------------------------------
    # SET ROTATION TOOL
    # ---------------------------------------------------------
    def openSetRotationObjectList(self):
        dialog = QDialog(self)

        dialog.setWindowTitle("Set Rotation")

        dialog.resize(350, 400)

        layout = QVBoxLayout(dialog)

        label = QLabel("Select an object to set rotation:")

        layout.addWidget(label)

        objectList = QListWidget()

        layout.addWidget(objectList)

        for sceneObject in self.scene.objects:
            if sceneObject.name == "Axis":
                continue
            objectList.addItem(sceneObject.name)

        selectButton = QPushButton("Select")

        layout.addWidget(selectButton)

        def selectObject():
            index = objectList.currentRow()

            if index < 0:
                return

            sceneObject = self.scene.objects[
                index
            ]

            dialog.accept()

            self.openSetRotationDialog(sceneObject)

        selectButton.clicked.connect(selectObject)

        objectList.itemDoubleClicked.connect(lambda item: selectObject())

        dialog.exec()

    def openSetRotationDialog(self, sceneObject):
        dialog = QDialog(self)

        dialog.setWindowTitle(f"Reposition - {sceneObject.name}")

        dialog.setMinimumWidth(300)

        mainLayout = QVBoxLayout(dialog)

        title = QLabel(f"Rotation (Degrees): {sceneObject.name}")

        mainLayout.addWidget(title)

        formLayout = QFormLayout()

        mainLayout.addLayout(formLayout)
        # -----------------------------------------------------
        # X Rotation
        # -----------------------------------------------------

        xInput = QDoubleSpinBox()

        xInput.setRange(0, 360.0)

        xInput.setDecimals(3)

        xInput.setValue(float(sceneObject.rotation[0]))
        # -----------------------------------------------------
        # Y Rotation
        # -----------------------------------------------------

        yInput = QDoubleSpinBox()

        yInput.setRange(0, 360.0)

        yInput.setDecimals(3)

        yInput.setValue(float(sceneObject.rotation[1]))

        # -----------------------------------------------------
        # Z Rotation
        # -----------------------------------------------------

        zInput = QDoubleSpinBox()

        zInput.setRange(0, 360.0)

        zInput.setDecimals(3)

        zInput.setValue(float(sceneObject.rotation[2]))

        # -----------------------------------------------------
        # Layout
        # -----------------------------------------------------

        formLayout.addRow("X:", xInput)

        formLayout.addRow("Y:", yInput)

        formLayout.addRow("Z:", zInput)

        # -----------------------------------------------------
        # OK / CANCEL
        # -----------------------------------------------------

        buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)

        mainLayout.addWidget(buttons)

        def applyRotation():
            x = xInput.value()
            y = yInput.value()
            z = zInput.value()

            sceneObject.setRotation(x, y, z)

            print(f"Rotated {sceneObject.name} to ({x}, {y}, {z})")

            self.viewport.update()

            dialog.accept()

        buttons.accepted.connect(applyRotation)

        buttons.rejected.connect(dialog.reject)

        dialog.exec()

    # ---------------------------------------------------------
    # REPOSITION TOOL
    # ---------------------------------------------------------

    def openRepositionObjectList(self):
        dialog = QDialog(self)

        dialog.setWindowTitle("Reposition Object")

        dialog.resize(350, 400)

        layout = QVBoxLayout(dialog)

        label = QLabel("Select an object to reposition:")

        layout.addWidget(label)

        objectList = QListWidget()

        layout.addWidget(objectList)

        for sceneObject in self.scene.objects:
            if sceneObject.name == "Axis":
                continue
            objectList.addItem(sceneObject.name)

        selectButton = QPushButton("Select")

        layout.addWidget(selectButton)

        def selectObject():
            index = objectList.currentRow()

            if index < 0:
                return

            sceneObject = self.scene.objects[
                index
            ]

            dialog.accept()

            self.openPositionDialog(sceneObject)

        selectButton.clicked.connect(selectObject)

        objectList.itemDoubleClicked.connect(lambda item: selectObject())

        dialog.exec()

    def openPositionDialog(self, sceneObject):
        dialog = QDialog(self)

        dialog.setWindowTitle(f"Reposition - {sceneObject.name}")

        dialog.setMinimumWidth(300)

        mainLayout = QVBoxLayout(dialog)

        title = QLabel(f"Position: {sceneObject.name}")

        mainLayout.addWidget(title)

        formLayout = QFormLayout()

        mainLayout.addLayout(formLayout)

        # -----------------------------------------------------
        # X POSITION
        # -----------------------------------------------------

        xInput = QDoubleSpinBox()

        xInput.setRange(-1000000.0, 1000000.0)

        xInput.setDecimals(3)

        xInput.setValue(float(sceneObject.position[0]))

        # -----------------------------------------------------
        # Y POSITION
        # -----------------------------------------------------

        yInput = QDoubleSpinBox()

        yInput.setRange(-1000000.0, 1000000.0)

        yInput.setDecimals(3)

        yInput.setValue(float(sceneObject.position[1]))

        # -----------------------------------------------------
        # Z POSITION
        # -----------------------------------------------------

        zInput = QDoubleSpinBox()

        zInput.setRange(-1000000.0, 1000000.0)

        zInput.setDecimals(3)

        zInput.setValue(float(sceneObject.position[2]))

        formLayout.addRow("X:", xInput)

        formLayout.addRow("Y:", yInput)

        formLayout.addRow("Z:", zInput)

        # -----------------------------------------------------
        # OK / CANCEL
        # -----------------------------------------------------

        buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)

        mainLayout.addWidget(buttons)

        def applyPosition():
            x = xInput.value()
            y = yInput.value()
            z = zInput.value()

            sceneObject.setPosition(x, y, z)

            print(f"Moved {sceneObject.name} to ({x}, {y}, {z})")

            self.viewport.update()

            dialog.accept()

        buttons.accepted.connect(applyPosition)

        buttons.rejected.connect(dialog.reject)

        dialog.exec()

    # ---------------------------------------------------------
    # MENUS
    # ---------------------------------------------------------

    def createMenus(self):

        fileMenu = self.menuBar().addMenu("File")

        self.menuBar().addMenu("Edit")

        self.menuBar().addMenu("Window")

        self.menuBar().addMenu("Help")

        newAction = QAction("New", self)

        openAction = QAction("Open", self)

        importAction = QAction("Import", self)

        saveAsAction = QAction("SaveAs", self)
        saveAction = QAction("Save", self)
        saveAction.setShortcut("Ctrl+S")

        saveAsAction.setShortcut("Ctrl+Shift+S")

        exitAction = QAction("Exit", self)
        
        newAction.triggered.connect(self.newProject)

        openAction.triggered.connect(self.openFile)

        importAction.triggered.connect(self.importFile)

        exitAction.triggered.connect(self.close)

        saveAction.triggered.connect(self.saveFile)

        saveAsAction.triggered.connect(self.saveAsFile)

        fileMenu.addAction(newAction)

        fileMenu.addAction(openAction)

        fileMenu.addAction(importAction)

        fileMenu.addAction(saveAsAction)
        fileMenu.addAction(saveAction)

        fileMenu.addSeparator()

        fileMenu.addAction(exitAction)

    # ---------------------------------------------------------
    # LEFT TOOLBAR
    # ---------------------------------------------------------

    def createToolbar(self):

        toolbar = QToolBar("Tools", self)

        toolbar.setMovable(False)

        self.addToolBar(Qt.LeftToolBarArea, toolbar)

        self.toolActions = []

        tools = [
            ("Select", "➤"),
            ("Reposition", "⇄"),
            ("Set Rotation", "⤾"),
            ("Pan", "✋"),
            ("Rotate", "⟳"),
            ("Move", "✥"),
        ]

        for index, (name, symbol) in enumerate(tools):
            action = QAction(symbol, self)

            action.setToolTip(name)

            action.setCheckable(True)

            action.triggered.connect(lambda checked, n=name: self.toolSelected(n))

            toolbar.addAction(action)

            self.toolActions.append(action)

            if index == 0:
                action.setChecked(True)

    def toolSelected(self, name):

        sender = self.sender()

        for action in self.toolActions:
            action.setChecked(action is sender)

        print("Selected tool:", name)

        if name == "Reposition":
            self.openRepositionObjectList()

        if name == "Set Rotation":
            self.openSetRotationObjectList()


class App:
    def __init__(self, projectPath=None, scene=None):

        self.projectPath = projectPath

        self.scene = scene

        self.window = None

        if self.scene is None:
            self.scene = Scene()

    def run(self):

        # Must be configured before QApplication is created.
        surfaceFormat = QSurfaceFormat()

        surfaceFormat.setVersion(3, 3)

        surfaceFormat.setProfile(QSurfaceFormat.CoreProfile)

        surfaceFormat.setDepthBufferSize(24)

        QSurfaceFormat.setDefaultFormat(surfaceFormat)

        app = QApplication.instance()

        ownsApp = app is None

        if app is None:
            app = QApplication(sys.argv)



        self.window = SimuOMainWindow(projectPath=self.projectPath, scene=self.scene)

        self.window.show()

        if ownsApp:
            return app.exec()

        return 0
