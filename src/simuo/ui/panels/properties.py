"""Object hierarchy and transform inspector backed by shared editor state."""

from pathlib import Path

from PySide6.QtCore import QEvent, QSignalBlocker, QSize, Qt
from PySide6.QtWidgets import (
    QDoubleSpinBox,
    QAbstractSpinBox,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QScrollArea,
    QSizePolicy,
    QStackedWidget,
    QVBoxLayout,
    QWidget,
)

from simuo.ui.theme import load_stylesheet


class TransformSpinBox(QDoubleSpinBox):
    """Compact numeric display without accidental edits while scrolling panels."""

    def __init__(self):
        super().__init__()
        self.mixed = False
        self.typed = False
        self.lineEdit().textEdited.connect(self._typed)

    def _typed(self, text):
        self.typed = True

    def set_mixed(self, mixed):
        self.mixed = mixed
        self.typed = False
        self.lineEdit().setText(self.prefix() + self.textFromValue(self.value()))

    def textFromValue(self, value):
        if getattr(self, "mixed", False):
            return "—"
        text = super().textFromValue(value)
        decimal = self.locale().decimalPoint()
        if decimal in text:
            text = text.rstrip(self.locale().zeroDigit()).removesuffix(decimal)
        return text

    def wheelEvent(self, event):
        if self.hasFocus():
            super().wheelEvent(event)
        else:
            event.ignore()


class InspectorSection(QWidget):
    """A collapsible component section with an optional, explicit reset action."""

    def __init__(self, title, reset=None):
        super().__init__()
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)
        self.header = QWidget()
        self.header.setObjectName("sectionHeader")
        self.header.setFixedHeight(32)
        header = QHBoxLayout(self.header)
        header.setContentsMargins(0, 0, 8, 0)
        header.setSpacing(6)
        self.toggle = QPushButton(f"▾  {title}")
        self.toggle.setObjectName("sectionToggle")
        self.toggle.setCheckable(True)
        self.toggle.setChecked(True)
        header.addWidget(self.toggle, 1)
        self.reset_button = None
        if reset is not None:
            self.reset_button = button = QPushButton("Reset")
            button.setObjectName("inspectorReset")
            button.setFixedHeight(22)
            button.setAccessibleName("Reset transform")
            button.setToolTip("Reset position and rotation to zero, and scale to one")
            button.clicked.connect(reset)
            header.addWidget(button)
        layout.addWidget(self.header)
        self.body = QWidget()
        self.body.setObjectName("sectionBody")
        layout.addWidget(self.body)
        self.toggle.toggled.connect(self.body.setVisible)
        self.toggle.toggled.connect(lambda expanded: self.toggle.setText(f"{'▾' if expanded else '▸'}  {title}"))


class PropertiesPanel(QWidget):
    def __init__(self, state):
        super().__init__()
        self.state = state
        self._displayed_id = None
        self._displayed_ids = ()
        self.setObjectName("editorPanel")
        self.setMinimumSize(260, 120)
        self.setStyleSheet(load_stylesheet("properties"))
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        self.stack = QStackedWidget()
        empty = QLabel("Nothing selected\n\nClick an object in the viewport\nor Object Hierarchy to inspect it.")
        empty.setObjectName("inspectorHint")
        empty.setAlignment(Qt.AlignmentFlag.AlignCenter)
        empty.setWordWrap(True)
        self.stack.addWidget(empty)

        self.scroll = QScrollArea()
        self.scroll.setWidgetResizable(True)
        self.scroll.setFrameShape(QScrollArea.Shape.NoFrame)
        self.scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        content = QWidget()
        content.setObjectName("editorPanel")
        form = QVBoxLayout(content)
        form.setContentsMargins(0, 0, 0, 0)
        form.setSpacing(6)

        header = QWidget()
        header.setObjectName("inspectorHeader")
        header_layout = QVBoxLayout(header)
        header_layout.setContentsMargins(10, 10, 10, 10)
        header_layout.setSpacing(4)
        self.name_input = QLineEdit()
        self.name_input.setObjectName("objectName")
        self.name_input.setAccessibleName("Object name")
        self.name_input.setPlaceholderText("Object name")
        self.name_input.setToolTip("Rename the selected object")
        self.name_input.installEventFilter(self)
        self.name_input.editingFinished.connect(self._rename)
        header_layout.addWidget(self.name_input)
        self.selection_hint = QLabel()
        self.selection_hint.setWordWrap(True)
        header_layout.addWidget(self.selection_hint)
        form.addWidget(header)

        self.transform_section = InspectorSection(
            "Transform", lambda: state.reset_transforms(self._displayed_ids)
        )
        rows = QGridLayout(self.transform_section.body)
        rows.setContentsMargins(10, 10, 8, 10)
        rows.setHorizontalSpacing(4)
        rows.setVerticalSpacing(6)
        self.transform_inputs = {}
        self.reset_buttons = {}
        for row, (attribute, title) in enumerate((("position", "Position"), ("rotation", "Rotation"), ("scale", "Scale"))):
            label = QLabel(title)
            label.setToolTip("Euler angles in degrees" if attribute == "rotation" else title)
            rows.addWidget(label, row, 0)
            inputs = []
            for axis, axis_name in enumerate(("X", "Y", "Z")):
                field = TransformSpinBox()
                field.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
                field.setProperty("axis", axis_name)
                field.setRange(-1_000_000.0, 1_000_000.0)
                field.setDecimals(3)
                field.setSingleStep(1.0 if attribute == "rotation" else 0.1)
                field.setKeyboardTracking(False)
                field.setButtonSymbols(QAbstractSpinBox.ButtonSymbols.NoButtons)
                field.setPrefix(f"{axis_name} ")
                field.setMinimumWidth(40)
                field.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Fixed)
                field.setAccessibleName(f"{title} {axis_name}")
                field.setToolTip(f"{title} {axis_name}" + (" (degrees)" if attribute == "rotation" else ""))
                field.valueChanged.connect(
                    lambda value, a=attribute, i=axis: self.state.set_transform_components(
                        self._displayed_ids, a, i, value
                    )
                )
                field.editingFinished.connect(
                    lambda field=field, a=attribute, i=axis: self._commit_mixed(field, a, i)
                )
                rows.addWidget(field, row, axis + 1)
                inputs.append(field)
            self.transform_inputs[attribute] = inputs
            reset = QPushButton("↺")
            reset.setObjectName("inspectorReset")
            reset.setFixedWidth(23)
            reset.setToolTip(f"Reset {title.lower()}")
            reset.setAccessibleName(f"Reset {title.lower()}")
            reset.clicked.connect(lambda checked=False, a=attribute: state.reset_transforms(self._displayed_ids, a))
            rows.addWidget(reset, row, 4)
            self.reset_buttons[attribute] = reset
        for column in (1, 2, 3):
            rows.setColumnStretch(column, 1)
        form.addWidget(self.transform_section)

        self.mesh_section = InspectorSection("Mesh")
        mesh_layout = QVBoxLayout(self.mesh_section.body)
        mesh_layout.setContentsMargins(10, 10, 10, 10)
        mesh_layout.setSpacing(4)
        mesh_layout.addWidget(QLabel("Source asset"))
        self.mesh_name = QLabel()
        self.mesh_name.setTextFormat(Qt.TextFormat.PlainText)
        self.mesh_name.setMinimumWidth(0)
        self.mesh_name.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred)
        self.mesh_name.setWordWrap(True)
        self.mesh_name.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        mesh_layout.addWidget(self.mesh_name)
        form.addWidget(self.mesh_section)
        form.addStretch()
        self.scroll.setWidget(content)
        self.stack.addWidget(self.scroll)
        layout.addWidget(self.stack)
        state.selection_changed.connect(self._show_object)
        state.object_changed.connect(self._object_changed)
        self._show_object(state.selected_object)

    def sizeHint(self):
        return QSize(340, 400)

    def eventFilter(self, watched, event):
        if watched is self.name_input and event.type() == QEvent.Type.KeyPress and event.key() == Qt.Key.Key_Escape:
            obj = self.state.find_object(self._displayed_id)
            if obj is not None:
                with QSignalBlocker(self.name_input):
                    self.name_input.setText(obj.name)
                self.name_input.selectAll()
            return True
        return super().eventFilter(watched, event)

    def _show_object(self, obj):
        self._displayed_id = obj.identifier if obj is not None else None
        self._displayed_ids = self.state.selected_ids
        selected = self.state.selected_objects
        multiple = len(selected) > 1
        self.stack.setCurrentIndex(1 if obj is not None else 0)
        self.scroll.setEnabled(obj is not None)
        with QSignalBlocker(self.name_input):
            self.name_input.setText(f"{len(selected)} objects selected" if multiple else obj.name if obj is not None else "")
        self.name_input.setEnabled(not multiple)
        self.selection_hint.setVisible(multiple)
        self.selection_hint.setText("Transform edits apply to all selected objects. A dash marks different values.")
        path = Path(obj.meshPath) if obj is not None and obj.meshPath is not None else None
        self.mesh_name.setText(path.name if path is not None else "No mesh assigned")
        if multiple and len({str(item.meshPath) for item in selected}) > 1:
            self.mesh_name.setText("Multiple source assets")
        self.mesh_name.setToolTip(str(path) if path is not None else "")
        for attribute, inputs in self.transform_inputs.items():
            values = getattr(obj, attribute) if obj is not None else (0.0, 0.0, 0.0)
            for field, value in zip(inputs, values):
                with QSignalBlocker(field):
                    field.mixed = False
                    field.setValue(value)
                    field.set_mixed(any(getattr(item, attribute)[inputs.index(field)] != value for item in selected))

    def _object_changed(self, obj):
        if obj.identifier in self._displayed_ids:
            self._show_object(self.state.selected_object)

    def _commit_mixed(self, field, attribute, axis):
        if field.typed:
            self.state.set_transform_components(self._displayed_ids, attribute, axis, field.value())
            field.typed = False

    def _rename(self):
        if len(self._displayed_ids) != 1:
            return
        self.state.rename_object(self._displayed_id, self.name_input.text())
        obj = self.state.selected_object
        if obj is not None:
            self.name_input.setText(obj.name)

    def focus_transform(self, attribute):
        if self.state.selected_object is not None:
            self.transform_section.toggle.setChecked(True)
            field = self.transform_inputs[attribute][0]
            self.scroll.ensureWidgetVisible(field)
            field.setFocus()
            field.selectAll()
