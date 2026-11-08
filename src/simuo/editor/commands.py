"""Undo commands for object properties and scene organization."""

from copy import deepcopy

from PySide6.QtGui import QUndoCommand


class ObjectEdit(QUndoCommand):
    def __init__(self, state, text, changes):
        super().__init__(text)
        self.state, self.changes = state, changes

    def _apply(self, index):
        affected = {}
        for obj, attribute, before, after in self.changes:
            setattr(obj, attribute, deepcopy((before, after)[index]))
            affected[obj.identifier] = obj
        self.state._refresh_view()
        for obj in affected.values():
            self.state.object_changed.emit(obj)

    def redo(self):
        self._apply(1)

    def undo(self):
        self._apply(0)


class SceneEdit(QUndoCommand):
    def __init__(self, state, text, objects, selection, organization=None):
        super().__init__(text)
        self.state = state
        self.before = (tuple(state.scene.objects), state.selected_ids, state.organization())
        self.after = (tuple(objects), tuple(selection),
                      organization if organization is not None else state.organization(objects))

    def _apply(self, snapshot):
        objects, selection, (groups, roots) = snapshot
        self.state.scene.objects[:] = objects
        self.state.scene.groups[:] = [group for group, members in groups]
        for group, members in groups:
            group.members = list(members)
        self.state.scene.root_order[:] = roots
        self.state._selected_ids = tuple(selection)
        self.state._refresh_view(emit=False)
        self.state.objects_changed.emit()
        self.state.view_changed.emit()
        self.state._emit_selection()

    def redo(self):
        self._apply(self.after)

    def undo(self):
        self._apply(self.before)
