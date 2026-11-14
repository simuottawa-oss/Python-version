"""Undoable structural input snapshots, independent of generated meshes/results."""
from dataclasses import dataclass, replace
from PySide6.QtCore import QObject, Signal
from PySide6.QtGui import QUndoCommand, QUndoStack


@dataclass(frozen=True)
class StructuralInputs:
    material: object = None
    supports: tuple = ()
    support_names: tuple = ()
    support_conditions: tuple = ()
    loads: tuple = ()
    point_loads: tuple = ()
    mesh_size: float = .05
    feature_angle: float = 40.
    units: str = "m"
    gravity_enabled: bool = False
    gravity: tuple = (0., -9.80665, 0.)
    beam_clamp: tuple | None = None
    beam_free: tuple | None = None


class InputEdit(QUndoCommand):
    def __init__(self, state, text, after):
        super().__init__(text)
        self.state, self.before, self.after = state, state.inputs, after

    def apply(self, value):
        before = self.state.inputs
        self.state.inputs = value
        self.state.changed.emit(before, value)

    def redo(self):
        self.apply(self.after)

    def undo(self):
        self.apply(self.before)


class StructuralState(QObject):
    changed = Signal(object, object)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.inputs = StructuralInputs()
        self.undo_stack = QUndoStack(self)

    def edit(self, text, **updates):
        after = replace(self.inputs, **updates)
        if after != self.inputs:
            self.undo_stack.push(InputEdit(self, text, after))

    def reset(self, inputs):
        before = self.inputs
        self.inputs = inputs
        self.undo_stack.clear()
        self.changed.emit(before, inputs)
        self.undo_stack.setClean()
