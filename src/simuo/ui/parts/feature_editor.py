"""Feature tree, 3D viewing, plane/face sketching and additive extrusions."""
import copy
from pathlib import Path

import numpy as np
from PySide6.QtCore import Qt
from PySide6.QtGui import QAction, QColor, QPen, QPolygonF
from PySide6.QtWidgets import (QDockWidget, QTreeWidget, QTreeWidgetItem, QStackedWidget,
    QDialog, QVBoxLayout, QFormLayout, QDoubleSpinBox, QCheckBox, QDialogButtonBox,
    QMessageBox, QFileDialog, QToolBar, QLabel)

from simuo.ui.parts.part_editor import PartEditor
from simuo.ui.parts.part_viewport import PartViewport
from simuo.parts.feature_document import new_feature_document,open_feature_document,save_feature_document
from simuo.parts.feature_geometry import FeatureModel,PLANES,support_frame,to_plane
from simuo.parts.part_export import export_vertices
from simuo.parts.sketch_geometry import Sketch


class FeaturePartEditor(PartEditor):
    def __init__(self,path=None):
        """Build the feature-tree editor with 3D and sketch views, optionally opening a
        part document.

        Args:
            path (str or Path): Source or destination file path used by this operation.

        Returns:
            None.
        """
        self.model = None
        self.active_id = None
        self.selected_support = {"type":"plane","name":"Front"}
        self.sketch_plane_label = "Front Plane (XY)"
        super().__init__()
        self.data,self.model = new_feature_document()
        self.stack = QStackedWidget()
        self.viewport = PartViewport(self)
        self.viewport.face_selected.connect(self.select_face)
        self.viewport.plane_selected.connect(self.select_plane)
        self.centralWidget().layout().removeWidget(self.canvas)
        self.canvas.setParent(None)
        self.stack.addWidget(self.viewport)
        self.stack.addWidget(self.canvas)
        self.centralWidget().layout().addWidget(self.stack)
        self.tree = QTreeWidget()
        self.tree.setHeaderLabel("Part hierarchy")
        self.tree.setMinimumWidth(140)
        self.tree.itemClicked.connect(self.tree_clicked)
        self.tree.itemDoubleClicked.connect(self.tree_double_clicked)
        self.hierarchyDock = QDockWidget("Feature tree",self)
        self.hierarchyDock.setWidget(self.tree)
        self.addDockWidget(Qt.LeftDockWidgetArea,self.hierarchyDock)
        self.resizeDocks([self.hierarchyDock],[180],Qt.Horizontal)
        toolbar = QToolBar("Features",self)
        self.addToolBar(Qt.TopToolBarArea,toolbar)
        menu = self.menuBar().addMenu("Features")
        self.feature_actions = {}
        for name,callback in [("3D View",self.view_model),("New Sketch",self.new_sketch),
                              ("Extrude…",self.extrude_dialog),("Finish Sketch",self.finish_sketch),
                              ("Edit Sketch",self.edit_sketch)]:
            action = QAction(name,self)
            action.setToolTip(name+" on the selected reference plane, sketch or face")
            action.triggered.connect(callback)
            menu.addAction(action)
            toolbar.addAction(action)
            self.feature_actions[name] = action
        menu.addSeparator()
        for name, callback in (("Delete Sketch…", self.delete_sketch), ("Delete Extrusion…", self.delete_extrusion)):
            action = QAction(name, self)
            action.triggered.connect(callback)
            menu.addAction(action)
            self.feature_actions[name] = action
        delete_feature = QAction("Delete selected sketch / extrusion…", self)
        delete_feature.setShortcuts(["Backspace", "Delete"])
        delete_feature.setShortcutContext(Qt.WidgetShortcut)
        delete_feature.setAutoRepeat(False)
        delete_feature.triggered.connect(self.delete_tree_item)
        self.tree.addAction(delete_feature)
        self.tree.setContextMenuPolicy(Qt.ActionsContextMenu)
        view_menu = next(action.menu() for action in self.menuBar().actions() if action.text()=="View")
        view_menu.addAction(self.hierarchyDock.toggleViewAction())
        for action in view_menu.actions():
            if action.shortcut().toString()=="F":
                action.setText("Frame view")
                action.triggered.disconnect()
                action.triggered.connect(self.frame_view)
        self.select_mode()
        for label in self.findChildren(QLabel):
            if label.text()=="Thickness:":
                label.setText("Next extrusion:")
        self.refresh()
        self.viewport.fit()
        if path:
            self.open_path(path)

    @property
    def active_feature(self):
        """Look up the currently active sketch/extrusion feature.

        Returns:
            dict or None: Feature owned by the current model, or None if absent.
        """
        return next((f for f in self.model.features if f["id"]==self.active_id),None) if self.model else None

    def snapshot(self):
        """Capture editable model history, active feature, and selected support for undo.

        Returns:
            tuple: Independent geometry dictionary, active ID, and copied support.
        """
        return (self.model.geometry(),self.active_id,copy.deepcopy(self.selected_support))

    def restore(self,state):
        """Rebuild a saved snapshot and restore its active sketch and support selection.

        Args:
            state (tuple): Snapshot containing geometry, active feature ID, and selected
                support.

        Returns:
            None. Replaces the model and refreshes the UI.
        """
        self.model = FeatureModel.from_geometry(state[0])
        self.active_id,self.selected_support = state[1],copy.deepcopy(state[2])
        self.bind_active()
        self.refresh()

    def accept_model(self,candidate,active_id=None):
        """Build a candidate before committing it, record undo history, clear redo, and
        mark the document dirty.

        Args:
            candidate (FeatureModel): Independent edited history to build before
                replacing the current model.
            active_id (str, optional): Feature ID to activate after committing; None
                keeps the prior ID.

        Returns:
            None. Replaces the model on success; build errors propagate before
            commitment.
        """
        candidate.build()
        self.history.append(self.snapshot())
        self.future.clear()
        self.model = candidate
        if active_id is not None:
            self.active_id = active_id
        self.dirty = True
        self.bind_active()
        self.refresh()

    def bind_active(self):
        """Deserialize the active feature into the working sketch and update its plane
        label.

        Returns:
            None. Uses an empty Sketch if no feature is active.
        """
        feature = self.active_feature
        self.sketch = Sketch.from_geometry(feature["sketch"]) if feature else Sketch()
        if feature:
            support = feature["support"]
            self.sketch_plane_label = support.get("name",support.get("label","Face"))+" sketch · mm"

    def refresh(self,rebuild=True):
        """Refresh inherited sketch controls, 3D model references, summary, and optionally
        the feature tree.

        Args:
            rebuild (bool): Repopulate the feature tree as well as controls when True.

        Returns:
            None. Updates UI state without building new geometry.
        """
        super().refresh()
        if self.model is None or not hasattr(self,"tree"):
            return
        self.viewport.model = self.model
        self.viewport.active_id = self.active_id
        self.viewport.support = self.selected_support
        self.viewport.update()
        if rebuild:
            self.rebuild_tree()
        feature = self.active_feature
        text = f"{len(self.model.features)} sketches · {len(self.model.faces)} solid faces"
        if self.model.has_solid:
            text += f"\nVolume: {self.model.volume*1e9:.3f} mm³"
        if feature:
            support = feature["support"]
            text += "\n"+feature["name"]+" on "+support.get("name",support.get("label","Face"))
            text += "\n"+("Closed sketch — ready to extrude" if self.sketch.closed else "Open sketch")
            if feature["depth"] is not None:
                text += f"\nExtruded {feature['depth']*1000:g} mm"
        else:
            text += "\nSelect a plane or a model face, then New Sketch."
        self.summary.setText(text)
        self.statusBar().showMessage("Plane or face → New Sketch → draw/dimension → Finish Sketch → Extrude. Drag in 3D to orbit.")

    def rebuild_tree(self):
        """Repopulate reference planes, sketches/extrusions, and selectable faces while
        blocking selection signals.

        Returns:
            None. Replaces tree items and restores the active feature selection.
        """
        self.tree.blockSignals(True)
        self.tree.clear()
        planes = QTreeWidgetItem(self.tree,["Reference planes"])
        for name in PLANES:
            item = QTreeWidgetItem(planes,[name+" Plane"])
            item.setData(0,Qt.UserRole,("plane",name))
        features = QTreeWidgetItem(self.tree,["Sketches and extrusions"])
        for i,feature in enumerate(self.model.features):
            support = feature["support"]
            parent = QTreeWidgetItem(features,[feature["name"]+" · "+support.get("name",support.get("label","Face"))])
            parent.setData(0,Qt.UserRole,("feature",feature["id"]))
            if feature["id"]==self.active_id:
                self.tree.setCurrentItem(parent)
            if feature["depth"] is not None:
                item = QTreeWidgetItem(parent,[f"Extrude {i+1} · {feature['depth']*1000:g} mm"])
                item.setData(0,Qt.UserRole,("extrusion",feature["id"]))
        faces = QTreeWidgetItem(self.tree,["Solid faces"])
        for i,face in enumerate(self.model.faces):
            item = QTreeWidgetItem(faces,[face["label"]])
            item.setData(0,Qt.UserRole,("face",i))
            item.setToolTip(0,"Select this flat face, then New Sketch")
        planes.setExpanded(True)
        features.setExpanded(True)
        self.tree.blockSignals(False)

    def tree_clicked(self,item,column=0):
        """Select the plane, face, or feature described by a tree item's stored role data.

        Args:
            item (QTreeWidgetItem): Clicked row containing plane, face, feature, or
                extrusion role data.
            column (int): Clicked tree column from Qt; currently unused.

        Returns:
            None. Updates active sketch/support and refreshes controls.
        """
        value = item.data(0,Qt.UserRole)
        if not value:
            return
        if value[0]=="plane":
            self.selected_support = {"type":"plane","name":value[1]}
            self.viewport.selected_face = -1
            self.view_model()
        elif value[0]=="face":
            self.view_model()
            self.select_face(value[1])
        else:
            self.active_id = value[1]
            self.bind_active()
            self.viewport.selected_face = -1
            self.selected_support = copy.deepcopy(self.active_feature["support"])
        self.refresh(rebuild=False)

    def tree_double_clicked(self,item,column=0):
        """Open a feature's sketch for editing, or create a sketch on a selected
        plane/face.

        Args:
            item (QTreeWidgetItem): Clicked row containing plane, face, feature, or
                extrusion role data.
            column (int): Clicked tree column from Qt; currently unused.

        Returns:
            None. Switches views and may create feature history.
        """
        value = item.data(0,Qt.UserRole)
        if value and value[0] in ("feature", "extrusion"):
            self.active_id = value[1]
            self.edit_sketch()
        elif value and value[0] in ("plane","face"):
            self.tree_clicked(item)
            self.new_sketch()

    def select_plane(self,name):
        """Select a named reference plane in the hierarchy and switch to the model view.

        Args:
            name (str): Reference plane name: Front, Right, or Top.

        Returns:
            None. Updates support and status text if the plane is found.
        """
        planes = self.tree.topLevelItem(0)
        if planes is None:
            return
        for index in range(planes.childCount()):
            item = planes.child(index)
            if item.data(0,Qt.UserRole)==("plane",name):
                self.tree.setCurrentItem(item)
                self.tree_clicked(item)
                self.statusBar().showMessage(f"{name} Plane selected — choose New Sketch to draw on it.")
                break

    def select_face(self,index):
        """Select a valid built planar face as the support for a new sketch.

        Args:
            index (int): Zero-based planar face index in the built model.

        Returns:
            None. Synchronizes viewport highlight, tree selection, and support; invalid
            indices are ignored.
        """
        if not 0<=index<len(self.model.faces):
            return
        self.selected_support = self.model.face_support(index)
        self.viewport.selected_face = index
        self.viewport.support = self.selected_support
        self.viewport.update()
        faces = self.tree.topLevelItem(2)
        if faces is not None and index<faces.childCount():
            faces.setExpanded(True)
            self.tree.setCurrentItem(faces.child(index))
        self.statusBar().showMessage(f"{self.model.faces[index]['label']} selected — choose New Sketch to draw on this face.")

    def new_sketch(self):
        """Create a sketch on the selected support via a candidate model and enter sketch
        editing.

        Returns:
            None. Records undo on success; shows a warning for invalid supports or
            rebuild failures.
        """
        try:
            candidate = FeatureModel(self.model.features)
            feature = candidate.new_sketch(self.selected_support)
            self.accept_model(candidate,feature["id"])
            self.viewport.selected_face = -1
            self.edit_sketch()
        except (ValueError,RuntimeError) as error:
            QMessageBox.warning(self,"Cannot Create Sketch",str(error))

    def edit_sketch(self):
        """Bind the active sketch, show the 2D canvas, and fit its geometry; create a
        sketch first if needed.

        Returns:
            None.
        """
        if self.active_feature is None:
            self.new_sketch()
            return
        self.bind_active()
        self.stack.setCurrentWidget(self.canvas)
        self.line_action.setChecked(not self.sketch.closed)
        self.refresh()
        self.canvas.fit()

    def finish_sketch(self):
        """Leave drawing mode, show the 3D model, and frame its geometry.

        Returns:
            None. Does not implicitly extrude the sketch.
        """
        self.select_mode()
        self.view_model()
        self.viewport.fit()

    def view_model(self):
        """Leave drawing mode and display the 3D viewport.

        Returns:
            None. Schedules a viewport repaint.
        """
        self.select_mode()
        self.stack.setCurrentWidget(self.viewport)
        self.viewport.update()

    def frame_view(self):
        """Fit whichever viewport is currently displayed, including sketch context when
        applicable.

        Returns:
            None. Changes camera or canvas framing only.
        """
        self.viewport.fit() if self.stack.currentWidget() is self.viewport else self.canvas.fit()

    def set_drawing(self,value):
        """Toggle straight-line drawing and show or create an editable sketch when enabling
        it.

        Args:
            value (bool): Enable the requested drawing mode when True; disable it when
                False.

        Returns:
            None. Updates drawing actions and the active view.
        """
        super().set_drawing(value)
        if value and self.model is not None and hasattr(self,"stack"):
            if self.active_feature is None:
                self.new_sketch()
            else:
                self.stack.setCurrentWidget(self.canvas)

    def set_arcs(self,value):
        """Toggle arc drawing and ensure a sketch canvas is available when enabled.

        Args:
            value (bool): Enable the requested drawing mode when True; disable it when
                False.

        Returns:
            None. Updates drawing actions and may create a new sketch.
        """
        super().set_arcs(value)
        if value and self.model is not None and hasattr(self,"stack"):
            if self.active_feature is None:
                self.new_sketch()
                self.arc_action.setChecked(True)
            else:
                self.stack.setCurrentWidget(self.canvas)

    def set_circles(self,value):
        """Toggle circle drawing, creating an empty sketch when the active sketch already
        has geometry.

        Args:
            value (bool): Enable the requested drawing mode when True; disable it when
                False.

        Returns:
            None. Updates drawing actions and active view.
        """
        super().set_circles(value)
        if value and self.model is not None and hasattr(self,"stack"):
            if self.active_feature is None or self.sketch.points:
                self.new_sketch()
                self.circle_action.setChecked(True)
            else:
                self.stack.setCurrentWidget(self.canvas)

    def commit(self,candidate):
        """Validate an edited sketch, put it into a copied feature history, and
        rebuild/commit the candidate model.

        Args:
            candidate (Sketch): Independently edited outline to validate and commit.

        Returns:
            None. Records undo and marks dirty on success; invalid edits propagate
            errors before commitment.
        """
        if self.model is None:
            return super().commit(candidate)
        if self.active_feature is None:
            raise ValueError("Choose a plane or face and create a sketch first")
        candidate.validate()
        model = FeatureModel(self.model.features)
        feature = next(f for f in model.features if f["id"]==self.active_id)
        feature["sketch"] = candidate.geometry()
        self.accept_model(model)
        if candidate.closed:
            self.select_mode()

    def change_thickness(self,value):
        """Convert the control's millimetres to the active sketch's stored thickness and
        report the next extrusion distance.

        Args:
            value (float): Thickness/next-extrusion control value in millimetres,
                converted to metres.

        Returns:
            None. Commits an edited sketch when one is active.
        """
        if self.model is not None and self.active_feature is not None:
            candidate = copy.deepcopy(self.sketch)
            candidate.thickness = value/1000
            self.commit(candidate)
        self.statusBar().showMessage(f"Next extrusion distance: {value:g} mm")

    def dependent_features(self, roots):
        """Find transitive descendants whose face supports depend on the supplied features.

        Args:
            roots (iterable): Feature IDs whose transitive face-support dependents are
                sought.

        Returns:
            set: Dependent feature IDs, excluding the supplied root IDs.
        """
        removed = set(roots)
        while True:
            dependent = {f["id"] for f in self.model.features
                         if f["support"]["type"] == "face" and f["support"]["parent"] in removed}
            if dependent <= removed:
                return removed - set(roots)
            removed.update(dependent)

    def confirm_feature_deletion(self, message, dependent):
        """Ask whether to delete a feature, listing dependent sketches that will also be
        removed.

        Args:
            message (str): Deletion explanation shown before dependent-feature names.
            dependent (iterable): Dependent feature IDs to list in the deletion
                confirmation.

        Returns:
            bool: True only when the user confirms deletion.
        """
        if dependent:
            names = [f["name"] for f in self.model.features if f["id"] in dependent]
            message += "\n\nThese sketches depend on its faces and will also be deleted:\n" + "\n".join(names)
        return QMessageBox.question(
            self, "Delete Sketch / Extrusion", message + "\n\nYou can undo this change.",
            QMessageBox.Yes | QMessageBox.Cancel, QMessageBox.Cancel,
        ) == QMessageBox.Yes

    def accept_deletion(self, candidate, active_id=None):
        """Commit a deletion candidate, choose a surviving active feature/support, and
        clear stale selections.

        Args:
            candidate (FeatureModel): Independent edited history to build before
                replacing the current model.
            active_id (str, optional): Feature ID to activate after committing; None
                keeps the prior ID.

        Returns:
            None. Records undo and refreshes the editor.
        """
        self.accept_model(candidate, active_id)
        if self.active_feature is None:
            self.active_id = self.model.features[-1]["id"] if self.model.features else None
        self.selected_support = copy.deepcopy(self.active_feature["support"]) if self.active_feature else {"type":"plane", "name":"Front"}
        self.viewport.selected_face = -1
        self.canvas.selection = -1
        self.bind_active()
        self.select_mode()
        self.refresh()

    def delete_selected_segment(self):
        """Remove the selected sketch edge, split surviving outlines when needed, and
        remove affected extrusion/dependent features after confirmation.

        Returns:
            None. Commits a valid deletion or displays an error; cancellation preserves
            the model.
        """
        if self.model is None:
            return super().delete_selected_segment()
        if self.active_feature is None or not 0 <= self.canvas.selection < len(self.sketch.edges):
            self.statusBar().showMessage("Select a sketch line or arc to delete.", 5000)
            return
        try:
            pieces = self.sketch.without_segment(self.canvas.selection)
            root = self.active_id
            dependent = self.dependent_features({root})
            if self.active_feature["depth"] is not None:
                if not self.confirm_feature_deletion("Deleting this segment opens the sketch and removes its extrusion.", dependent):
                    return
            candidate = FeatureModel([f for f in self.model.features if f["id"] not in dependent])
            feature = next(f for f in candidate.features if f["id"] == root)
            feature["sketch"], feature["depth"], feature["symmetric"] = pieces[0].geometry(), None, False
            for number, piece in enumerate(pieces[1:], 2):
                extra = candidate.new_sketch(feature["support"])
                extra["name"] = feature["name"] + f" (section {number})"
                extra["sketch"] = piece.geometry()
            self.accept_deletion(candidate, root)
            self.stack.setCurrentWidget(self.canvas)
            self.statusBar().showMessage("Segment deleted. The remaining outline is open; Ctrl+Z restores it.", 7000)
        except (ValueError, RuntimeError) as error:
            QMessageBox.warning(self, "Cannot Delete Segment", str(error))

    def selected_tree_feature(self):
        """Resolve the selected sketch or extrusion row to its model feature.

        Returns:
            dict or None: Selected feature; shows selection guidance when absent.
        """
        item = self.tree.currentItem()
        value = item.data(0, Qt.UserRole) if item else None
        if value and value[0] in ("feature", "extrusion"):
            return next((f for f in self.model.features if f["id"] == value[1]), None)
        self.statusBar().showMessage("Select a sketch or extrusion in the feature tree first.", 5000)
        return None

    def delete_tree_item(self):
        """Dispatch feature-tree deletion to sketch or extrusion removal based on the
        current row.

        Returns:
            None. Non-feature rows are ignored.
        """
        item = self.tree.currentItem()
        value = item.data(0, Qt.UserRole) if item else None
        if value and value[0] == "extrusion":
            self.delete_extrusion()
        elif value and value[0] == "feature":
            self.delete_sketch()

    def delete_sketch(self):
        """Confirm and remove a sketch, its extrusion, and face-dependent descendants
        through a rebuilt candidate.

        Returns:
            None. Records undo on success; warnings report rebuild failures.
        """
        feature = self.selected_tree_feature()
        if feature is None:
            return
        root = feature["id"]
        dependent = self.dependent_features({root})
        description = feature["name"] + (" and its extrusion" if feature["depth"] is not None else "")
        if not self.confirm_feature_deletion(f"Delete {description}?", dependent):
            return
        candidate = FeatureModel([f for f in self.model.features if f["id"] not in dependent | {root}])
        try:
            self.accept_deletion(candidate)
            self.view_model()
        except (ValueError, RuntimeError) as error:
            QMessageBox.warning(self, "Cannot Delete Sketch", str(error))

    def delete_extrusion(self):
        """Confirm and remove an extrusion and its dependents while retaining its sketch.

        Returns:
            None. Commits a valid candidate, or preserves the model on
            cancellation/failure.
        """
        feature = self.selected_tree_feature()
        if feature is None or feature["depth"] is None:
            self.statusBar().showMessage("Select an extruded sketch or extrusion first.", 5000)
            return
        root = feature["id"]
        dependent = self.dependent_features({root})
        if not self.confirm_feature_deletion(f"Delete the extrusion of {feature['name']}? The sketch will be kept.", dependent):
            return
        candidate = FeatureModel([f for f in self.model.features if f["id"] not in dependent])
        kept = next(f for f in candidate.features if f["id"] == root)
        kept["depth"], kept["symmetric"] = None, False
        try:
            self.accept_deletion(candidate, root)
            self.view_model()
        except (ValueError, RuntimeError) as error:
            QMessageBox.warning(self, "Cannot Delete Extrusion", str(error))

    def extrude_face(self,index,distance,symmetric=False):
        """Derive a sketch from a selected flat face and add a joined extrusion through a
        candidate model.

        Args:
            index (int): Zero-based planar face index in the built model.
            distance (float): Signed extrusion depth in metres; negative reverses the
                support normal.
            symmetric (bool): Center the extrusion about its sketch plane when True.

        Returns:
            None. Commits history and frames the result; invalid boundaries or solids
            raise an error.
        """
        candidate = FeatureModel(self.model.features).build()
        sketch,support = candidate.face_sketch(index),candidate.face_support(index)
        feature = candidate.new_sketch(support)
        feature["name"] = f"Face extrusion {len(candidate.features)}"
        feature["sketch"] = sketch.geometry()
        feature["depth"],feature["symmetric"] = float(distance),bool(symmetric)
        self.accept_model(candidate,feature["id"])
        self.viewport.selected_face = -1
        self.view_model()
        self.viewport.fit()

    def extrude_active(self,distance,symmetric=False):
        """Set the active closed sketch's extrusion depth/mode in copied history and
        rebuild the solid.

        Args:
            distance (float): Signed extrusion depth in metres; negative reverses the
                support normal.
            symmetric (bool): Center the extrusion about its sketch plane when True.

        Returns:
            None. Commits history and frames the result; invalid geometry raises an
            error.
        """
        if self.active_feature is None or not self.sketch.closed:
            raise ValueError("Create and close a sketch before extruding it")
        candidate = FeatureModel(self.model.features)
        feature = next(f for f in candidate.features if f["id"]==self.active_id)
        feature["depth"],feature["symmetric"] = float(distance),bool(symmetric)
        self.accept_model(candidate)
        self.view_model()
        self.viewport.selected_face = -1
        self.viewport.fit()

    def extrude_dialog(self):
        """Collect extrusion distance, reverse direction, and symmetry, then extrude the
        selected face or active sketch.

        Returns:
            None. Converts millimetres to metres and displays build errors without
            committing invalid geometry.
        """
        direct_face = self.viewport.selected_face if self.stack.currentWidget() is self.viewport else -1
        if direct_face<0 and (self.active_feature is None or not self.sketch.closed):
            QMessageBox.information(self,"Extrude Sketch","Select a closed sketch in the tree, or create one on a plane or face first.")
            return
        dialog = QDialog(self)
        dialog.setWindowTitle("Extrude Face")
        layout = QVBoxLayout(dialog)
        form = QFormLayout()
        distance = QDoubleSpinBox()
        distance.setObjectName("extrudeDistance")
        distance.setRange(.001,1e6)
        distance.setDecimals(3)
        distance.setSuffix(" mm")
        depth = self.active_feature["depth"] if direct_face<0 else None
        distance.setValue(abs(depth)*1000 if depth is not None else self.thickness.value())
        reverse = QCheckBox("Reverse direction")
        reverse.setChecked(depth is not None and depth<0)
        symmetric = QCheckBox("Symmetric about sketch plane")
        symmetric.setChecked(self.active_feature["symmetric"] if direct_face<0 else False)
        form.addRow("Distance:",distance)
        layout.addLayout(form)
        layout.addWidget(reverse)
        layout.addWidget(symmetric)
        buttons = QDialogButtonBox(QDialogButtonBox.Ok|QDialogButtonBox.Cancel)
        buttons.accepted.connect(dialog.accept)
        buttons.rejected.connect(dialog.reject)
        layout.addWidget(buttons)
        if dialog.exec()==QDialog.Accepted:
            try:
                method = self.extrude_active if direct_face<0 else lambda d,s: self.extrude_face(direct_face,d,s)
                method(distance.value()/1000*(-1 if reverse.isChecked() else 1),symmetric.isChecked())
            except (ValueError,RuntimeError) as error:
                QMessageBox.warning(self,"Cannot Extrude",str(error))

    def undo(self):
        """Restore the previous feature-model snapshot and move the current snapshot to
        redo history.

        Returns:
            None. Marks the document dirty; no change when undo history is empty.
        """
        if self.history:
            self.future.append(self.snapshot())
            self.restore(self.history.pop())
            self.dirty = True
            self.refresh()

    def redo(self):
        """Restore the next feature-model snapshot and save the current snapshot in undo
        history.

        Returns:
            None. Marks the document dirty; no change when redo history is empty.
        """
        if self.future:
            self.history.append(self.snapshot())
            self.restore(self.future.pop())
            self.dirty = True
            self.refresh()

    def sketch_context_geometry(self):
        """Build the history before the active sketch and project visible solid faces/edges
        into its drawing frame. Cache by model identity and active ID.

        Returns:
            tuple: Projected 2D triangles and boundary edges, or two empty lists with no
            active feature.
        """
        feature = self.active_feature
        if not feature:
            return [], []
        cache = getattr(self, "_sketch_context_cache", None)
        if cache is not None and cache[:2] == (self.model, self.active_id):
            return cache[2]
        index = self.model.features.index(feature)
        context = FeatureModel(self.model.features[:index]).build()
        frame = support_frame(feature["support"])
        normal = np.cross(frame["u"],frame["v"])
        triangles, edges = [], []
        for face in context.faces:
            # Only faces pointing toward the sketch viewer have projected area.
            if np.dot(face["normal"], normal) <= 1e-7:
                continue
            triangles.extend(to_plane(face["triangles"], frame))
            edges.extend(to_plane(edge, frame) for edge in face["edges"])
        result = (triangles, edges)
        self._sketch_context_cache = (self.model, self.active_id, result)
        return result

    def sketch_context_points(self):
        """Flatten projected solid context triangles for sketch framing.

        Returns:
            list: 2D points in metres in the active sketch frame.
        """
        triangles, _ = self.sketch_context_geometry()
        return [point for triangle in triangles for point in triangle]

    def paint_sketch_context(self,painter,canvas):
        """Paint projected solid faces and boundaries behind the active sketch while
        preserving painter state.

        Args:
            painter (QPainter): Active painter receiving sketch context drawing.
            canvas (SketchCanvas): Canvas providing metre-to-pixel projection.

        Returns:
            None. Draws into the supplied painter.
        """
        triangles, edges = self.sketch_context_geometry()
        painter.save()
        painter.setPen(Qt.NoPen)
        painter.setBrush(QColor("#454c54"))
        for triangle in triangles:
            painter.drawPolygon(QPolygonF([canvas.screen(point) for point in triangle]))
        painter.setPen(QPen(QColor("#89939d"), 1))
        for a, b in edges:
            painter.drawLine(canvas.screen(a), canvas.screen(b))
        painter.restore()

    def new_part(self):
        """Protect unsaved changes, then reset to an empty feature document with Front
        plane selected.

        Returns:
            None. Clears file path, history, selections, and dirty state after
            confirmation.
        """
        if self.confirm_changes():
            self.data,self.model = new_feature_document()
            self.active_id,self.path,self.dirty = None,None,False
            self.selected_support = {"type":"plane","name":"Front"}
            self.history.clear()
            self.future.clear()
            self.bind_active()
            self.name.setText(self.data["name"])
            self.select_mode()
            self.view_model()
            self.refresh()
            self.viewport.fit()

    def open_path(self,path):
        """Load/migrate a JSON part into feature history, replacing editor state only after
        successful loading.

        Args:
            path (str or Path): Source or destination file path used by this operation.

        Returns:
            bool: True on success; False after displaying a load error.
        """
        try:
            data,model = open_feature_document(path)
        except (OSError,ValueError,TypeError,RuntimeError,ImportError) as error:
            QMessageBox.warning(self,"Cannot Open Part",f"{error}\nOpen a JSON box, sketch part or feature part. Legacy OBJ meshes have no editable features.")
            return False
        self.data,self.model,self.path = data,model,Path(path)
        self.active_id = model.features[-1]["id"] if model.features else None
        self.selected_support = copy.deepcopy(self.active_feature["support"]) if self.active_feature else {"type":"plane","name":"Front"}
        self.dirty = False
        self.history.clear()
        self.future.clear()
        self.bind_active()
        self.name.setText(data["name"])
        self.select_mode()
        self.view_model()
        self.refresh()
        self.viewport.fit()
        return True

    def _save_to(self,path):
        """Save current version-3 history and update the path and clean state only on
        success.

        Args:
            path (str or Path): Source or destination file path used by this operation.

        Returns:
            bool: True when saved; False after displaying a save error.
        """
        try:
            data = save_feature_document(path,self.data,self.model)
        except (OSError,ValueError,RuntimeError) as error:
            QMessageBox.warning(self,"Cannot Save Part",str(error))
            return False
        self.data,self.path,self.dirty = data,Path(path),False
        self.refresh()
        return True

    def export_mesh(self,kind):
        """Prompt for a destination and export the built solid as OBJ or STL without
        changing document save state.

        Args:
            kind (str): Mesh format, obj or stl.

        Returns:
            bool: True when exported; False for no solid, cancellation, or reported
            failure.
        """
        if not self.model.has_solid:
            QMessageBox.information(self,"Export Part","Extrude a closed sketch before exporting the 3D solid.")
            return False
        path,_ = QFileDialog.getSaveFileName(self,f"Export {kind.upper()}",str((self.path or Path("part.simuOPart")).with_suffix("."+kind)),f"{kind.upper()} Mesh (*.{kind})")
        if not path:
            return False
        path = Path(path)
        if path.suffix.lower()!="."+kind:
            path = path.with_suffix("."+kind)
            if path.exists() and QMessageBox.question(self,"Replace Export",f"Replace {path.name}?",QMessageBox.Yes|QMessageBox.Cancel)!=QMessageBox.Yes:
                return False
        try:
            export_vertices(path,self.model.vertices,kind)
        except (OSError,ValueError) as error:
            QMessageBox.warning(self,"Cannot Export",str(error))
            return False
        return True

    def show_controls(self):
        """Display the feature editor's sketching, extrusion, selection, and navigation
        guidance.

        Returns:
            None. Opens an informational dialog.
        """
        QMessageBox.information(self,"Part Editor — 3D Features",
            "Select Front, Right or Top Plane in the hierarchy, then New Sketch.\n"
            "Draw lines or three-point arcs, then close the outline to make a face. Dimensions use millimeters; arcs dimension by radius (R).\n"
            "Constraints: select straight lines for Horizontal/Vertical; Ctrl-click multiple lines for Equal. Delete relations or dimensions from the Constraints list to release them.\n"
            "Finish Sketch returns to the 3D view. Extrude adds material along the sketch normal.\n\n"
            "Click a flat model face (or choose it under Solid faces), then New Sketch to draw on it.\n"
            "While drawing, hover near a visible solid corner or edge to snap precisely to it. The locked marker shows the target; move away to release it. Sketch lines also snap.\n"
            "Double-click a sketch in the tree to edit it. Undo/redo includes sketches and extrusions.\n\n"
            "Backspace/Delete removes a selected sketch segment. Features → Delete Sketch / Delete Extrusion removes the selected tree item; deleting an extrusion keeps its sketch. Dependent sketches are listed before removal.\n\n"
            "3D: drag to orbit, middle-drag to pan, wheel to zoom, F to frame.\n"
            "Sketch: middle-drag to pan, wheel to zoom, double-click a segment to dimension.\n"
            "Choose Select line and drag an endpoint to move it within its constraints. Other endpoints stay fixed; Esc cancels and Ctrl+Z undoes the move.\n"
            "Cuts, fillets and curved-face sketches are not yet supported.")
