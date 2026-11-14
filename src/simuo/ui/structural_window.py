"""Structural workspace using the shared editor panels, materials and menus."""
from dataclasses import replace
from pathlib import Path
import sys
import numpy as np
from PySide6.QtCore import Qt, QTimer, QSettings, QSignalBlocker
from PySide6.QtGui import QAction, QActionGroup, QKeySequence
from PySide6.QtWidgets import (QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
    QFormLayout, QPushButton, QLabel, QLineEdit, QComboBox, QListWidget, QTreeWidget,
    QTreeWidgetItem, QAbstractItemView, QFileDialog, QMessageBox, QDoubleSpinBox,
    QCheckBox, QFrame, QSizePolicy, QAbstractSpinBox, QStackedWidget, QScrollArea, QTabWidget, QProgressBar, QMenu, QToolButton)

from simuo.materials import MaterialDefinition
from simuo.structural.models import (AnalysisSetup, Material, MeshSettings, SurfaceLoad,
    PointLoad, SupportCondition, BeamConfiguration, all_supports, point_targets)
from simuo.structural.jobs import BackgroundJob
from simuo.structural.persistence import load_analysis, save_analysis
from simuo.structural.meshing import point_position, bind_point_targets
from simuo.structural.constraints import restraint_reason
from simuo.editor.structural_state import StructuralState, StructuralInputs
from simuo.project.project_format import read_project, PROJECT_FILTER
from simuo.ui.structural_viewport import StructuralViewport, BeamDiagram
from simuo.ui.material_inspector import MaterialInspector
from simuo.ui.panels.properties import InspectorSection, TransformSpinBox, numeric_frame
from simuo.ui.docking import PanelManager, PanelSpec
from simuo.ui.theme import load_stylesheet
from simuo.ui.viewport_tools import ViewportToolRail, tool_icon
from simuo.ui.viewport_options import ToolOptionCombo
from simuo.ui.recent_projects import remember_project, record_saved_project


class StructuralWindow(QMainWindow):
    def __init__(self, path=None):
        super().__init__()
        self.resize(1280, 800)
        self.setObjectName("structuralWindow")
        self.setStyleSheet(load_stylesheet("main_window"))
        self.geometry = self.mesh = self.result = None
        self.patches = ()
        self.analysis_path = None
        self.pending_setup = None
        self.pending_geometry_path = None
        self._geometry_dirty = False
        self._updating = False
        self._selection = ("solid", "")
        self._editing_load = None
        self._draft_anchor = None
        self._renaming_support = None
        self._repositioning = False
        self._readiness_cache = None
        self.state = StructuralState(self)
        self.job = BackgroundJob()
        self._build_ui()
        self.state.changed.connect(self.inputs_changed)
        self.state.undo_stack.cleanChanged.connect(self.update_title)
        self.sync_inputs()
        self.timer = QTimer(self)
        self.timer.timeout.connect(self.poll_job)
        self.timer.start(50)
        if path:
            QTimer.singleShot(0, lambda: self.open_path(path))

    @property
    def supports(self): return [s.triangles for s in self.conditions if s.kind == "fixed_face"]
    @property
    def conditions(self): return self.state.inputs.support_conditions
    @property
    def loads(self): return list(self.state.inputs.loads)
    @property
    def point_loads(self): return list(self.state.inputs.point_loads)
    @property
    def beam_clamp(self): return self.state.inputs.beam_clamp
    @property
    def beam_free(self): return self.state.inputs.beam_free
    @property
    def dirty(self):
        return self.geometry is not None and (self._geometry_dirty or not self.state.undo_stack.isClean())

    def _action(self, menu, text, callback, shortcut=None):
        action = QAction(text, self)
        action.triggered.connect(callback)
        if shortcut:
            action.setShortcut(shortcut)
        menu.addAction(action)
        return action

    def _build_ui(self):
        file_menu = self.menuBar().addMenu("File")
        self._action(file_menu, "New Structural Analysis", self.new_analysis, QKeySequence.StandardKey.New)
        self._action(file_menu, "Open Project…", self.open_analysis, QKeySequence.StandardKey.Open)
        self._action(file_menu, "Import Solid…", self.import_geometry)
        file_menu.addSeparator()
        self._action(file_menu, "Save", self.save, QKeySequence.StandardKey.Save)
        self._action(file_menu, "Save As…", lambda: self.save(save_as=True), QKeySequence.StandardKey.SaveAs)
        edit = self.menuBar().addMenu("Edit")
        self.undo_action = self.state.undo_stack.createUndoAction(self, "Undo")
        self.redo_action = self.state.undo_stack.createRedoAction(self, "Redo")
        self.undo_action.setShortcuts(QKeySequence.keyBindings(QKeySequence.StandardKey.Undo))
        self.redo_action.setShortcuts(QKeySequence.keyBindings(QKeySequence.StandardKey.Redo))
        edit.addActions([self.undo_action, self.redo_action])
        self._action(edit, "Delete Selected Condition", self.remove_selected, QKeySequence("Delete"))
        view = self.menuBar().addMenu("View")
        self._action(view, "Frame Selected", self.frame_selected, "F")
        self._action(view, "Frame All", lambda: self.viewport.frame_all(), "Shift+F")
        self.tools_visible = view.addAction("Viewport Tools")
        self.tools_visible.setCheckable(True)
        self.tools_visible.setChecked(True)
        analysis = self.menuBar().addMenu("Analysis")
        self.generate_action = self._action(analysis, "Generate Mesh", self.generate_mesh)
        self.generate_action.setToolTip("Generate the tetrahedral mesh without running analysis")
        self.solve_action = self._action(analysis, "Run Analysis", self.solve, "Ctrl+R")
        self._action(analysis, "Cancel", self.cancel)
        help_menu = self.menuBar().addMenu("Help")
        self._action(help_menu, "Controls", lambda: QMessageBox.information(self, "Structural controls",
            "Choose a material, add supports and loads, generate a mesh, then run analysis.\n\n"
            "Left-click selects or places a load. Ctrl-click adds faces. Right-drag looks around; WASD moves the camera; Space moves up and Alt moves down without right-click. F frames the selection; Shift+F frames the solid. Escape cancels placement.\n\n"
            "Pressure pushes perpendicular to selected faces; total force depends on their area."))
        self.viewport = StructuralViewport()
        self.setCentralWidget(self.viewport)
        self.viewport.patch_clicked.connect(self.select_patch)
        self.viewport.point_picked.connect(self.point_picked)
        self.viewport.load_picked.connect(lambda key: self.select_item("point", key))
        self.viewport.support_picked.connect(lambda key: self.select_item("support", key))
        self.viewport.placement_cancelled.connect(self.cancel_placement)
        self.viewport.frame_requested.connect(self.frame_selected)
        self.create_viewport_tools()
        self.hierarchy_panel = QWidget()
        self.hierarchy_panel.setObjectName("editorPanel")
        hierarchy_layout = QVBoxLayout(self.hierarchy_panel)
        hierarchy_layout.setContentsMargins(6, 6, 6, 6)
        self.tree = QTreeWidget()
        self.tree.setHeaderHidden(True)
        self.tree.setObjectName("analysisHierarchy")
        self.tree.itemSelectionChanged.connect(self.tree_selected)
        self.tree.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.tree.customContextMenuRequested.connect(self.tree_menu)
        hierarchy_layout.addWidget(self.tree, 1)
        selection_section = self.selection_section = InspectorSection("Surface Selection")
        selection_section.toggle.setChecked(False)
        sl = QVBoxLayout(selection_section.body)
        self.patch_list = QListWidget()
        self.patch_list.setSelectionMode(QAbstractItemView.SelectionMode.ExtendedSelection)
        self.patch_list.setMaximumHeight(155)
        self.patch_list.itemSelectionChanged.connect(self.selection_changed)
        sl.addWidget(self.patch_list)
        hierarchy_layout.addWidget(selection_section)
        self.properties = QStackedWidget()
        self.properties.setObjectName("editorPanel")
        self.properties.setStyleSheet(load_stylesheet("properties"))
        self.pages = {}
        solid, form = self.make_page("solid", "Solid")
        self.summary = QLabel("Import one closed .simuOPart, OBJ or STL solid.")
        self.summary.setWordWrap(True)
        form.addRow(self.summary)
        self.units = QComboBox()
        self.units.setObjectName("inspectorCombo")
        self.units.addItems(["m", "mm", "cm", "in"])
        form.addRow("OBJ/STL units", self.units)
        self.units.currentTextChanged.connect(self.units_changed)
        self.button(form, "Import Solid…", self.import_geometry)
        material_page = QWidget()
        material_page.setObjectName("editorPanel")
        ml = QVBoxLayout(material_page)
        ml.setContentsMargins(0, 0, 0, 0)
        self.material_section = MaterialInspector()
        self.material_section.material_changed.connect(self.material_changed)
        ml.addWidget(self.material_section)
        gravity = InspectorSection("Gravity")
        gf = QFormLayout(gravity.body)
        self.gravity_on = QCheckBox("Enable gravity")
        self.gravity_on.toggled.connect(self.gravity_changed)
        gf.addRow(self.gravity_on)
        self.gravity_fields, gravity_row = self.vector_fields("Gravity", (0., -9.80665, 0.))
        for field in self.gravity_fields:
            field.editingFinished.connect(self.gravity_changed)
        gf.addRow(QLabel("Acceleration (m/s²)"))
        gf.addRow(gravity_row)
        ml.addWidget(gravity)
        ml.addStretch()
        material_scroll = QScrollArea()
        material_scroll.setWidgetResizable(True)
        material_scroll.setFrameShape(QScrollArea.Shape.NoFrame)
        material_scroll.setWidget(material_page)
        self.pages["material"] = self.properties.addWidget(material_scroll)
        _, supports = self.make_page("supports", "Support")
        self.support_hint = QLabel("Click the solid with a support tool. Fixed points restrain translation; face pins allow rotation about their centroid.")
        self.support_hint.setWordWrap(True)
        supports.addRow(self.support_hint)
        self.support_name = QLineEdit()
        self.support_name.setPlaceholderText("Support name")
        self.support_name.editingFinished.connect(self.rename_support)
        supports.addRow("Name", self.support_name)
        self.support_kind = QComboBox()
        self.support_kind.setObjectName("inspectorCombo")
        for label, kind in (("Fixed face", "fixed_face"), ("Pinned face", "pinned_face"), ("Fixed point", "fixed_point")):
            self.support_kind.addItem(label, kind)
        self.support_kind.currentIndexChanged.connect(self.change_support_kind)
        self.support_kind.model().item(self.support_kind.findData("fixed_point")).setEnabled(False)
        supports.addRow("Type", self.support_kind)
        self.support_place_button = self.button(supports, "Reposition Point…", self.reposition_support)
        self.support_place_button.hide()
        self.button(supports, "Delete Support", self.remove_selected)
        _, load = self.make_page("loads", "Load")
        self.load_kind = QComboBox()
        self.load_kind.setObjectName("inspectorCombo")
        for text, key in (("Force at a point", "point"), ("Force over a face", "force"), ("Pressure on a face", "pressure")):
            self.load_kind.addItem(text, key)
        self.load_kind.currentIndexChanged.connect(self.load_kind_changed)
        load.addRow("Type", self.load_kind)
        self.load_name = QLineEdit()
        self.load_name.setPlaceholderText("Load name")
        load.addRow("Name", self.load_name)
        self.load_name.editingFinished.connect(self.commit_load)
        self.force_fields, self.force_row = self.vector_fields("Force", (0., 0., 0.))
        for field in self.force_fields:
            field.editingFinished.connect(self.commit_load)
            field.valueChanged.connect(self.update_load_preview)
        self.force_label = QLabel("Force (N)")
        load.addRow(self.force_label, self.force_row)
        self.pressure_row = QWidget()
        pr = QHBoxLayout(self.pressure_row)
        pr.setContentsMargins(0, 0, 0, 0)
        self.pressure = self.numeric("Pressure", minimum=0.)
        self.pressure.editingFinished.connect(self.commit_load)
        self.pressure.valueChanged.connect(self.update_load_preview)
        self.pressure_units = QComboBox()
        self.pressure_units.setObjectName("inspectorCombo")
        for unit, scale in (("Pa", 1.), ("kPa", 1000.), ("MPa", 1e6)):
            self.pressure_units.addItem(unit, scale)
        self.pressure_units.setCurrentIndex(1)
        self.pressure_units.currentIndexChanged.connect(self.pressure_unit_changed)
        pr.addWidget(self.pressure, 1)
        pr.addWidget(self.pressure_units)
        self.pressure_label = QLabel("Pressure")
        load.addRow(self.pressure_label, self.pressure_row)
        self.pressure_direction = QComboBox()
        self.pressure_direction.setObjectName("inspectorCombo")
        self.pressure_direction.addItems(["Push inward", "Pull outward"])
        self.pressure_direction.currentIndexChanged.connect(self.commit_load)
        self.direction_label = QLabel("Direction")
        load.addRow(self.direction_label, self.pressure_direction)
        self.load_hint = QLabel()
        self.load_hint.setWordWrap(True)
        load.addRow(self.load_hint)
        self.place_button = self.button(load, "Place Point…", self.begin_point_placement)
        self.apply_load_button = self.button(load, "Duplicate Load", self.duplicate_load)
        self.button(load, "Delete Load", self.remove_selected)
        _, mesh = self.make_page("mesh", "Mesh")
        self.size = self.numeric("Target element size", 1e-9)
        self.size.setDecimals(9)
        self.size.setValue(.05)
        self.size.valueChanged.connect(self.mesh_size_changed)
        mesh.addRow("Element size (m)", self.size)
        self.action_button(mesh, self.generate_action)
        self.action_button(mesh, self.solve_action)
        self.readiness = QLabel()
        self.readiness.setWordWrap(True)
        mesh.addRow(self.readiness)
        _, beam = self.make_page("results", "Beam Diagram")
        self.beam_label = QLabel()
        self.beam_label.setWordWrap(True)
        beam.addRow(self.beam_label)
        self.button(beam, "Use Selected Faces as Clamp End", lambda: self.set_beam_end(True))
        self.button(beam, "Use Selected Faces as Free End", lambda: self.set_beam_end(False))
        self.button(beam, "Clear Beam Configuration", self.clear_beam)
        self.stress_range = QComboBox()
        self.stress_range.setObjectName("inspectorCombo")
        self.stress_range.addItems(["Full stress range", "Custom maximum"])
        self.stress_max = self.numeric("Stress legend maximum", 1e-9)
        self.stress_max.setValue(1e6)
        self.stress_range.currentIndexChanged.connect(self.stress_scale_changed)
        self.stress_max.editingFinished.connect(self.stress_scale_changed)
        beam.addRow("Stress colours", self.stress_range)
        beam.addRow("Maximum (Pa)", self.stress_max)
        self.results_tabs = QTabWidget()
        self.results_tabs.setObjectName("analysisResults")
        self.report = QLabel("Run analysis to see displacement, stress and equilibrium results.")
        self.report.setObjectName("analysisReport")
        self.report.setAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignTop)
        self.report.setWordWrap(True)
        self.report.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        summary_scroll = QScrollArea()
        summary_scroll.setWidgetResizable(True)
        summary_scroll.setWidget(self.report)
        self.results_tabs.addTab(summary_scroll, "Summary")
        self.diagram = BeamDiagram()
        self.results_tabs.addTab(self.diagram, "Beam Diagram")
        settings = QSettings("SimuOttawa", "SimuO.Structural")
        self.panel_manager = PanelManager(self, view, settings=settings)
        for spec in (
            PanelSpec("analysis_hierarchy", "Analysis Hierarchy", lambda: self.hierarchy_panel, default_width=330, default_height=220),
            PanelSpec("analysis_properties", "Properties", lambda: self.properties, default_width=330, default_height=340),
            PanelSpec("analysis_results", "Results", lambda: self.results_tabs, Qt.DockWidgetArea.BottomDockWidgetArea, default_height=180)):
            self.panel_manager.register_panel(spec)
        self.panel_manager.restore_layout()
        self.panel_manager.docks["analysis_results"].hide()
        self.progress = QProgressBar()
        self.progress.setMaximumWidth(150)
        self.progress.setRange(0, 1)
        self.statusBar().setObjectName("analysisStatus")
        self.statusBar().addPermanentWidget(self.progress)
        self.statusBar().showMessage("Import a solid, choose a material, fix faces, then add loads.")
        for dock in self.panel_manager.docks.values():
            dock.addActions([self.undo_action, self.redo_action])

    def make_page(self, key, title):
        content = QWidget()
        content.setObjectName("editorPanel")
        layout = QVBoxLayout(content)
        layout.setContentsMargins(0, 0, 0, 0)
        section = InspectorSection(title)
        form = QFormLayout(section.body)
        form.setContentsMargins(10, 10, 10, 10)
        layout.addWidget(section)
        layout.addStretch()
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QScrollArea.Shape.NoFrame)
        scroll.setWidget(content)
        self.pages[key] = self.properties.addWidget(scroll)
        return content, form

    @staticmethod
    def button(form, text, callback):
        button = QPushButton(text)
        button.clicked.connect(callback)
        form.addRow(button)
        return button

    @staticmethod
    def action_button(form, action):
        button = QToolButton()
        button.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextOnly)
        button.setDefaultAction(action)
        form.addRow(button)
        return button

    @staticmethod
    def numeric(name, minimum=-1e12):
        field = TransformSpinBox()
        field.setRange(minimum, 1e12)
        field.setDecimals(6)
        field.setKeyboardTracking(False)
        field.setButtonSymbols(QAbstractSpinBox.ButtonSymbols.NoButtons)
        field.setAccessibleName(name)
        field.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Fixed)
        field.setMinimumWidth(0)
        return field

    def vector_fields(self, name, values):
        row = QWidget()
        layout = QHBoxLayout(row)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(4)
        fields = []
        for axis, value in zip("XYZ", values):
            field = self.numeric(f"{name} {axis}")
            field.setPrefix(axis+" ")
            field.setValue(value)
            layout.addWidget(numeric_frame(field, axis))
            fields.append(field)
        return fields, row

    def create_viewport_tools(self):
        rail = self.viewport.tool_rail = ViewportToolRail(self.viewport)
        rail.setStyleSheet(load_stylesheet("viewport_tools"))
        self.tool_group = QActionGroup(self)
        self.tool_actions = {}
        for key, label in (("select", "Select"), ("clamp", "Fixed Face"), ("pinned_face", "Pinned Face"), ("fixed_point", "Fixed Point"), ("point", "Point Force"), ("force", "Face Force"), ("pressure", "Face Pressure")):
            action = QAction(tool_icon(key), label, self.tool_group)
            action.setCheckable(True)
            action.triggered.connect(lambda checked=False, tool=key: self.activate_tool(tool))
            rail.add_tool(action)
            self.tool_actions[key] = action
        self.tool_actions["select"].setChecked(True)
        rail.add_separator()
        expand = QAction("»", self)
        expand.setCheckable(True)
        expand.setToolTip("Expand tool labels")
        expand.toggled.connect(lambda value: (rail.set_expanded(value), self.viewport.layout_tools()))
        rail.add_tool(expand, toggle=True)
        self.tools_visible.toggled.connect(rail.setVisible)
        context = self.viewport.tool_context = QFrame(self.viewport)
        context.setObjectName("toolContext")
        context.setStyleSheet(load_stylesheet("viewport_tools"))
        row = QHBoxLayout(context)
        row.setContentsMargins(8, 4, 8, 4)
        self.view_mode = ToolOptionCombo(context)
        self.view_mode.addItems(["Setup", "Mesh", "Stress"])
        self.view_mode.currentTextChanged.connect(self.view_changed)
        row.addWidget(self.view_mode)
        add = QPushButton("Add Load…")
        menu = QMenu(add)
        for text, key in (("Force at a point", "point"), ("Force over a face", "force"), ("Pressure on a face", "pressure")):
            menu.addAction(text, lambda key=key: self.new_load(key))
        add.setMenu(menu)
        row.addWidget(add)
        for action in (self.generate_action, self.solve_action):
            button = QToolButton()
            button.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextOnly)
            button.setDefaultAction(action)
            row.addWidget(button)
        context.adjustSize()
        self.viewport.layout_tools()

    def activate_tool(self, key):
        self._repositioning_support = None
        if key in ("point", "force", "pressure"):
            self.new_load(key)
        elif key in ("clamp", "pinned_face", "fixed_point"):
            self._editing_load = None
            self.selection_section.toggle.setChecked(key != "fixed_point")
            self.viewport.set_tool(key)
            self.select_item("supports", "")
            self.statusBar().showMessage("Click the solid to place a support. Ctrl-click extends the selected face support.")
        else:
            self.cancel_placement()
        self.tool_actions[key].setChecked(True)

    def error(self, error):
        self.statusBar().showMessage(str(error))
        QMessageBox.warning(self, "Structural Analysis", str(error))

    def update_title(self, *args):
        name = Path(self.analysis_path).name if self.analysis_path else "Untitled"
        self.setWindowTitle(f"SimuO — Structural Analysis — {name}{' *' if self.dirty else ''}")

    def inputs_changed(self, before, after):
        if self._updating:
            return
        mesh_changed = before.mesh_size != after.mesh_size or before.feature_angle != after.feature_angle
        if mesh_changed:
            self.mesh = None
        numerical = replace(before, support_names=(), support_conditions=tuple(replace(v, name="") for v in before.support_conditions),
                            loads=tuple(replace(v, name="") for v in before.loads), point_loads=tuple(replace(v, name="") for v in before.point_loads)) != replace(
                            after, support_names=(), support_conditions=tuple(replace(v, name="") for v in after.support_conditions),
                            loads=tuple(replace(v, name="") for v in after.loads), point_loads=tuple(replace(v, name="") for v in after.point_loads))
        if numerical:
            self._readiness_cache = None
            if (mesh_changed and self.job.operation == "mesh") or self.job.operation == "solve":
                self.job.invalidate()
            self.result = None
            self.diagram.result = None
            self.diagram.update()
            self.report.setText("Inputs changed. Choose Run Analysis to update results; generate a mesh first if required.")
        self.sync_inputs()

    def sync_inputs(self):
        self._updating = True
        try:
            inputs = self.state.inputs
            density = self.geometry.density if self.geometry else None
            self.material_section.set_material(inputs.material, MaterialDefinition("From Part", density=density))
            self.units.setCurrentText(inputs.units)
            self.size.setValue(inputs.mesh_size)
            self.gravity_on.setChecked(inputs.gravity_enabled)
            for field, value in zip(self.gravity_fields, inputs.gravity):
                field.setValue(value)
            self.beam_label.setText(f"Clamp end: {'selected' if inputs.beam_clamp else 'missing'}\nFree end: {'selected' if inputs.beam_free else 'missing'}")
            kind, key = self._selection
            if (kind in ("point", "load") and key not in {load.identifier for load in (*self.loads, *self.point_loads)}):
                self._selection = ("loads", "")
                self._editing_load = self._draft_anchor = None
                self.viewport.draft_point = None
            elif kind == "support" and key not in {v.identifier for v in self.conditions}:
                self._selection = ("supports", "")
            self.rebuild_tree()
            self.show_properties(*self._selection)
        finally:
            self._updating = False
        self.refresh_view()
        self.update_title()
        self.update_actions()

    def rebuild_tree(self):
        self.tree.blockSignals(True)
        try:
            self.tree.clear()
            def item(parent, text, kind, key=""):
                node = QTreeWidgetItem(parent, [text])
                node.setData(0, Qt.ItemDataRole.UserRole, (kind, key))
                if kind in ("point", "load", "supports", "support"):
                    node.setIcon(0, tool_icon(next((v.kind if v.kind != "fixed_face" else "clamp" for v in self.conditions if v.identifier == key), "clamp") if kind == "support" else "point" if kind == "point" else "force" if kind == "load" else "clamp"))
                else:
                    from simuo.ui.panels.hierarchy.icons import outliner_icon
                    node.setIcon(0, outliner_icon("mesh" if kind in ("solid", "mesh") else "material" if kind == "material" else "results" if kind == "results" else "group"))
                node.setExpanded(True)
                if self._selection == (kind, key):
                    node.setSelected(True)
                return node
            root = self.tree.invisibleRootItem()
            item(root, Path(self.geometry.path).name if self.geometry else "Solid", "solid")
            material = self.state.inputs.material
            item(root, "Material — "+(material.name if material else "From Part"), "material")
            supports = item(root, "Supports", "supports")
            for support in self.conditions:
                item(supports, support.name or support.kind.replace("_", " ").title(), "support", support.identifier)
            loads = item(root, "Loads", "loads")
            for load in self.loads:
                item(loads, load.name or ("Face Force" if load.kind == "force" else "Face Pressure"), "load", load.identifier)
            for load in self.point_loads:
                item(loads, load.name, "point", load.identifier)
            item(root, "Mesh"+(f" — {len(self.mesh.tetrahedra)} tetrahedra" if self.mesh else ""), "mesh")
            item(root, "Results", "results")
        finally:
            self.tree.blockSignals(False)

    def select_item(self, kind, key=""):
        self._selection = (kind, key)
        self.rebuild_tree()
        self.show_properties(kind, key)

    def tree_selected(self):
        if self._updating or not self.tree.selectedItems():
            return
        kind, key = self.tree.selectedItems()[0].data(0, Qt.ItemDataRole.UserRole)
        self._selection = (kind, key)
        self.show_properties(kind, key)

    def show_properties(self, kind, key):
        page = {"support": "supports", "load": "loads", "point": "loads"}.get(kind, kind)
        self.properties.setCurrentIndex(self.pages.get(page, self.pages["solid"]))
        self._renaming_support = key if kind == "support" else None
        if kind == "support":
            support = next((v for v in self.conditions if v.identifier == key), None)
            if support is not None:
                with QSignalBlocker(self.support_kind):
                    self.support_kind.setCurrentIndex(self.support_kind.findData(support.kind))
                self.support_kind.setEnabled(support.kind != "fixed_point")
                self.support_place_button.setVisible(support.kind == "fixed_point")
                self.support_name.setText(support.name)
                self.highlight_faces(support.triangles)
        elif kind in ("point", "load"):
            load = next((load for load in (*self.loads, *self.point_loads) if load.identifier == key), None)
            if load is not None:
                self.edit_load(load)
        self.viewport.selected_support = key if kind == "support" else None
        self.viewport.selected_load = key if kind in ("point", "load") else None
        self.viewport.refresh()

    def tree_menu(self, position):
        node = self.tree.itemAt(position)
        if node:
            self.tree.setCurrentItem(node)
        menu = QMenu(self.tree)
        menu.addAction("Add Point Force", lambda: self.new_load("point"))
        menu.addAction("Add Face Force", lambda: self.new_load("force"))
        menu.addAction("Add Face Pressure", lambda: self.new_load("pressure"))
        if self._selection[0] in ("point", "load", "support"):
            menu.addSeparator()
            if self._selection[0] in ("point", "load"):
                menu.addAction("Duplicate", self.duplicate_load)
            menu.addAction("Delete", self.remove_selected)
        menu.exec(self.tree.mapToGlobal(position))

    def selected_triangles(self):
        indices = [self.patch_list.row(item) for item in self.patch_list.selectedItems()]
        if not indices:
            raise ValueError("Select one or more faces on the solid")
        return tuple(sorted(i for index in indices for i in self.patches[index].triangles))

    def selection_changed(self):
        self.viewport.selected = {self.patch_list.row(item) for item in self.patch_list.selectedItems()}
        self.viewport.refresh()
        self.update_load_preview()

    def highlight_faces(self, triangles):
        with QSignalBlocker(self.patch_list):
            self.patch_list.clearSelection()
            for i, patch in enumerate(self.patches):
                self.patch_list.item(i).setSelected(set(patch.triangles) <= set(triangles))
        self.selection_changed()

    def select_patch(self, index, additive):
        if not 0 <= index < self.patch_list.count():
            return
        tool = self.viewport.tool
        chosen = self.patches[index].triangles
        if tool in ("clamp", "pinned_face"):
            kind = "fixed_face" if tool == "clamp" else tool
            current = next((v for v in self.conditions if v.identifier == self._selection[1] and self._selection[0] == "support" and v.kind == kind), None)
            if additive and current:
                chosen = tuple(sorted(set(current.triangles) | set(chosen)))
                value = replace(current, triangles=chosen)
                self.state.edit("Extend Support", support_conditions=tuple(value if v.identifier == value.identifier else v for v in self.conditions))
            else:
                value = next((v for v in self.conditions if v.kind == kind and set(v.triangles) == set(chosen)), None)
                if value is None:
                    value = SupportCondition(kind, tuple(chosen), name=kind.replace("_", " ").title())
                    self.state.edit("Place Support", support_conditions=(*self.conditions, value))
            self.select_item("support", value.identifier)
        elif tool in ("force", "pressure"):
            current = next((v for v in self.loads if v.identifier == self._selection[1] and self._selection[0] == "load" and v.kind == tool), None)
            if additive and current:
                value = replace(current, triangles=tuple(sorted(set(current.triangles) | set(chosen))))
                self.state.edit("Extend Load", loads=tuple(value if v.identifier == value.identifier else v for v in self.loads))
            else:
                value = next((v for v in self.loads if v.kind == tool and set(v.triangles) == set(chosen)), None)
                if value is None:
                    value = SurfaceLoad(tuple(chosen), tool, (0., 0., 0.) if tool == "force" else (0.,), name="Face Force" if tool == "force" else "Face Pressure")
                    self.state.edit("Place Load", loads=(*self.loads, value))
            self.select_item("load", value.identifier)
        else:
            item = self.patch_list.item(index)
            selected = item.isSelected()
            if not additive:
                self.patch_list.clearSelection()
            item.setSelected(not selected if additive else True)

    def view_changed(self, text):
        self.viewport.display = text
        self.viewport.refresh()

    def material_changed(self, value):
        if not self._updating:
            self.state.edit("Change Material", material=value)

    def gravity_changed(self, *args):
        if not self._updating:
            self.state.edit("Change Gravity", gravity_enabled=self.gravity_on.isChecked(), gravity=tuple(w.value() for w in self.gravity_fields))

    def mesh_size_changed(self):
        if not self._updating:
            self.state.edit("Change Element Size", mesh_size=self.size.value())

    def mesh_settings(self):
        return MeshSettings(self.state.inputs.mesh_size, self.state.inputs.feature_angle)

    def refresh_view(self):
        self.viewport.supports = set(i for s in self.conditions for i in s.triangles)
        self.viewport.point_supports = tuple(v for v in self.conditions if v.kind == "fixed_point")
        self.viewport.pinned_faces = set(i for v in self.conditions if v.kind == "pinned_face" for i in v.triangles)
        self.viewport.loads = set(i for load in self.loads for i in load.triangles)
        self.viewport.surface_loads = tuple(self.loads)
        self.viewport.point_loads = tuple(self.point_loads)
        self.viewport.set_data(self.geometry, self.patches, self.mesh, self.result)

    def add_support(self):
        try:
            chosen = self.selected_triangles()
            value = next((v for v in self.conditions if v.kind == "fixed_face" and v.triangles == chosen), None)
            if value is None:
                value = SupportCondition("fixed_face", chosen, name="Fixed Face")
                self.state.edit("Fix Faces", support_conditions=(*self.conditions, value))
            self.select_item("support", value.identifier)
        except ValueError as error:
            self.error(error)

    def support_names(self):
        return tuple(v.name for v in self.conditions)

    def rename_support(self):
        if self._updating or self._renaming_support is None:
            return
        self.state.edit("Rename Support", support_conditions=tuple(replace(v, name=self.support_name.text().strip() or v.name) if v.identifier == self._renaming_support else v for v in self.conditions))

    def replace_support(self):
        if self._renaming_support is not None:
            try:
                self.state.edit("Reassign Support", support_conditions=tuple(replace(v, triangles=self.selected_triangles()) if v.identifier == self._renaming_support and v.kind != "fixed_point" else v for v in self.conditions))
            except ValueError as error:
                self.error(error)

    def change_support_kind(self):
        if self._updating or self._renaming_support is None:
            return
        kind = self.support_kind.currentData()
        if kind == "fixed_point":
            return
        self.state.edit("Change Support Type", support_conditions=tuple(replace(v, kind=kind) if v.identifier == self._renaming_support and v.kind != "fixed_point" else v for v in self.conditions))

    def reposition_support(self):
        if self._renaming_support:
            self._repositioning_support = self._renaming_support
            self.viewport.set_tool("fixed_point")
            self.tool_actions["fixed_point"].setChecked(True)
            self.statusBar().showMessage("Click the new fixed-point location. Escape exits placement.")

    def new_load(self, kind):
        self.selection_section.toggle.setChecked(kind != "point")
        self._editing_load = None
        self._draft_anchor = None
        self.load_name.clear()
        self.load_kind.setEnabled(True)
        self.load_kind.setCurrentIndex(self.load_kind.findData(kind))
        for field in self.force_fields:
            field.setValue(0.)
        self.pressure.setValue(0.)
        self._selection = ("loads", "")
        self.properties.setCurrentIndex(self.pages["loads"])
        self.load_kind_changed()
        if kind == "point":
            self.begin_point_placement()
        else:
            self.viewport.set_tool(kind)
        self.tool_actions[kind].setChecked(True)

    def load_kind_changed(self):
        if not hasattr(self, "force_row"):
            return
        kind = self.load_kind.currentData()
        pressure = kind == "pressure"
        for widget in (self.force_label, self.force_row):
            widget.setVisible(not pressure)
        for widget in (self.pressure_label, self.pressure_row, self.direction_label, self.pressure_direction):
            widget.setVisible(pressure)
        self.place_button.setVisible(kind == "point" and self._editing_load is not None)
        self.place_button.setText("Reposition Point…")
        if not self._editing_load and not self._updating:
            self.viewport.set_tool(kind)
        self.update_load_preview()

    def edit_load(self, load):
        was_updating = self._updating
        self._updating = True
        self._editing_load = load.identifier
        kind = "point" if isinstance(load, PointLoad) else load.kind
        self.load_kind.setCurrentIndex(self.load_kind.findData(kind))
        self.load_kind.setEnabled(False)
        self.load_name.setText(load.name)
        if kind == "point":
            self._draft_anchor = (load.source_triangle, load.barycentric)
            values = load.force
        elif kind == "force":
            values = load.value
            self.highlight_faces(load.triangles)
        else:
            values = (0., 0., 0.)
            self.pressure.setValue(abs(load.value[0])/self.pressure_units.currentData())
            self.pressure_direction.setCurrentIndex(0 if load.value[0] >= 0 else 1)
            self.highlight_faces(load.triangles)
        for field, value in zip(self.force_fields, values):
            field.setValue(value)
        self.load_kind_changed()
        self._updating = was_updating

    def begin_point_placement(self):
        if self.geometry is None:
            self.error("Import a solid first")
            return
        self._repositioning = self._editing_load is not None
        self.viewport.set_tool("point")
        self.tool_actions["point"].setChecked(True)
        self.update_load_preview()
        self.statusBar().showMessage("Click the solid to place a point force. Escape cancels placement.")

    def point_picked(self, triangle, barycentric):
        barycentric = tuple(barycentric)
        if self.viewport.tool == "fixed_point":
            reposition = getattr(self, "_repositioning_support", None)
            if reposition:
                value = next((v for v in self.conditions if v.identifier == reposition), None)
                self._repositioning_support = None
                if value:
                    value = replace(value, source_triangle=triangle, barycentric=barycentric)
                    self.state.edit("Move Fixed Point", support_conditions=tuple(value if v.identifier == reposition else v for v in self.conditions))
                    self.select_item("support", reposition)
                    return
            probe = SupportCondition("fixed_point", source_triangle=triangle, barycentric=barycentric, name="Fixed Point")
            position = point_position(self.geometry, probe)
            value = next((v for v in self.conditions if v.kind == "fixed_point" and np.linalg.norm(point_position(self.geometry, v)-position) < np.linalg.norm(self.geometry.dimensions)*1e-10), None)
            if value is None:
                value = probe
                self.state.edit("Place Fixed Point", support_conditions=(*self.conditions, value))
            self.select_item("support", value.identifier)
            return
        self._draft_anchor = (triangle, barycentric)
        if self._repositioning and self._editing_load:
            self.add_load()
            self._repositioning = False
            return
        probe = PointLoad(triangle, barycentric, (0., 0., 0.))
        position = point_position(self.geometry, probe)
        value = next((v for v in self.point_loads if np.linalg.norm(point_position(self.geometry, v)-position) < np.linalg.norm(self.geometry.dimensions)*1e-10), None)
        if value is None:
            value = probe
            self.state.edit("Place Point Force", point_loads=(*self.point_loads, value))
        self.select_item("point", value.identifier)
        self.statusBar().showMessage("Point force selected. Enter XYZ force in Properties; edits apply automatically.")

    def update_load_preview(self, *args):
        if not hasattr(self, "apply_load_button"):
            return
        kind = self.load_kind.currentData()
        force = tuple(field.value() for field in self.force_fields)
        self.viewport.preview_force = force
        self.viewport.draft_surface_load = None
        ready = self.geometry is not None
        if kind == "point":
            ready &= self._draft_anchor is not None and any(force)
            if self._draft_anchor and self.geometry:
                triangle, bary = self._draft_anchor
                preview = PointLoad(triangle, bary, force)
                position = point_position(self.geometry, preview)
                self.viewport.draft_point = position if self._repositioning else None
                location = ", ".join(f"{x:.6g}" for x in position)
                self.load_hint.setText(f"Point XYZ: {location} m. Force acts at this one point.")
            else:
                self.viewport.draft_point = None
                self.load_hint.setText("Click Place Point, then click a location on the solid.")
        else:
            self.viewport.draft_point = None
            ready &= bool(self.patch_list.selectedItems()) and (self.pressure.value() > 0 if kind == "pressure" else any(force))
            if not self._editing_load and self.viewport.tool in ("force", "pressure") and self.patch_list.selectedItems():
                value = force if kind == "force" else (self.pressure.value()*self.pressure_units.currentData()*(1 if self.pressure_direction.currentIndex() == 0 else -1),)
                self.viewport.draft_surface_load = SurfaceLoad(self.selected_triangles(), kind, value, identifier="draft", name="Preview")
            self.load_hint.setText("Pressure pushes perpendicular to each face; total force depends on area." if kind == "pressure" else "The total XYZ force is spread uniformly over all selected faces.")
        title = {"point": "Point Force", "force": "Face Force", "pressure": "Pressure"}[kind]
        self.apply_load_button.setText("Duplicate Load")
        self.apply_load_button.setEnabled(bool(self._editing_load))
        self.viewport.refresh()

    def add_load(self):
        try:
            kind = self.load_kind.currentData()
            name = self.load_name.text().strip() or {"point": "Point Force", "force": "Face Force", "pressure": "Face Pressure"}[kind]
            identity = {"identifier": self._editing_load} if self._editing_load else {}
            if kind == "point":
                if self._draft_anchor is None:
                    raise ValueError("Place the point on the solid first")
                load = PointLoad(*self._draft_anchor, tuple(w.value() for w in self.force_fields), name=name, **identity)
                values = [item for item in self.point_loads if item.identifier != load.identifier]
                values.append(load)
                self.state.edit("Update Point Force" if self._editing_load else "Add Point Force", point_loads=tuple(values))
                selected_kind = "point"
            else:
                chosen = self.selected_triangles()
                value = tuple(w.value() for w in self.force_fields) if kind == "force" else (self.pressure.value()*self.pressure_units.currentData()*(1 if self.pressure_direction.currentIndex() == 0 else -1),)
                load = SurfaceLoad(chosen, kind, value, name=name, **identity)
                values = [item for item in self.loads if item.identifier != load.identifier]
                values.append(load)
                self.state.edit("Update Face Load" if self._editing_load else "Add Face Load", loads=tuple(values))
                selected_kind = "load"
            self.select_item(selected_kind, load.identifier)
        except ValueError as error:
            self.error(error)

    def commit_load(self, *args):
        if not self._updating and self._editing_load:
            self.add_load()

    def pressure_unit_changed(self):
        if self._updating:
            return
        value = next((v for v in self.loads if v.identifier == self._editing_load and v.kind == "pressure"), None)
        if value:
            with QSignalBlocker(self.pressure):
                self.pressure.setValue(abs(value.value[0])/self.pressure_units.currentData())
        self.update_load_preview()

    def duplicate_load(self):
        value = next((v for v in (*self.loads, *self.point_loads) if v.identifier == self._editing_load), None)
        if value is None:
            return
        from uuid import uuid4
        value = replace(value, identifier=uuid4().hex, name=value.name+" Copy")
        key = "point_loads" if isinstance(value, PointLoad) else "loads"
        self.state.edit("Duplicate Load", **{key: (*getattr(self.state.inputs, key), value)})
        self.select_item("point" if isinstance(value, PointLoad) else "load", value.identifier)

    def cancel_placement(self):
        self._repositioning = False
        self._repositioning_support = None
        self.viewport.set_tool("select")
        self.viewport.draft_point = None
        self.viewport.hover_point = None
        self.viewport.draft_surface_load = None
        existing = next((v for v in (*self.loads, *self.point_loads) if v.identifier == self._editing_load), None)
        if existing is not None:
            self.edit_load(existing)
        else:
            self._draft_anchor = None
        self.tool_actions["select"].setChecked(True)
        self.update_load_preview()
        self.viewport.refresh()

    def remove_selected(self):
        kind, key = self._selection
        if kind == "support":
            self.state.edit("Delete Support", support_conditions=tuple(v for v in self.conditions if v.identifier != key))
        elif kind == "point":
            self.state.edit("Delete Point Force", point_loads=tuple(v for v in self.point_loads if v.identifier != key))
        elif kind == "load":
            self.state.edit("Delete Face Load", loads=tuple(v for v in self.loads if v.identifier != key))
        self._editing_load = None
        self._draft_anchor = None
        self.cancel_placement()
        self.select_item("loads" if kind in ("load", "point") else "supports")

    def set_beam_end(self, clamp):
        try:
            chosen = self.selected_triangles()
            self.state.edit("Assign Beam End", **({"beam_clamp": chosen} if clamp else {"beam_free": chosen}))
        except ValueError as error:
            self.error(error)

    def clear_beam(self):
        self.state.edit("Clear Beam Configuration", beam_clamp=None, beam_free=None)

    def frame_selected(self):
        kind, key = self._selection
        if kind == "support" and self.geometry:
            support = next((v for v in self.conditions if v.identifier == key and v.kind == "fixed_point"), None)
            if support:
                self.viewport.frame_point(point_position(self.geometry, support))
                return
        if kind == "point" and self.geometry:
            load = next((v for v in self.point_loads if v.identifier == key), None)
            if load:
                self.viewport.frame_point(point_position(self.geometry, load))
                return
        self.viewport.frame_all()

    def setup(self):
        if self.geometry is None:
            raise ValueError("Import a solid first")
        inputs = self.state.inputs
        value = inputs.material
        if value is None or value.young_modulus is None or value.poisson_ratio is None:
            raise ValueError("Choose a material preset or complete the Custom material properties")
        material = Material(value.young_modulus, value.poisson_ratio, value.density, value.name, value.preset_id)
        gravity = inputs.gravity if inputs.gravity_enabled else (0., 0., 0.)
        if bool(inputs.beam_clamp) != bool(inputs.beam_free):
            raise ValueError("Select both beam ends, or clear the beam configuration")
        beam = BeamConfiguration(inputs.beam_clamp, inputs.beam_free) if inputs.beam_clamp else None
        return AnalysisSetup(self.geometry.path, self.geometry.fingerprint, self.geometry.units, material,
            self.mesh_settings(), inputs.supports, inputs.loads, gravity, beam, inputs.point_loads, inputs.support_names, inputs.support_conditions)

    def confirm_unsaved(self, title):
        if not self.dirty:
            return True
        answer = QMessageBox.question(self, title, "Save changes to this structural design?",
            QMessageBox.StandardButton.Save | QMessageBox.StandardButton.Discard | QMessageBox.StandardButton.Cancel,
            QMessageBox.StandardButton.Save)
        if answer == QMessageBox.StandardButton.Cancel:
            return False
        return self.save() if answer == QMessageBox.StandardButton.Save else True

    def new_analysis(self):
        if not self.confirm_unsaved("New Structural Analysis"):
            return
        self._readiness_cache = None
        self.job.invalidate()
        self.geometry = self.mesh = self.result = None
        self.patches = ()
        self.patch_list.clear()
        self.analysis_path = None
        self._geometry_dirty = False
        self.state.reset(StructuralInputs())
        self.summary.setText("Import one closed .simuOPart, OBJ or STL solid.")
        self.select_item("solid")

    def import_geometry(self):
        path, _ = QFileDialog.getOpenFileName(self, "Import Solid", "", "Solids (*.simuOPart *.obj *.OBJ *.stl *.STL)")
        if path and self.confirm_unsaved("Import Solid"):
            self.analysis_path = None
            self.prepare_geometry(path)

    def units_changed(self, *args):
        if not self._updating and self.geometry:
            self.prepare_geometry(self.geometry.path, units=self.units.currentText())

    def prepare_geometry(self, path, setup=None, units=None):
        self._readiness_cache = None
        self.job.invalidate()
        self.geometry = self.mesh = self.result = None
        self.patches = ()
        self.pending_setup = setup
        self.pending_geometry_path = str(path)
        self._pending_units = setup.units if setup else units or self.units.currentText()
        if Path(path).suffix.lower() == ".simuopart":
            try:
                if Path(path).read_text(encoding="utf-8-sig").lstrip().startswith(("{", "[")):
                    self._pending_units = "m"
            except OSError:
                pass
        self.patch_list.clear()
        self.diagram.result = None
        self.diagram.update()
        self.summary.setText(f"Importing {Path(path).name}…")
        self.report.setText("Importing geometry; results will be regenerated.")
        self.refresh_view()
        self.start_job("prepare", str(path), self._pending_units, setup.mesh if setup else self.mesh_settings())

    def open_analysis(self):
        path, _ = QFileDialog.getOpenFileName(self, "Open SimuO Project", "", PROJECT_FILTER)
        if path:
            self.open_path(path)

    def open_path(self, path):
        try:
            if Path(path).suffix.lower() in (".simuo", ".simuoanalysis"):
                document = read_project(path)
                if document.project_type == "scene":
                    from simuo.ui.project_open import open_project_window
                    open_project_window(path, self)
                    return
                setup = load_analysis(path)
                if not self.confirm_unsaved("Open Project"):
                    return
                self.analysis_path = str(path)
                self.prepare_geometry(setup.geometry_path, setup)
            elif self.confirm_unsaved("Import Solid"):
                self.prepare_geometry(path)
        except (OSError, ValueError, TypeError) as error:
            self.error(error)

    def save(self, checked=False, save_as=False):
        try:
            setup = self.setup()
            path = self.analysis_path
            if save_as or not path or Path(path).suffix.lower() != ".simuo":
                suggestion = str(Path(path).with_suffix(".simuO")) if path else "analysis.simuO"
                path, _ = QFileDialog.getSaveFileName(self, "Save SimuO Project", suggestion, "SimuO Projects (*.simuO)")
                if not path:
                    return False
                path = str(Path(path).with_suffix(".simuO"))
            save_analysis(path, setup)
            self.analysis_path = path
            self._geometry_dirty = False
            self.state.undo_stack.setClean()
            record_saved_project(path, self.viewport)
            self.update_title()
            self.statusBar().showMessage(f"Saved {path}")
            return True
        except (OSError, ValueError) as error:
            self.error(error)
            return False

    def required_points(self):
        return (*self.point_loads, *(v for v in self.conditions if v.kind == "fixed_point"))

    def mesh_current(self):
        if self.mesh is None or self.geometry is None or self.mesh.settings != self.mesh_settings() or self.mesh.geometry_fingerprint != self.geometry.fingerprint:
            return False
        try:
            bind_point_targets(self.mesh, self.required_points(), self.geometry)
            return True
        except ValueError:
            return False

    def solve_reason(self):
        try:
            setup = self.setup()
            if not self.mesh_current():
                return "Mesh update required. Choose Generate Mesh, then Run Analysis."
            cache_key = (id(self.mesh), setup.supports, setup.support_conditions, tuple((v.source_triangle, v.barycentric, v.identifier) for v in setup.point_loads))
            if self._readiness_cache is None or self._readiness_cache[0] != cache_key:
                self._readiness_cache = (cache_key, restraint_reason(self.geometry, setup))
            return self._readiness_cache[1]
        except ValueError as error:
            return str(error)

    def update_actions(self):
        busy = self.job.running
        reason = "Analysis is busy" if busy else self.solve_reason()
        self.solve_action.setEnabled(not reason)
        self.solve_action.setToolTip(reason or "Solve using the current mesh")
        current = self.mesh_current()
        self.generate_action.setEnabled(self.geometry is not None and not busy and not current)
        self.generate_action.setToolTip("Mesh is up to date" if current else "Generate the tetrahedral mesh without running analysis")
        self.readiness.setText(reason or "Ready to run analysis with the current mesh.")

    def stress_scale_changed(self):
        self.viewport.display_maximum = self.stress_max.value() if self.stress_range.currentIndex() == 1 else None
        self.viewport.refresh()

    def generate_mesh(self):
        if self.geometry is None:
            self.error("Import a solid first")
            return
        if self.mesh_current():
            return
        self.mesh_size_changed()
        self.mesh = self.result = None
        self.diagram.result = None
        self.diagram.update()
        self.refresh_view()
        self.start_job("mesh", self.geometry, self.mesh_settings(), self.required_points())

    def solve(self):
        reason = self.solve_reason()
        if reason:
            self.statusBar().showMessage(reason)
            self.update_actions()
            return
        self.start_job("solve", self.mesh, self.setup())

    def start_job(self, operation, *arguments):
        self.progress.setRange(0, 0)
        self.statusBar().showMessage(f"Starting {operation}…")
        try:
            self.job.start(operation, *arguments)
            self.update_actions()
        except (OSError, RuntimeError) as error:
            self.error(error)

    def cancel(self):
        self.job.invalidate()
        self.update_actions()
        self.progress.setRange(0, 1)
        self.statusBar().showMessage("Cancelled")

    def poll_job(self):
        operation = self.job.operation
        for kind, value in self.job.poll():
            if kind == "progress":
                self.statusBar().showMessage(value)
            elif kind == "error":
                self.error(value)
            elif kind == "result":
                if operation == "prepare":
                    self.geometry, self.patches = value
                    self.apply_prepared_geometry()
                elif operation == "mesh":
                    if self.geometry is None or value.geometry_fingerprint != self.geometry.fingerprint or value.settings != self.mesh_settings():
                        continue
                    try:
                        bind_point_targets(value, self.required_points(), self.geometry)
                    except ValueError:
                        continue
                    self.mesh = value
                    self._readiness_cache = None
                    self.view_mode.setCurrentText("Mesh")
                    self.statusBar().showMessage(f"Mesh: {len(value.points)} vertices, {len(value.tetrahedra)} tetrahedra")
                    self.rebuild_tree()
                elif operation == "solve":
                    self.result = value
                    self.view_mode.setCurrentText("Stress")
                    self.diagram.result = value
                    self.diagram.update()
                    note = "\nStress at an ideal point force is singular and may increase with mesh refinement." if self.point_loads else ""
                    self.report.setText(f"Peak displacement: {np.linalg.norm(value.displacement, axis=1).max():.6g} m\nUnaveraged peak von Mises: {value.von_mises.max():.6g} Pa\nResidual / force / moment errors: {value.residual_error:.3g} / {value.force_error:.3g} / {value.moment_error:.3g}\nReaction XYZ (N), moment XYZ (N·m): {np.array2string(value.root_reaction, precision=5)}\n{value.beam_message}{note}")
                    reactions = "\n".join(f"{next((s.name for s in self.conditions if s.identifier == key), key)}: F {np.array2string(data['force'], precision=5)} N; M {np.array2string(data['moment'], precision=5)} N·m" for key, data in value.support_reactions.items())
                    self.report.setText(self.report.text()+"\nSupport reactions about each support origin:\n"+reactions)
                    self.panel_manager.docks["analysis_results"].show()
                    self.statusBar().showMessage("Analysis complete")
                self.refresh_view()
        if not self.job.running:
            self.progress.setRange(0, 1)
            self.progress.setValue(1)
        self.update_actions()

    def apply_prepared_geometry(self):
        setup = self.pending_setup
        self.patch_list.clear()
        for patch in self.patches:
            self.patch_list.addItem(patch.label)
        try:
            if setup:
                selections = [v.triangles for v in all_supports(setup) if v.kind != "fixed_point"]+[load.triangles for load in setup.loads]
                if setup.beam:
                    selections += [setup.beam.clamp, setup.beam.free_end]
                for chosen in selections:
                    members = set()
                    for patch in self.patches:
                        if set(patch.triangles) & set(chosen):
                            if not set(patch.triangles) <= set(chosen):
                                raise ValueError("Surface reconstruction changed; reassign boundaries")
                            members.update(patch.triangles)
                    if members != set(chosen):
                        raise ValueError("Surface reconstruction changed; reassign boundaries")
                for load in point_targets(setup):
                    point_position(self.geometry, load)
                value = setup.material
                inputs = StructuralInputs(material=MaterialDefinition(value.name, value.young_modulus, value.poisson_ratio, value.density, value.preset_id),
                    support_conditions=all_supports(setup), loads=setup.loads, point_loads=setup.point_loads,
                    mesh_size=setup.mesh.target_size, feature_angle=setup.mesh.feature_angle, units=setup.units,
                    gravity_enabled=any(setup.gravity), gravity=setup.gravity if any(setup.gravity) else (0., -9.80665, 0.),
                    beam_clamp=setup.beam.clamp if setup.beam else None, beam_free=setup.beam.free_end if setup.beam else None)
            else:
                inputs = StructuralInputs(material=self.state.inputs.material, mesh_size=float(max(self.geometry.dimensions)/8), units=self.geometry.units)
            self._geometry_dirty = setup is None
            self.state.reset(inputs)
            if setup:
                remember_project(self.analysis_path)
            g = self.geometry
            self.summary.setText(f"{Path(g.path).name}\nDimensions: {' × '.join(f'{x:.6g}' for x in g.dimensions)} m\nVolume: {g.volume:.6g} m³ · {len(self.patches)} faces")
            self.view_mode.setCurrentText("Setup")
            self.viewport.frame_all()
            self.cancel_placement()
            self.select_item("material")
        except ValueError as error:
            self.state.reset(StructuralInputs(units=self.geometry.units))
            self._geometry_dirty = True
            self.error(error)
        finally:
            self.pending_setup = None

    def closeEvent(self, event):
        if not self.confirm_unsaved("Close Structural Analysis"):
            event.ignore()
            return
        self.timer.stop()
        self.job.cancel()
        self.panel_manager.save_layout()
        super().closeEvent(event)


def run_structural(path=None):
    from simuo.rendering.context import configure_opengl
    configure_opengl()
    app = QApplication.instance() or QApplication(sys.argv)
    window = StructuralWindow(path)
    window.show()
    return app.exec()
