"""One Material section used by both Scene and Structural properties panels."""
from dataclasses import replace
from PySide6.QtCore import Signal, QSignalBlocker
from PySide6.QtWidgets import QComboBox, QDoubleSpinBox, QLabel, QLineEdit, QPushButton, QStyleFactory, QAbstractSpinBox

from simuo.materials import MaterialDefinition, PRESETS, MATERIAL_PRESETS, PRESET_SOURCES, inherited_material
from simuo.ui.panels.properties import InspectorSection, TransformSpinBox, inspector_grid, numeric_frame


class MaterialInspector(InspectorSection):
    material_changed = Signal(object)  # None means inherit the source part.

    def __init__(self):
        super().__init__("Material", self.reset_material, "Restore the part's material")
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
        self.combo.addItem("From Part", None)
        for preset in PRESETS:
            self.combo.addItem(preset.name, preset.preset_id)
        self.combo.addItem("Custom", "custom")
        grid.addWidget(QLabel("Material"), 0, 0)
        grid.addWidget(self.combo, 0, 1, 1, 3)
        self.name = QLineEdit()
        self.name.setAccessibleName("Custom material name")
        self.name.setPlaceholderText("Custom material name")
        grid.addWidget(self.name, 1, 0, 1, 4)
        self.young, self.poisson, self.density = TransformSpinBox(), TransformSpinBox(), TransformSpinBox()
        for row, (label, control, maximum, decimals) in enumerate((
            ("Modulus (GPa)", self.young, 1e9, 12),
            ("Poisson ratio", self.poisson, .499999, 6),
            ("Density (kg/m³)", self.density, 1e12, 6)), 2):
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
        grid.addWidget(self.edit_button, 5, 0, 1, 4)
        self.hint = QLabel()
        self.hint.setWordWrap(True)
        grid.addWidget(self.hint, 6, 0, 1, 4)
        self.combo.currentIndexChanged.connect(self._selected)
        self.name.editingFinished.connect(self._custom_changed)
        self.set_material(None)

    def set_material(self, assignment, inherited=None):
        self._updating = True
        try:
            self.assignment = assignment
            if inherited is not None:
                self.inherited = inherited
            value = assignment or self.inherited
            preset_matches = value.preset_id in MATERIAL_PRESETS and MATERIAL_PRESETS[value.preset_id] == value
            key = None if assignment is None else value.preset_id if preset_matches else "custom"
            with QSignalBlocker(self.combo):
                self.combo.setCurrentIndex(self.combo.findData(key))
            self.name.setText(value.name)
            self.young.setValue(value.young_modulus/1e9 if value.young_modulus is not None else 0)
            self.poisson.setValue(value.poisson_ratio if value.poisson_ratio is not None else -1.)
            self.density.setValue(value.density or 0)
            custom = key == "custom"
            self.name.setVisible(custom)
            for control in (self.young, self.poisson, self.density):
                control.setReadOnly(not custom)
            self.edit_button.setVisible(not custom)
            if assignment is None:
                self.hint.setText("Inherited from the source part. Choose a material to supply elastic properties.")
            elif value.preset_id:
                self.hint.setToolTip(PRESET_SOURCES.get(value.preset_id, "Saved material snapshot"))
                self.hint.setText("Typical room-temperature properties. Saved values are preserved when reopened.")
            else:
                self.hint.setText("Custom isotropic material. Enter modulus, Poisson ratio and density.")
        finally:
            self._updating = False

    def _selected(self):
        if self._updating:
            return
        key = self.combo.currentData()
        if key == "custom":
            self.edit_as_custom()
            return
        value = MATERIAL_PRESETS.get(key)
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
        value = MaterialDefinition(self.name.text().strip() or "Custom",
                                   self.young.value()*1e9 if self.young.value() else None,
                                   self.poisson.value() if self.young.value() and self.poisson.value() > -1 else None,
                                   self.density.value() or None)
        if value != self.assignment:
            self.assignment = value
            self.material_changed.emit(value)

    def reset_material(self):
        self.set_material(None)
        self.material_changed.emit(None)
