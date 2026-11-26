"""One Material section used by both Scene and Structural properties panels."""
from dataclasses import replace
from pathlib import Path
from weakref import WeakSet
from shiboken6 import isValid
from PySide6.QtCore import Signal, QSignalBlocker, QStandardPaths
from PySide6.QtWidgets import QComboBox, QLabel, QLineEdit, QPushButton, QStyleFactory, QAbstractSpinBox, QFileDialog, QMessageBox

from simuo.materials import (MaterialDefinition, MaterialRecord, MaterialCatalog,
    save_material, inherited_material)
from simuo.ui.panels.properties import InspectorSection, TransformSpinBox, inspector_grid, numeric_frame


_INSPECTORS = WeakSet()
MATERIAL_FILTER = "Material JSON (*.json)"


class MaterialInspector(InspectorSection):
    material_changed = Signal(object)  # None means inherit the source part.

    def __init__(self, catalog=None):
        super().__init__("Material", self.reset_material, "Restore the part's material")
        self.catalog = catalog if catalog is not None else MaterialCatalog(
            Path(QStandardPaths.writableLocation(QStandardPaths.GenericDataLocation))/"SimuO"/"materials")
        _INSPECTORS.add(self)
        self.assignment = None
        self.inherited = inherited_material()
        self._updating = False
        grid = inspector_grid(self)
        self.combo = QComboBox()
        self.combo.setObjectName("inspectorCombo")
        self._combo_style = QStyleFactory.create("Fusion")
        self._combo_style.setParent(self.combo)
        self.combo.setStyle(self._combo_style)
        self.combo.setMinimumHeight(26)
        self.combo.setAccessibleName("Material")
        grid.addWidget(QLabel("Material"), 0, 0)
        grid.addWidget(self.combo, 0, 1, 1, 3)
        self.name = QLineEdit()
        self.name.setAccessibleName("Custom material name")
        self.name.setPlaceholderText("Custom material name")
        grid.addWidget(self.name, 1, 0, 1, 4)
        self.young, self.poisson, self.density = TransformSpinBox(), TransformSpinBox(), TransformSpinBox()
        self.yield_strength, self.ultimate_tensile_strength = TransformSpinBox(), TransformSpinBox()
        for row, (label, control, maximum, decimals) in enumerate((
            ("Modulus (GPa)", self.young, 1e9, 12),
            ("Poisson ratio", self.poisson, .499999, 6),
            ("Density (kg/m³)", self.density, 1e12, 6),
            ("Yield strength (MPa)", self.yield_strength, 1e9, 6),
            ("UTS (MPa)", self.ultimate_tensile_strength, 1e9, 6)), 2):
            control.setDecimals(decimals)
            control.setRange(-1. if control is self.poisson else 0., maximum)
            control.setKeyboardTracking(False)
            control.setButtonSymbols(QAbstractSpinBox.ButtonSymbols.NoButtons)
            control.setAccessibleName(label)
            control.setSpecialValueText("Not supplied")
            grid.addWidget(QLabel(label), row, 0)
            grid.addWidget(numeric_frame(control), row, 1, 1, 3)
            control.editingFinished.connect(self._custom_changed)
        self.edit_button = QPushButton("Edit as Custom")
        self.edit_button.setObjectName("inspectorReset")
        self.edit_button.clicked.connect(self.edit_as_custom)
        grid.addWidget(self.edit_button, 7, 0, 1, 4)
        self.hint = QLabel()
        self.hint.setWordWrap(True)
        grid.addWidget(self.hint, 8, 0, 1, 4)
        self.save_button = QPushButton("Save to Library")
        self.save_button.clicked.connect(self.save_to_library)
        grid.addWidget(self.save_button, 9, 0, 1, 4)
        self.import_button = QPushButton("Import Material…")
        self.import_button.clicked.connect(self.import_material)
        self.export_button = QPushButton("Export Material…")
        self.export_button.clicked.connect(self.export_material)
        grid.addWidget(self.import_button, 10, 0, 1, 2)
        grid.addWidget(self.export_button, 10, 2, 1, 2)
        self.combo.currentIndexChanged.connect(self._selected)
        self.name.editingFinished.connect(self._custom_changed)
        self.reload_catalog()

    def set_material(self, assignment, inherited=None):
        self._updating = True
        try:
            self.assignment = assignment
            if inherited is not None:
                self.inherited = inherited
            value = assignment or self.inherited
            record = self.catalog.get(value.preset_id)
            preset_matches = record is not None and record.material == value
            key = None if assignment is None else value.preset_id if preset_matches else "custom"
            with QSignalBlocker(self.combo):
                self.combo.setCurrentIndex(self.combo.findData(key))
            self.name.setText(value.name)
            self.young.setValue(value.young_modulus/1e9 if value.young_modulus is not None else 0)
            self.poisson.setValue(value.poisson_ratio if value.poisson_ratio is not None else -1.)
            self.density.setValue(value.density or 0)
            self.yield_strength.setValue((value.yield_strength or 0)/1e6)
            self.ultimate_tensile_strength.setValue((value.ultimate_tensile_strength or 0)/1e6)
            custom = key == "custom"
            self.name.setVisible(custom)
            for control in (self.young, self.poisson, self.density, self.yield_strength, self.ultimate_tensile_strength):
                control.setReadOnly(not custom)
            self.edit_button.setVisible(not custom)
            self.save_button.setVisible(custom)
            self.hint.setToolTip("")
            if assignment is None:
                self.hint.setText("Inherited from the source part. Choose a material to supply elastic properties.")
            elif record is not None and preset_matches:
                self.hint.setToolTip("\n".join(filter(None, (record.source_url, record.strength_source_url))))
                description = "Personal library material. " if value.preset_id.startswith("user:") else "Room-temperature reference properties. "
                self.hint.setText(description+"Saved values are preserved when reopened. "+(record.strength_notes or ""))
            else:
                self.hint.setText("Custom isotropic material. Strengths are optional; zero means not supplied.")
        finally:
            self._updating = False

    def _selected(self):
        if self._updating:
            return
        key = self.combo.currentData()
        if key == "custom":
            self.edit_as_custom()
            return
        record = self.catalog.get(key)
        value = record.material if record is not None else None
        self.set_material(value)
        self.material_changed.emit(value)

    def edit_as_custom(self):
        value = replace(self.assignment or self.inherited, preset_id=None)
        if value.name == "From Part":
            value = replace(value, name="Custom")
        self.set_material(value)
        self.material_changed.emit(value)

    def _custom_changed(self):
        if self._updating or self.combo.currentData() != "custom":
            return
        try:
            value = self._read_custom()
        except ValueError as error:
            self.hint.setText(str(error))
            return
        self.hint.setText("Custom isotropic material. Strengths are optional; zero means not supplied.")
        if value != self.assignment:
            self.assignment = value
            self.material_changed.emit(value)

    def _read_custom(self):
        values = {}
        for name, control, scale in (("young_modulus", self.young, 1e9),
                                     ("poisson_ratio", self.poisson, 1.),
                                     ("density", self.density, 1.),
                                     ("yield_strength", self.yield_strength, 1e6),
                                     ("ultimate_tensile_strength", self.ultimate_tensile_strength, 1e6)):
            displayed = control.value()
            supplied = displayed > -1 if name == "poisson_ratio" else displayed > 0
            value = displayed*scale if supplied else None
            original = getattr(self.assignment, name, None)
            # Editing another field must not round the stored strength to the
            # precision of its MPa display.
            if original is not None and displayed == round(original/scale, control.decimals()):
                value = original
            values[name] = value
        return MaterialDefinition(self.name.text().strip() or "Custom", **values)

    def reload_catalog(self):
        self.catalog.reload()
        with QSignalBlocker(self.combo):
            self.combo.clear()
            self.combo.addItem("From Part", None)
            for record in self.catalog.records.values():
                self.combo.addItem(record.material.name, record.material.preset_id)
            self.combo.addItem("Custom", "custom")
        self.set_material(self.assignment)
        if self.catalog.errors:
            self.hint.setText("Some personal materials could not be loaded. "+"; ".join(self.catalog.errors))

    def _notify_library_changed(self):
        for inspector in list(_INSPECTORS):
            if isValid(inspector) and inspector.catalog.directory == self.catalog.directory:
                inspector.reload_catalog()

    def _current_record(self):
        value = self._read_custom() if self.combo.currentData() == "custom" else self.assignment or self.inherited
        record = self.catalog.get(value.preset_id)
        return record if record is not None and record.material == value else MaterialRecord(value)

    def _file_error(self, error):
        QMessageBox.warning(self, "Material", str(error))

    def save_to_library(self):
        try:
            if not self.name.text().strip():
                raise ValueError("Enter a material name before saving")
            record = self._current_record()
            self.catalog.reload()
            existing = self.catalog.named(record.material.name)
            replace_id = None
            if existing:
                dialog = QMessageBox(self)
                dialog.setWindowTitle("Save Material")
                dialog.setText("A personal material with this name already exists.")
                replace_button = dialog.addButton("Replace Existing", QMessageBox.AcceptRole)
                copy_button = dialog.addButton("Save a Copy", QMessageBox.ActionRole)
                dialog.addButton(QMessageBox.Cancel)
                dialog.exec()
                if dialog.clickedButton() == replace_button:
                    replace_id = existing
                elif dialog.clickedButton() != copy_button:
                    return
            saved = self.catalog.save(record, replace_id=replace_id)
            self._notify_library_changed()
            self.hint.setText(f"Saved {saved.material.name} to your material library.")
        except (OSError, ValueError) as error:
            self._file_error(error)

    def import_material(self):
        path, _ = QFileDialog.getOpenFileName(self, "Import Material", "", MATERIAL_FILTER)
        if not path:
            return
        try:
            record = self.catalog.import_file(path)
            self._notify_library_changed()
            self.hint.setText(f"{record.material.name} is available in the material library.")
        except (OSError, ValueError) as error:
            self._file_error(error)

    def export_material(self):
        try:
            record = self._current_record()
            path, _ = QFileDialog.getSaveFileName(self, "Export Material", record.material.name+".json", MATERIAL_FILTER)
            if not path:
                return
            destination = str(Path(path).with_suffix(".json"))
            if destination != path and Path(destination).exists():
                answer = QMessageBox.question(self, "Export Material", f"Replace {destination}?",
                    QMessageBox.Yes | QMessageBox.No, QMessageBox.No)
                if answer != QMessageBox.Yes:
                    return
            path = destination
            save_material(path, record)
            self.hint.setText(f"Exported material to {path}")
        except (OSError, ValueError) as error:
            self._file_error(error)

    def reset_material(self):
        self.set_material(None)
        self.material_changed.emit(None)
