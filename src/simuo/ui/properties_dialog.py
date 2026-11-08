"""Scene-object material and motion controls."""

from PySide6.QtWidgets import (
    QComboBox, QDialog, QDialogButtonBox, QDoubleSpinBox, QFormLayout, QLabel, QVBoxLayout,
)


from simuo.project.scene import BODY_TYPES


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
        self.body_type = QComboBox()
        self.body_type.setObjectName("bodyType")
        for mode in BODY_TYPES:
            self.body_type.addItem(mode.title(), mode)
        self.body_type.setCurrentIndex(self.body_type.findData(scene_object.body_type))
        form.addRow("Body Type", self.body_type)
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
        self._motion = {}
        for attribute, title, units in (
            ("velocity", "Velocity", "m/s"),
            ("acceleration", "Acceleration", "m/s²"),
        ):
            controls = []
            for axis, value in zip("XYZ", getattr(scene_object, attribute)):
                control = QDoubleSpinBox()
                control.setObjectName(attribute + axis)
                limit = max(1e12, abs(value))
                control.setRange(-limit, limit)
                control.setDecimals(6)
                control.setSuffix(f" {units}")
                control.setValue(value)
                form.addRow(f"{title} {axis}", control)
                controls.append((control, value, control.value()))
            self._motion[attribute] = controls
            setattr(self, attribute, [control for control, _, _ in controls])
        self.body_type.currentIndexChanged.connect(self._sync_motion)
        self._sync_motion()
        note = ("Dynamic bodies respond to gravity and contacts. Kinematic bodies follow the "
                "velocity and acceleration you set. Open a new Render window to use changes.")
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

    def _sync_motion(self):
        enabled = self.body_type.currentData() != "static"
        for controls in self._motion.values():
            for control, _, _ in controls:
                control.setEnabled(enabled)

    def values(self):
        """Return edits while preserving the precision of untouched fields."""
        return {
            "body_type": self.body_type.currentData(),
            "bounce": self.bounce.value() if self._bounceChanged else self._originalBounce,
            **{name: [original if control.value() == displayed else control.value()
                      for control, original, displayed in controls]
               for name, controls in self._motion.items()},
        }
