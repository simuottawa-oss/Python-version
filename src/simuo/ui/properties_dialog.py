"""Scene-object material and motion controls."""

from PySide6.QtWidgets import (
    QCheckBox, QDialog, QDialogButtonBox, QDoubleSpinBox, QFormLayout, QLabel, QVBoxLayout,
)


class PropertiesDialog(QDialog):
    def __init__(self, scene_object, parent=None):
        """Build instance body-type, bounce, and velocity controls without mutating the
        source object.

        Args:
            scene_object (SceneObject): Instance whose current effective properties
                initialize the dialog.
            parent (widget, optional): Owning Qt or Tk widget; None creates an
                independent Qt widget.

        Returns:
            None. Creates controls initialized from effective instance properties.
        """
        super().__init__(parent)
        self.setWindowTitle(f"Properties — {scene_object.name}")
        self.setMinimumWidth(390)
        layout = QVBoxLayout(self)
        guidance = QLabel("Changes apply to this object and are saved with the scene.")
        guidance.setWordWrap(True)
        layout.addWidget(guidance)
        form = QFormLayout()
        layout.addLayout(form)
        self.dynamic = QCheckBox("Dynamic body")
        self.dynamic.setObjectName("dynamicBody")
        self.dynamic.setChecked(scene_object.body_type == "dynamic")
        self.dynamic.setToolTip("Checked: moves under physics. Unchecked: static and fixed in place.")
        form.addRow("Body behavior:", self.dynamic)
        self.bounce = QDoubleSpinBox()
        self.bounce.setObjectName("bounce")
        self.bounce.setRange(0, 1)
        self.bounce.setDecimals(4)
        self.bounce.setSingleStep(0.05)
        self.bounce.setValue(scene_object.restitution)
        self._originalBounce = scene_object.restitution
        self._bounceChanged = False
        self.bounce.valueChanged.connect(self._markBounceChanged)
        self.bounce.setToolTip("0: no bounce. 1: fully elastic contact. The other surface also affects the result.")
        form.addRow("Bounce (0–1):", self.bounce)
        self.velocity = []
        self._originalVelocity = list(scene_object.velocity)
        self._velocityChanged = set()
        for axis, value in zip("XYZ", scene_object.velocity):
            control = QDoubleSpinBox()
            control.setObjectName(f"velocity{axis}")
            limit = max(1e12, abs(value))
            control.setRange(-limit, limit)
            control.setDecimals(6)
            control.setSuffix(" m/s")
            control.setValue(value)
            form.addRow(f"Velocity {axis}:", control)
            self.velocity.append(control)
            index = len(self.velocity) - 1
            control.valueChanged.connect(lambda value, i=index: self._velocityChanged.add(i))
        note = ("Check Dynamic body to enable motion; uncheck it to keep the object fixed. "
                "Starting velocity applies when dynamic. Open a new Render window to use changes.")
        if scene_object.part is None:
            note += " Dynamic legacy meshes use a convex hull with a default mass of 1 kg."
        elif scene_object.part.sketch is not None or scene_object.part.features is not None:
            note += " Dynamic sketch parts use convex collision hulls, which fill concave areas."
        note = QLabel(note)
        note.setWordWrap(True)
        layout.addWidget(note)
        buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    def _markBounceChanged(self, value):
        """Record that bounce was edited so untouched file precision can otherwise be
        preserved.

        Args:
            value (float): New bounce-control signal value; only the fact that it
                changed is used.

        Returns:
            None. Sets the bounce-changed flag.
        """
        self._bounceChanged = True

    def values(self):
        # Preserve file precision for controls the user did not edit.
        """Read edited bounce and velocity controls, preserving original precision for
        untouched fields. Body type is read separately from the checkbox.

        Returns:
            tuple: Bounce float and three-component velocity list in m/s; does not apply
            them to the object.
        """
        bounce = self.bounce.value() if self._bounceChanged else self._originalBounce
        velocity = [control.value() if i in self._velocityChanged else self._originalVelocity[i]
                    for i, control in enumerate(self.velocity)]
        return bounce, velocity
