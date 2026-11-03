"""Main application window and editor logic for SimuO.

This module assembles the Qt interface, manages project loading/saving, and
connects the scene to the hierarchy and property editor.
"""

from pathlib import Path
from PySide6.QtCore import Qt
from PySide6.QtGui import QAction, QKeySequence
from PySide6.QtWidgets import (
    QApplication,
    QMainWindow,
    QFileDialog,
    QMessageBox,
    QLineEdit,
    QAbstractSpinBox,
)

from simuo.scene.model import Scene, SceneObject
from simuo.scene.persistence import load_project, save_project
from simuo.rendering.viewport import OpenGLViewport
from simuo.ui.docking import PanelManager
from simuo.editor.state import EditorState
from simuo.ui.panel_registry import editor_panel_specs
from simuo.ui.theme import load_stylesheet
from simuo.ui.viewport_tools import create_viewport_tools


class SimuOMainWindow(QMainWindow):
    """Primary editor window for the SimuO scene editor."""

    def __init__(self, projectPath=None, scene=None):
        """Create the main application window and initialize the scene editor.

        Args:
            projectPath: Optional path to a saved .simuO project.
            scene: Optional pre-existing scene object.
        """
        super().__init__()

        self.projectPath = projectPath

        if scene is None:
            scene = Scene()

        self.scene = scene
        self.editor_state = EditorState(self.scene, self)

        self.setWindowTitle("SimuO - Untitled")

        self.resize(1280, 800)

        self.setStyleSheet(load_stylesheet("main_window"))

        self.createMenus()

        self.viewport = OpenGLViewport(self, scene=self.scene)
        self.viewport.setMinimumSize(320, 280)

        self.setCentralWidget(self.viewport)
        self.createToolbar()
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
        self.editor_state.frame_requested.connect(self.viewport.frame_object)

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

        if projectPath is not None:
            self.loadFile(projectPath,uploadToGPU=False)

    def closeEvent(self, event):
        """Remember the workspace when the editor closes normally."""
        self.viewport.cancel_interaction()
        if not self.confirmDiscardChanges():
            event.ignore()
            return
        super().closeEvent(event)
        if event.isAccepted():
            self.panel_manager.save_layout()

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

    def confirmDiscardChanges(self):
        """Return whether the current scene may safely be replaced or closed."""
        self.viewport.cancel_interaction()
        self.editor_state.cancel_transform()
        if not self.scene.dirty:
            return True
        response = QMessageBox.question(
            self, "Unsaved Changes", "Save changes to the current scene?",
            QMessageBox.Save | QMessageBox.Discard | QMessageBox.Cancel,
            QMessageBox.Save,
        )
        if response == QMessageBox.Save:
            return self.saveFile()
        return response == QMessageBox.Discard


    # ---------------------------------------------------------
    # FILE OPERATIONS
    # ---------------------------------------------------------

    def newProject(self):
        """Create a new empty project after prompting to save the current one.

        Returns:
            None: The method updates the current scene and viewport state.
        """

        if not self.confirmDiscardChanges():
            return

        self.viewport.clearRenderObjects()
        self.editor_state.replace_objects([])

        self.projectPath = None

        self.updateWindowTitle()

        self.viewport.update()


    def loadFile(self, path, uploadToGPU=True):
        """Read a project, replace editor state, and upload its meshes when requested."""
        self.viewport.cancel_interaction()
        objects, groups, root_order = load_project(path)
        if uploadToGPU:
            self.viewport.clearRenderObjects()
            for obj in objects:
                self.viewport.addNewObject(obj)
        self.editor_state.replace_objects(objects, groups, root_order)
        self.projectPath = Path(path)
        self.updateWindowTitle()
        if uploadToGPU:
            self.viewport.update()
        print("Opened project:", path)
    def openFile(self):
        """Open a project via a file dialog and load it into the editor."""
        filePath, _ = QFileDialog.getOpenFileName(
            self,
            "Open SimuO Project",
            "",
            "SimuO Project Files (*.simuO);;All Files (*)",
        )

        if not filePath:
            return

        path = Path(filePath)

        if self.confirmDiscardChanges():
            self.loadFile(path, True)

    def importFile(self):
        """Import an external 3D model into the current scene."""
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

        self.viewport.addNewObject(importedObject)
        self.editor_state.add_object(importedObject)
        self.updateWindowTitle()

    def saveFile(self):
        """Save the current scene to the active project file.

        Returns:
            bool: Whether the scene was successfully saved.
        """
        if self.projectPath is None:
            return self.saveAsFile()
        return self.writeProject(Path(self.projectPath))

    def writeProject(self, path):
        """Save the project, retaining the old path and dirty flag on failure."""
        self.viewport.cancel_interaction()
        self.editor_state.cancel_transform()
        focus = QApplication.focusWidget()
        if isinstance(focus, (QLineEdit, QAbstractSpinBox)) and self.isAncestorOf(focus):
            focus.clearFocus()
        try:
            save_project(self.scene, path)
        except (OSError, TypeError, ValueError) as error:
            QMessageBox.critical(self, "Could Not Save", str(error))
            return False
        self.projectPath = path
        self.editor_state.mark_saved()
        self.updateWindowTitle()
        print("Saved project:", self.projectPath)
        return True

    def saveAsFile(self):
        """Save the current project under a new file path."""
        filePath, _ = QFileDialog.getSaveFileName(
            self, "Save Scene as", "", "SimuO Project Files (*.simuO)"
        )

        if not filePath:
            return False

        path = Path(filePath)

        if path.suffix.lower() != ".simuo":
            path = path.with_suffix(".simuO")

        return self.writeProject(path)

    # ---------------------------------------------------------
    # MENUS
    # ---------------------------------------------------------

    def createMenus(self):
        """Construct the main application menu bar and menu actions."""

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
        """Keep active tools and options inside the viewport."""
        self.viewport_tools, self.toolActions = create_viewport_tools(
            self.viewport, self.editor_state, self.toolsVisibleAction,
        )

    def historyStep(self, operation):
        self.viewport.cancel_interaction()
        self.editor_state.cancel_transform()
        operation()

    def focusProperties(self, attribute):
        """Bring an existing inspector into view instead of opening a dialog."""
        dock = self.panel_manager.docks["properties"]
        dock.show()
        dock.raise_()
        if self.editor_state.selected_object is not None:
            dock.widget().focus_transform(attribute)
        else:
            hierarchy = self.panel_manager.docks["object_hierarchy"]
            hierarchy.show()
            hierarchy.raise_()
            hierarchy.widget().setFocus()
