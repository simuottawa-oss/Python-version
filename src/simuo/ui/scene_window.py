"""Main application window and editor logic for SimuO.

This module assembles the Qt interface, manages project loading/saving, and
provides scene-editing dialogs for object positioning and rotation.
"""
import sys
from pathlib import Path
import json
from PySide6.QtCore import Qt
from PySide6.QtGui import QAction, QKeySequence
from PySide6.QtWidgets import (
    QApplication,
    QMainWindow,
    QLineEdit,
    QAbstractSpinBox,
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
    QDockWidget,
    QWidget,
)

from simuo.project.scene import Scene, SceneObject
from simuo.project.project_format import read_project, project_data, PROJECT_FILTER
from simuo.materials import material_from_dict
from simuo.editor.state import EditorState
from simuo.project.editor_metadata import read_groups, read_object_editor, write_group
from simuo.rendering.context import configure_opengl
from simuo.rendering.viewport import OpenGLViewport
from simuo.ui.docking import PanelManager
from simuo.ui.recent_projects import remember_project, record_saved_project
from simuo.ui.panel_registry import editor_panel_specs
from simuo.ui.theme import load_stylesheet
from simuo.ui.viewport_tools import create_viewport_tools
from simuo.project.project_paths import resolve_mesh_path, stored_mesh_path
from simuo.project.temporary_parts import TemporaryParts, atomic_write
from simuo.ui.properties_dialog import PropertiesDialog


class SimuOMainWindow(QMainWindow):
    """Primary editor window for the SimuO scene editor."""

    def __init__(self, projectPath=None, scene=None):
        """Build the scene editor, viewport, menus, temporary-part panel, and child-window
        registries; optionally load a project before GL initialization.

        Args:
            projectPath (str or Path, optional): Scene file to open; None starts without
                a project path.
            scene (Scene, optional): Scene to display/use; None uses the constructor's
                empty or unbound default.

        Returns:
            None.
        """
        super().__init__()

        self.projectPath = projectPath

        if scene is None:
            scene = Scene()

        self.scene = scene
        self.editor_state = EditorState(scene, self)
        self.renderWindows = []
        self.partWindows = []
        self.temporaryParts = TemporaryParts()

        self.setWindowTitle("SimuO - Untitled")

        self.resize(1280, 800)

        self.setStyleSheet(load_stylesheet("main_window"))
        self.createMenus()

        self.viewport = OpenGLViewport(self, scene=self.scene)
        self.viewport.setMinimumSize(320, 280)

        self.setCentralWidget(self.viewport)
        self.createToolbar()
        self.createTemporaryPartsPanel()
        self.viewport.object_picked.connect(self.onViewportPicked)
        self.viewport.box_selection_requested.connect(self.editor_state.select_many)
        self.viewport.transform_started.connect(self.editor_state.begin_transform)
        self.viewport.transform_previewed.connect(self.editor_state.preview_transform)
        self.viewport.transform_finished.connect(self.editor_state.finish_transform)
        self.editor_state.transform_ended.connect(self.viewport.discard_transform)
        self.editor_state.tool_changed.connect(self.viewport.set_tool)
        self.editor_state.tool_options_changed.connect(self.viewport.set_tool_options)
        self.editor_state.selection_set_changed.connect(self.viewport.set_selected_objects)
        self.viewport.frame_requested.connect(self.editor_state.frame_selected)
        self.viewport.frame_scene_requested.connect(self.editor_state.frame_scene)
        self.viewport.escape_requested.connect(self.onViewportEscape)
        self.editor_state.frame_requested.connect(self.viewport.frameObject)

        self.panel_manager = PanelManager(self, self.viewMenu)
        for spec in editor_panel_specs(self.editor_state):
            self.panel_manager.register_panel(spec)
        self.panel_manager.restore_layout()
        # Give floating docks the same editing shortcuts as the main window.
        for widget in (self, *self.panel_manager.docks.values()):
            for action in self.edit_actions:
                widget.addAction(action)
        self.editor_state.object_changed.connect(self.onObjectChanged)
        self.editor_state.objects_changed.connect(self.onObjectsChanged)
        self.editor_state.dirty_changed.connect(self.updateWindowTitle)
        self.editor_state.view_changed.connect(self.viewport.update)
        self.editor_state.view_changed.connect(self.updateEditActions)
        self.editor_state.selection_set_changed.connect(self.updateEditActions)
        QApplication.instance().focusChanged.connect(self.updateEditActions)
        self.updateEditActions()
        self.updateWindowTitle()

        self.statusBar().showMessage(
            "Import Part to add a model · Right-drag to look · WASD to move · Help → Controls"
        )
        
        if projectPath is not None:
            if not self.tryLoadFile(projectPath, uploadToGPU=False):
                self.projectPath = None


    # ---------------------------------------------------------
    # FILE OPERATIONS
    # ---------------------------------------------------------

    def updateWindowTitle(self):
        name = Path(self.projectPath).stem if self.projectPath is not None else "Untitled"
        self.setWindowTitle(f"SimuO - {name}[*]")
        self.setWindowModified(self.scene.dirty)
        self.editor_state.set_scene_name("Untitled Scene" if self.projectPath is None else name)

    def onObjectChanged(self, obj):
        self.updateWindowTitle()
        self.viewport.update()

    def onObjectsChanged(self):
        self.viewport.sync_scene_objects()
        self.refreshTemporaryParts()
        self.updateWindowTitle()

    def onViewportPicked(self, identifier):
        self.editor_state.select_from_viewport(identifier, self.viewport.pick_modifiers)

    def onViewportEscape(self):
        if self.editor_state.isolated_ids is not None:
            self.editor_state.exit_isolation()
        else:
            self.close()

    def updateEditActions(self, *args):
        focus = QApplication.focusWidget()
        typing = isinstance(focus, (QLineEdit, QAbstractSpinBox))
        selected = bool(self.editor_state.selected_objects)
        self.duplicateAction.setEnabled(selected and not typing)
        self.deleteAction.setEnabled(selected and not typing)
        self.selectAllAction.setEnabled(bool(self.scene.objects) and not typing)
        self.groupAction.setEnabled(selected and not typing)
        self.showSelectedAction.setEnabled(selected)
        self.frameSelectedAction.setEnabled(any(obj.viewport_visible for obj in self.editor_state.selected_objects))
        self.frameSceneAction.setEnabled(any(obj.viewport_visible and obj.meshPath is not None for obj in self.scene.objects))
        self.isolateAction.setEnabled(selected or self.editor_state.isolated_ids is not None)
        self.isolateAction.setChecked(self.editor_state.isolated_ids is not None)

    def showSelectedInHierarchy(self):
        dock = self.panel_manager.docks["object_hierarchy"]
        dock.show()
        dock.raise_()
        dock.widget().show_selected()

    def createGroupFromSelection(self):
        dock = self.panel_manager.docks["object_hierarchy"]
        dock.show()
        dock.raise_()
        dock.widget().create_group()

    def selectAllObjects(self):
        focus = QApplication.focusWidget()
        hierarchy = self.panel_manager.docks["object_hierarchy"].widget()
        if focus is hierarchy or (focus is not None and hierarchy.isAncestorOf(focus)):
            self.editor_state.select_many(hierarchy.matching_ids())
        elif focus is self.viewport:
            self.editor_state.select_many(obj.identifier for obj in self.scene.objects
                                          if obj.viewport_visible and not obj.viewport_locked)
        else:
            self.editor_state.select_many(obj.identifier for obj in self.scene.objects)

    def historyStep(self, operation):
        self.viewport.cancel_interaction()
        self.editor_state.cancel_transform()
        operation()

    def createTemporaryPartsPanel(self):
        """Create a hidden dock showing unsaved part copies and their temporary directory.

        Returns:
            None. Adds its visibility action to the Window menu.
        """
        self.temporaryPartsDock = QDockWidget("Temporary parts", self)
        self.temporaryPartsDock.setObjectName("temporaryPartsDock")
        panel = QWidget(self)
        layout = QVBoxLayout(panel)
        self.temporaryPartsDirectory = QLabel(panel)
        self.temporaryPartsDirectory.setWordWrap(True)
        self.temporaryPartsDirectory.setTextInteractionFlags(Qt.TextSelectableByMouse)
        layout.addWidget(self.temporaryPartsDirectory)
        self.temporaryPartsList = QListWidget(panel)
        layout.addWidget(self.temporaryPartsList)
        self.temporaryPartsDock.setWidget(panel)
        self.addDockWidget(Qt.RightDockWidgetArea, self.temporaryPartsDock)
        self.windowMenu.addAction(self.temporaryPartsDock.toggleViewAction())
        self.temporaryPartsDock.hide()

    def active_temporary_parts(self):
        paths = {Path(obj.meshPath).resolve() for obj in self.scene.objects if obj.meshPath}
        return [path for path in self.temporaryParts.sources if path in paths]

    def refreshTemporaryParts(self):
        """Repopulate temporary-part names and paths, showing the dock only when copies
        exist.

        Returns:
            None. Updates panel contents and visibility.
        """
        self.temporaryPartsList.clear()
        active_paths = self.active_temporary_parts()
        for path in active_paths:
            self.temporaryPartsList.addItem(path.name)
            self.temporaryPartsList.item(self.temporaryPartsList.count()-1).setToolTip(str(path))
        self.temporaryPartsDirectory.setText(
            f"Unsaved parts are stored in:\n{self.temporaryParts.directory}\n\n"
            "Save the scene to choose permanent locations for these parts."
        )
        self.temporaryPartsDock.setVisible(bool(active_paths))

    def newPart(self):
        """Open an independent feature-based part editor and retain its window reference.

        Returns:
            None. Leaves the scene open.
        """
        from simuo.ui.parts.feature_editor import FeaturePartEditor

        window = FeaturePartEditor()
        self.partWindows.append(window)
        window.show()

    def newProject(self):
        """Protect unsaved changes, then clear scene objects, uploaded buffers, temporary
        copies, and project identity.

        Returns:
            None. Resets the editor to a clean untitled scene after confirmation.
        """
        if not self.confirmUnsavedChanges("New Project"):
            return

        self.viewport.clearRenderObjects()
        self.editor_state.replace_objects([])
        self.temporaryParts.cleanup()
        self.refreshTemporaryParts()

        self.projectPath = None
        self.scene.dirty = False

        self.updateWindowTitle()

        self.viewport.update()
        
        
    def loadFile(
        self,
        path,
        uploadToGPU=True
    ):
        """Load referenced assets and instance overrides before replacing scene objects;
        optionally rebuild GPU uploads. Parsing/asset errors propagate to the caller.

        Args:
            path (str or Path): Source or destination file path used by this operation.
            uploadToGPU (bool): Upload loaded objects immediately; False defers uploads
                until GL initialization.

        Returns:
            None. Updates project path, title, clean state, and camera framing for a
            single JSON part.
        """
        document = read_project(path)
        if document.project_type != "scene":
            raise ValueError("This project belongs to Structural Analysis")
        data = document.data

        loadedObjects = []

        for objectData in data.get(
            "objects",
            []
        ):
            sceneObject = SceneObject(
                name=objectData["name"],
                meshPath=resolve_mesh_path(objectData["meshPath"], path) if objectData.get("meshPath") else None,
                identifier=objectData.get("id"),
            )

            position = objectData.get(
                "position",
                sceneObject.position
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

            sceneObject.setPhysicsProperties(
                objectData.get("restitution", sceneObject.restitution),
                objectData.get("velocity", sceneObject.velocity),
                objectData.get("body_type", sceneObject.body_type),
                objectData.get("acceleration", sceneObject.acceleration),
            )
            sceneObject.angularVelocity = list(objectData.get("angularVelocity", sceneObject.angularVelocity))
            sceneObject.material_override = material_from_dict(objectData.get("material"))

            read_object_editor(sceneObject, objectData)
            loadedObjects.append(sceneObject)

        # Resolve all model files before replacing the current scene.
        if uploadToGPU:
            self.viewport.clearRenderObjects()
        self.editor_state.replace_objects(loadedObjects, *read_groups(data))

        if len(loadedObjects) == 1 and loadedObjects[0].part is not None:
            self.viewport.frameObject(loadedObjects[0])

        self.projectPath = Path(
            path
        )
        self.scene.dirty = False

        self.updateWindowTitle()

        if uploadToGPU:
            self.viewport.update()

        remember_project(path)

        print(
            "Opened project:",
            path
        )
    def tryLoadFile(self, path, uploadToGPU=True):
        """Attempt project loading, converting supported parse, schema, and filesystem
        errors into a warning dialog.

        Args:
            path (str or Path): Source or destination file path used by this operation.
            uploadToGPU (bool): Upload loaded objects immediately; False defers uploads
                until GL initialization.

        Returns:
            bool: True if loaded; False after displaying a load error.
        """
        try:
            self.loadFile(path, uploadToGPU)
        except (OSError, ValueError, KeyError, TypeError, IndexError, AttributeError) as error:
            QMessageBox.warning(self, "Cannot Open Project", str(error))
            return False
        return True

    def openFile(self):
        """Prompt for a project, protect unsaved work, and load it; clear old temporary
        copies only after success.

        Returns:
            None. Cancellation leaves the current scene open.
        """
        filePath, _ = QFileDialog.getOpenFileName(
            self,
            "Open SimuO Project",
            "",
            PROJECT_FILTER,
        )

        if not filePath:
            return

        path = Path(filePath)
        try:
            if read_project(path).project_type == "structural":
                from simuo.ui.project_open import open_project_window
                open_project_window(path, self)
                return
        except (OSError, ValueError, TypeError) as error:
            QMessageBox.warning(self, "Cannot Open Project", str(error))
            return

        if not self.confirmUnsavedChanges("Open Project"):
            return
        if self.tryLoadFile(path, True):
            self.temporaryParts.cleanup()
            self.refreshTemporaryParts()

    def importFile(self):
        """Prompt for a part/OBJ, validate and upload it, then add it to the scene. OBJ
        imports become temporary copies after confirmation.

        Returns:
            None. Marks successful imports dirty; errors release temporary copies and
            display a warning.
        """
        filePath, _ = QFileDialog.getOpenFileName(
            self,
            "Import Part",
            "",
            "3D Model Files (*.simuOPart *.obj *.OBJ);;SimuO Parts (*.simuOPart);;OBJ Models (*.obj *.OBJ);;All Files (*)",
        )

        if not filePath:
            return

        print("Importing model:", filePath)

        path = Path(filePath)

        temporaryPath = None
        try:
            if path.suffix.lower() == ".obj":
                answer = QMessageBox.question(
                    self, "Create SimuO Part",
                    f"Create a new SimuO part from {path.name}?\n\n"
                    "The part will be temporary until you save the scene. "
                    "Your original OBJ file will be kept.",
                    QMessageBox.Yes | QMessageBox.Cancel,
                    QMessageBox.Yes,
                )
                if answer != QMessageBox.Yes:
                    return
                temporaryPath = self.temporaryParts.create(path)
                path = temporaryPath
            importedObject = SceneObject(meshPath=path)
            if temporaryPath is not None and importedObject.part is not None:
                raise ValueError("Expected OBJ geometry in the selected .obj file")
            self.viewport.addNewObject(importedObject)
        except (OSError, ValueError, TypeError, OverflowError) as error:
            if temporaryPath is not None:
                self.temporaryParts.release(temporaryPath)
            QMessageBox.warning(self, "Cannot Import Part", str(error))
            return

        self.editor_state.add_object(importedObject)
        self.refreshTemporaryParts()
        if importedObject.part is not None or temporaryPath is not None:
            self.viewport.frameObject(importedObject)

    def saveFile(self, checked=False, destination=None):
        """Collect permanent temporary-part destinations and atomically write each part and
        scene reference file. Updates in-memory paths/clean state only after success;
        writes are not a multi-file transaction.

        Args:
            checked (bool): QAction signal argument, accepted for compatibility and
                otherwise ignored.
            destination (str or Path, optional): Explicit scene save path; None uses the
                current path or prompts.

        Returns:
            bool: True when saved; False on destination cancellation or reported
            filesystem failure.
        """
        self.viewport.cancel_interaction()
        path = Path(destination) if destination is not None else self.projectPath
        if path is None:
            filePath, _ = QFileDialog.getSaveFileName(
                self, "Save SimuO Project", "", "SimuO Project Files (*.simuO)"
            )

            if not filePath:
                return False

            path = Path(filePath)

        path = Path(path).resolve()
        if path.suffix.lower() != ".simuo":
            path = path.with_suffix(".simuO")
        directory = self.temporaryParts.directory
        if directory is not None and path.is_relative_to(directory):
            QMessageBox.warning(self, "Cannot Save Scene", "Choose a permanent folder outside the temporary parts directory.")
            return False

        # Ask for every destination before writing anything. A cancelled part
        # dialog must never produce a scene referring to temporary files.
        partPaths = {}
        for sceneObject in self.scene.objects:
            source = Path(sceneObject.meshPath).resolve() if sceneObject.meshPath else None
            if not self.temporaryParts.contains(source) or source in partPaths:
                continue
            filename, _ = QFileDialog.getSaveFileName(
                self, f"Save SimuO Part — {source.stem}",
                str(path.parent / source.name), "SimuO Part Files (*.simuOPart)",
            )
            if not filename:
                return False
            target = Path(filename).resolve()
            if target.suffix.lower() != ".simuopart":
                target = target.with_suffix(".simuOPart")
                if target.exists() and QMessageBox.question(
                    self, "Replace Part", f"Replace the existing part {target.name}?",
                    QMessageBox.Yes | QMessageBox.Cancel, QMessageBox.Cancel,
                ) != QMessageBox.Yes:
                    return False
            directory = self.temporaryParts.directory
            if (directory is not None and target.is_relative_to(directory)) or target == path or target in partPaths.values():
                QMessageBox.warning(self, "Cannot Save Part", "Choose a separate permanent file for each part.")
                return False
            partPaths[source] = target

        self.scene.normalize_hierarchy()
        data = project_data("scene", objects=[],
                            groups=[write_group(group) for group in self.scene.groups],
                            hierarchy_order=self.scene.root_order)


        for sceneObject in self.scene.objects:
            # Skip editor-only objects like the axis
            if sceneObject.name == "Axis" and sceneObject.asset is None:
                continue

            objectData = {
                "id": sceneObject.identifier,
                "name": sceneObject.name,
                "editor": {"visible": sceneObject.editor_visible, "selection_locked": sceneObject.selection_locked},
                "meshPath": stored_mesh_path(
                    partPaths.get(Path(sceneObject.meshPath).resolve(), sceneObject.meshPath), path
                ) if sceneObject.meshPath is not None else None,
                "position": list(sceneObject.position),
                "rotation": list(sceneObject.rotation),
                "scale": list(sceneObject.scale),
                "velocity": list(sceneObject.velocity),
                "restitution": sceneObject.restitution,
                "body_type": sceneObject.body_type,
                "material": sceneObject.material_override.to_dict() if sceneObject.material_override else None,
                "acceleration": list(sceneObject.acceleration),
                "angularVelocity": list(sceneObject.angularVelocity),
            }

            data["objects"].append(objectData)

        try:
            for source, target in partPaths.items():
                atomic_write(target, source.read_bytes())
            atomic_write(path, json.dumps(data, indent=4).encode("utf-8"))
        except OSError as error:
            QMessageBox.warning(
                self, "Cannot Save Scene",
                f"Could not save the scene to:\n{path}\n\n{error}\n\n"
                "Your scene is still open. Choose a writable folder and try again.",
            )
            return False

        for sceneObject in self.editor_state.history_objects():
            source = Path(sceneObject.meshPath).resolve() if sceneObject.meshPath else None
            if source in partPaths:
                sceneObject.meshPath = partPaths[source]
        for source in partPaths:
            self.temporaryParts.release(source)
        self.projectPath = path
        self.editor_state.mark_saved()
        self.refreshTemporaryParts()

        self.updateWindowTitle()

        print("Saved project:", self.projectPath)
        record_saved_project(self.projectPath, self.viewport)
        return True

    def saveAsFile(self):
        """Prompt for a new scene path and delegate scene/temporary-part persistence to
        saveFile.

        Returns:
            bool: True when saved; False on cancellation or failure.
        """
        filePath, _ = QFileDialog.getSaveFileName(
            self, "Save Scene as", "", "SimuO Project Files (*.simuO)"
        )

        if not filePath:
            return False

        path = Path(filePath)

        if path.suffix.lower() != ".simuo":
            path = path.with_suffix(".simuO")

        return self.saveFile(destination=path)

    def confirmUnsavedChanges(self, title):
        """Offer Save/Discard/Cancel when dirty objects, an unsaved scene, or temporary
        parts need protection.

        Args:
            title (str): Window or confirmation-dialog title.

        Returns:
            bool: True if clean, discarded, or successfully saved; False on cancellation
            or failed save.
        """
        self.viewport.cancel_interaction()
        hasUnsavedObjects = self.projectPath is None and self.scene.sceneHasObjects()
        if not (self.scene.dirty or hasUnsavedObjects or self.active_temporary_parts()):
            return True
        message = "Save changes to the current scene before continuing?"
        if self.active_temporary_parts():
            message += "\n\nYou will also choose permanent locations for its temporary parts."
        answer = QMessageBox.question(
            self, title, message,
            QMessageBox.Save | QMessageBox.Discard | QMessageBox.Cancel,
            QMessageBox.Save,
        )
        if answer == QMessageBox.Save:
            return self.saveFile()
        return answer == QMessageBox.Discard

    def confirmTemporaryParts(self, title):
        """Preserve the older temporary-part confirmation entry point by delegating to the
        full scene unsaved-change check.

        Args:
            title (str): Window or confirmation-dialog title.

        Returns:
            bool: Whether the requested operation may continue.
        """
        return self.confirmUnsavedChanges(title)

    def closeEvent(self, event):
        """Protect unsaved changes, close playback windows, release temporary copies, and
        accept closure; otherwise ignore it.

        Args:
            event (Qt event): Input, paint, resize, focus, or close event delivered by
                the framework.

        Returns:
            None. Controls window closure through the event.
        """
        if not self.confirmUnsavedChanges("Close Scene"):
            event.ignore()
            return
        for window in list(self.renderWindows):
            window.close()
        self.temporaryParts.cleanup()
        self.panel_manager.save_layout()
        event.accept()

    # ---------------------------------------------------------
    # SET ROTATION TOOL
    # ---------------------------------------------------------
    def openSetRotationObjectList(self):
        """Show a scene-object picker and open the rotation dialog for the selected row.

        Returns:
            None. Uses a nested selection callback.
        """
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
            """Read the enclosing picker's selected row and open that object's rotation
            controls.

            Returns:
                None. Accepts the picker only when a row is selected.
            """
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
        """Show XYZ Euler angle controls and apply accepted values to one scene instance.

        Args:
            sceneObject (SceneObject): Instance to display, remove, or edit.

        Returns:
            None. Accepted edits mark the scene dirty and repaint the viewport.
        """
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
            """Apply the enclosing dialog's XYZ angle values and finish the dialog.

            Returns:
                None. Mutates the selected object, marks dirty, and repaints.
            """
            x = xInput.value()
            y = yInput.value()
            z = zInput.value()

            self.editor_state._edit("Change Rotation", [(sceneObject, "rotation", [x, y, z])])

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
        """Show an object picker and open position controls for the selected row.

        Returns:
            None. Leaves state unchanged until a position edit is accepted.
        """
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
            """Read the enclosing picker's selected row and open that object's position
            controls.

            Returns:
                None. Accepts the picker only when a row is selected.
            """
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
        """Show XYZ position controls for one scene instance and apply accepted
        coordinates.

        Args:
            sceneObject (SceneObject): Instance to display, remove, or edit.

        Returns:
            None. Accepted edits mark the scene dirty and repaint.
        """
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
            """Apply the enclosing dialog's XYZ coordinates and finish the dialog.

            Returns:
                None. Mutates the selected instance, marks dirty, and repaints.
            """
            x = xInput.value()
            y = yInput.value()
            z = zInput.value()

            self.editor_state._edit("Change Position", [(sceneObject, "position", [x, y, z])])

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

        """Create scene file/window/help menus and physics playback action with shortcuts
        and callbacks.

        Returns:
            None. Stores menu/action references used elsewhere by the window.
        """
        fileMenu = self.menuBar().addMenu("File")

        self.editMenu = self.menuBar().addMenu("Edit")
        stack = self.editor_state.undo_stack
        self.undoAction = stack.createUndoAction(self, "Undo")
        self.redoAction = stack.createRedoAction(self, "Redo")
        for action, operation in ((self.undoAction, stack.undo), (self.redoAction, stack.redo)):
            action.triggered.disconnect()
            action.triggered.connect(lambda checked=False, operation=operation: self.historyStep(operation))
        self.undoAction.setShortcuts(QKeySequence.keyBindings(QKeySequence.StandardKey.Undo))
        self.redoAction.setShortcuts(QKeySequence.keyBindings(QKeySequence.StandardKey.Redo))
        self.duplicateAction = QAction("Duplicate", self)
        self.duplicateAction.setShortcut(QKeySequence("Ctrl+D"))
        self.duplicateAction.triggered.connect(self.editor_state.duplicate_selected)
        self.deleteAction = QAction("Delete", self)
        self.deleteAction.setShortcuts([QKeySequence("Delete"), QKeySequence("Backspace")])
        self.deleteAction.triggered.connect(self.editor_state.delete_selected)
        self.selectAllAction = QAction("Select All", self)
        self.selectAllAction.setShortcuts(QKeySequence.keyBindings(QKeySequence.StandardKey.SelectAll))
        self.selectAllAction.triggered.connect(self.selectAllObjects)
        self.groupAction = QAction("Group Selection", self)
        self.groupAction.setShortcut(QKeySequence("Ctrl+G"))
        self.groupAction.triggered.connect(self.createGroupFromSelection)
        self.edit_actions = (self.undoAction, self.redoAction, self.duplicateAction,
                             self.deleteAction, self.selectAllAction, self.groupAction)
        for action in self.edit_actions:
            action.setShortcutContext(Qt.ShortcutContext.WidgetWithChildrenShortcut)
        self.editMenu.addActions([self.undoAction, self.redoAction])
        self.editMenu.addSeparator()
        self.editMenu.addActions([self.duplicateAction, self.deleteAction, self.selectAllAction, self.groupAction])

        self.viewMenu = self.menuBar().addMenu("View")
        self.toolsVisibleAction = self.viewMenu.addAction("Viewport Tools")
        self.toolsVisibleAction.setCheckable(True)
        self.toolsVisibleAction.setChecked(True)
        self.frameSelectedAction = self.viewMenu.addAction("Frame Selected", self.editor_state.frame_selected)
        self.frameSceneAction = self.viewMenu.addAction("Frame Scene", self.editor_state.frame_scene)
        self.showSelectedAction = self.viewMenu.addAction("Show Selected in Hierarchy", self.showSelectedInHierarchy)
        self.isolateAction = self.viewMenu.addAction("Isolate Selected")
        self.isolateAction.setCheckable(True)
        self.isolateAction.triggered.connect(lambda checked: self.editor_state.isolate_selected() if checked else self.editor_state.exit_isolation())
        self.viewMenu.addSeparator()

        self.renderAction = QAction("Render", self)
        self.renderAction.setShortcut("Ctrl+R")
        self.renderAction.setToolTip("Open a physics simulation of the current scene")
        self.renderAction.triggered.connect(self.openPhysicsRender)
        self.menuBar().addAction(self.renderAction)

        windowMenu = self.menuBar().addMenu("Window")
        # The dock is created after the viewport; connect its toggle below.
        self.windowMenu = windowMenu
        helpMenu = self.menuBar().addMenu("Help")
        controlsAction = QAction("Controls", self)
        controlsAction.triggered.connect(self.showControls)
        helpMenu.addAction(controlsAction)

        newMenu = fileMenu.addMenu("New")
        newAction = QAction("Scene", self)
        newAction.setShortcut("Ctrl+N")
        newPartAction = QAction("Part", self)
        newPartAction.triggered.connect(self.newPart)
        newMenu.addAction(newAction)
        newMenu.addAction(newPartAction)

        openAction = QAction("Open Project…", self)
        openAction.setShortcut("Ctrl+O")

        importAction = QAction("Import Part…", self)

        saveAsAction = QAction("Save As…", self)
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

        fileMenu.addAction(openAction)

        fileMenu.addAction(importAction)

        fileMenu.addAction(saveAsAction)
        fileMenu.addAction(saveAction)

        fileMenu.addSeparator()

        fileMenu.addAction(exitAction)

    # ---------------------------------------------------------
    # LEFT TOOLBAR
    # ---------------------------------------------------------

    def showControls(self):
        """Display scene, camera, property-editing, and shortcut guidance.

        Returns:
            None. Opens an informational dialog.
        """
        QMessageBox.information(
            self, "SimuO Controls",
            "Import Part adds a model. Save stores your scene and its model references.\n\n"
            "Camera: W/S forward/back, A/D left/right, Space/C up/down.\n"
            "Left/Right arrows turn the camera left/right.\n"
            "Hold the right mouse button and move the mouse to look around.\n"
            "Esc closes the editor after checking for unsaved changes.\n\n"
            "Select a part and use the viewport tools or Properties panel. Use Edit → Physics Properties for motion and bounce.\n"
            "File → New → Scene / Part creates a scene or part.\n"
            "Ctrl+N: New Scene · Ctrl+O: Open Project · Ctrl+S: Save · Ctrl+Shift+S: Save As",
        )

    def createToolbar(self):
        self.viewport_tools, self.toolActions = create_viewport_tools(
            self.viewport, self.editor_state, self.toolsVisibleAction,
        )
        self.editMenu.addSeparator()
        self.propertiesAction = self.editMenu.addAction("Physics Properties…", self.openPropertiesObjectList)
        self.deletePartAction = self.editMenu.addAction("Delete Part…", self.openDeletePartDialog)

    def openDeletePartDialog(self):
        """Prompt for a non-axis object to remove, then delegate accepted deletion.

        Returns:
            None. Displays guidance when the scene has no removable parts.
        """
        objects = [obj for obj in self.scene.objects if obj.name != "Axis" or obj.asset is not None]
        if not objects:
            QMessageBox.information(self, "Delete Part", "There are no parts to delete.")
            return
        picker = QDialog(self)
        picker.setWindowTitle("Delete Part")
        layout = QVBoxLayout(picker)
        layout.addWidget(QLabel("Choose the part to remove from this scene:"))
        objectList = QListWidget()
        objectList.addItems([obj.name for obj in objects])
        objectList.setCurrentRow(0)
        layout.addWidget(objectList)
        buttons = QDialogButtonBox(QDialogButtonBox.Cancel)
        deleteButton = buttons.addButton("Delete", QDialogButtonBox.AcceptRole)
        deleteButton.setAutoDefault(False)
        deleteButton.setDefault(False)
        objectList.currentRowChanged.connect(lambda row: deleteButton.setEnabled(row >= 0))
        buttons.accepted.connect(picker.accept)
        buttons.rejected.connect(picker.reject)
        layout.addWidget(buttons)
        if picker.exec() == QDialog.Accepted and objectList.currentRow() >= 0:
            self.deleteScenePart(objects[objectList.currentRow()])

    def deleteScenePart(self, sceneObject):
        """Remove a scene instance through the same history as hierarchy deletion.

        Args:
            sceneObject (SceneObject): Instance to display, remove, or edit.

        Returns:
            None. Marks dirty and refreshes temporary-part/status UI; unknown instances
            are ignored.
        """
        if sceneObject not in self.scene.objects or (sceneObject.name == "Axis" and sceneObject.asset is None):
            return
        self.editor_state.delete_objects((sceneObject.identifier,))
        self.statusBar().showMessage(f"Removed {sceneObject.name} from the scene", 5000)

    def openPropertiesObjectList(self):
        """Choose a non-axis instance for property editing, opening its dialog directly
        when only one exists.

        Returns:
            None. Displays guidance if no editable objects exist.
        """
        objects = [obj for obj in self.scene.objects if obj.name != "Axis" or obj.asset is not None]
        if not objects:
            QMessageBox.information(self, "Properties", "Import a part before editing its properties.")
            return
        if len(objects) == 1:
            self.openPropertiesDialog(objects[0])
            return
        picker = QDialog(self)
        picker.setWindowTitle("Choose Part — Properties")
        layout = QVBoxLayout(picker)
        layout.addWidget(QLabel("Choose the part whose properties you want to edit:"))
        objectList = QListWidget()
        objectList.addItems([obj.name for obj in objects])
        objectList.setCurrentRow(0)
        layout.addWidget(objectList)
        buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        buttons.accepted.connect(picker.accept)
        buttons.rejected.connect(picker.reject)
        objectList.itemDoubleClicked.connect(lambda item: picker.accept())
        layout.addWidget(buttons)
        if picker.exec() == QDialog.Accepted and objectList.currentRow() >= 0:
            self.openPropertiesDialog(objects[objectList.currentRow()])

    def openPropertiesDialog(self, sceneObject):
        """Read accepted body-type, bounce, and velocity edits and apply them only if
        effective values changed.

        Args:
            sceneObject (SceneObject): Instance to display, remove, or edit.

        Returns:
            None. Marks the scene dirty and repaints; cancellation leaves the instance
            unchanged.
        """
        dialog = PropertiesDialog(sceneObject, self)
        if dialog.exec() != QDialog.Accepted:
            return
        self.editor_state.set_physics_properties(sceneObject.identifier, **dialog.values())

    def openPhysicsRender(self):
        """Open and retain an independent live simulation window for the current scene.

        Returns:
            None. Displays guidance or dependency/validation errors when playback cannot
            start.
        """
        if not self.scene.objects:
            QMessageBox.information(self, "Render Physics", "Import a part before rendering physics.")
            return
        try:
            from simuo.ui.physics_render import PhysicsRenderWindow
            window = PhysicsRenderWindow(self.scene,self)
        except ImportError as error:
            QMessageBox.warning(self, "Cannot Render Physics",
                                f"A physics dependency is missing: {error}\nInstall the project requirements and try again.")
            return
        except (ValueError, RuntimeError, OverflowError) as error:
            QMessageBox.warning(self, "Cannot Render Physics", str(error))
            return
        self.renderWindows.append(window)
        window.destroyed.connect(lambda: self.renderWindows.remove(window) if window in self.renderWindows else None)
        window.show()


class App:
    """Top-level application launcher for SimuO."""

    def __init__(self, projectPath=None, scene=None):

        """Store an optional project path and scene, creating an empty scene when omitted.

        Args:
            projectPath (str or Path, optional): Scene file to open; None starts without
                a project path.
            scene (Scene, optional): Scene to display/use; None uses the constructor's
                empty or unbound default.

        Returns:
            None. Defers Qt window creation to run.
        """
        self.projectPath = projectPath

        self.scene = scene

        self.window = None

        if self.scene is None:
            self.scene = Scene()

    def run(self, start_event_loop=None):

        # Must be configured before QApplication is created.
        """Configure OpenGL, create/show the editor, and optionally run Qt's event loop.

        Args:
            start_event_loop (bool, optional): Enter ``QApplication.exec`` when true.
                By default this happens only when this method creates the application,
                which keeps the class usable from an existing Qt event loop.

        Returns:
            int: Qt exit code, or 0 when a caller-owned event loop remains responsible.
        """
        configure_opengl()

        app = QApplication.instance()

        owns_app = app is None

        if app is None:
            app = QApplication(sys.argv)

        if start_event_loop is None:
            start_event_loop = owns_app



        self.window = SimuOMainWindow(projectPath=self.projectPath, scene=self.scene)

        self.window.show()

        if start_event_loop:
            return app.exec()
        return 0
