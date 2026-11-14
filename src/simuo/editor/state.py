"""Shared editor selection, edits, grouping, and temporary view state."""

from copy import copy, deepcopy
import math
import re
from uuid import uuid4

from PySide6.QtCore import QObject, Qt, Signal
from PySide6.QtGui import QUndoStack

from simuo.project.scene import SceneGroup
from simuo.editor.commands import ObjectEdit, SceneEdit


class EditorState(QObject):
    objects_changed = Signal()
    selection_changed = Signal(object)  # Active object, for single-object tools.
    selection_set_changed = Signal(object)
    object_changed = Signal(object)
    scene_name_changed = Signal(str)
    frame_requested = Signal(object)
    dirty_changed = Signal()
    view_changed = Signal()
    tool_changed = Signal(str)
    tool_options_changed = Signal(object)
    transform_ended = Signal()

    def __init__(self, scene, parent=None):
        super().__init__(parent)
        self.scene = scene
        scene.normalize_hierarchy()
        self.isolated_ids = None
        self.drag_token = uuid4().hex
        self._selected_ids = ()
        self.scene_name = "Untitled Scene"
        self.active_tool = "select"
        self.tool_options = {"xray": False}
        self._transform = None
        self._base_dirty = scene.dirty
        self.undo_stack = QUndoStack(self)
        self.undo_stack.indexChanged.connect(self._history_changed)
        self.undo_stack.cleanChanged.connect(self._history_changed)
        self._refresh_view(emit=False)

    def find_group(self, identifier):
        return next((group for group in self.scene.groups if group.identifier == identifier), None)

    def group_for_object(self, identifier):
        return next((group for group in self.scene.groups if identifier in group.members), None)

    def organization(self, objects=None):
        """Immutable membership/order snapshot, preserving group object identities."""
        objects = self.scene.objects if objects is None else objects
        keys = {obj.identifier for obj in objects}
        groups = tuple((group, tuple(key for key in group.members if key in keys)) for group in self.scene.groups)
        grouped = {key for group, members in groups for key in members}
        roots = [key for key in self.scene.root_order
                 if key in keys - grouped or self.find_group(key) is not None]
        roots.extend(obj.identifier for obj in objects if obj.identifier not in grouped and obj.identifier not in roots)
        return groups, tuple(roots)

    def ordered_object_ids(self):
        result = []
        for key in self.scene.root_order:
            group = self.find_group(key)
            result.extend(group.members if group is not None else (key,))
        return result

    def _refresh_view(self, emit=True):
        membership = {key: group for group in self.scene.groups for key in group.members}
        for obj in self.scene.objects:
            group = membership.get(obj.identifier)
            obj._group_visible = group.editor_visible if group is not None else True
            obj._group_locked = group.selection_locked if group is not None else False
            obj._isolated_out = self.isolated_ids is not None and obj.identifier not in self.isolated_ids
        if emit:
            self.view_changed.emit()

    def isolate_selected(self):
        self.cancel_transform()
        if self.selected_ids:
            self.isolated_ids = frozenset(self.selected_ids)
            self._refresh_view()

    def exit_isolation(self):
        self.cancel_transform()
        self.isolated_ids = None
        self._refresh_view()

    def _history_changed(self, *args):
        self.scene.dirty = self._base_dirty or not self.undo_stack.isClean()
        self.dirty_changed.emit()

    def mark_saved(self):
        self.cancel_transform()
        self._base_dirty = False
        self.undo_stack.setClean()
        self._history_changed()

    def set_scene_name(self, name):
        if name != self.scene_name:
            self.scene_name = name
            self.scene_name_changed.emit(name)

    def find_object(self, identifier):
        return next((obj for obj in self.scene.objects if obj.identifier == identifier), None)

    @property
    def selected_ids(self):
        return self._selected_ids

    @property
    def selected_objects(self):
        objects = {obj.identifier: obj for obj in self.scene.objects}
        return tuple(objects[key] for key in self._selected_ids if key in objects)

    @property
    def selected_object(self):
        objects = self.selected_objects
        return objects[-1] if objects else None

    def _emit_selection(self):
        self.selection_changed.emit(self.selected_object)
        self.selection_set_changed.emit(self.selected_objects)

    def select_many(self, identifiers):
        valid = {obj.identifier for obj in self.scene.objects}
        identifiers = tuple(dict.fromkeys(key for key in identifiers if key in valid))
        if identifiers != self._selected_ids:
            self.cancel_transform()
            self._selected_ids = identifiers
            self._emit_selection()

    def select(self, identifier):
        self.select_many((identifier,))

    def toggle_selection(self, identifier):
        if identifier in self._selected_ids:
            self.select_many(key for key in self._selected_ids if key != identifier)
        else:
            self.select_many((*self._selected_ids, identifier))

    def select_from_viewport(self, identifier, modifiers=Qt.KeyboardModifier.NoModifier):
        if modifiers & (Qt.KeyboardModifier.ControlModifier | Qt.KeyboardModifier.MetaModifier | Qt.KeyboardModifier.ShiftModifier):
            if identifier is not None:
                self.toggle_selection(identifier)
        else:
            self.select(identifier)

    def frame_selected(self):
        visible = tuple(obj for obj in self.selected_objects if obj.viewport_visible)
        if visible:
            self.frame_requested.emit(visible[0] if len(visible) == 1 else visible)

    def frame_scene(self):
        visible = tuple(obj for obj in self.scene.objects if obj.viewport_visible and obj.meshPath is not None)
        if visible:
            self.frame_requested.emit(visible[0] if len(visible) == 1 else visible)

    def _edit(self, text, updates):
        self.cancel_transform()
        changes = [(obj, attribute, deepcopy(getattr(obj, attribute)), deepcopy(value))
                   for obj, attribute, value in updates if getattr(obj, attribute) != value]
        if not changes:
            return False
        self.undo_stack.push(ObjectEdit(self, text, changes))
        return True

    def set_visibility(self, identifier, visible):
        self.set_objects_visibility((identifier,), visible)

    def set_objects_visibility(self, identifiers, visible):
        self._edit("Show Objects" if visible else "Hide Objects",
                   [(obj, "editor_visible", bool(visible)) for obj in self._objects(identifiers)])

    def set_selection_locked(self, identifier, locked):
        self.set_objects_locked((identifier,), locked)

    def set_objects_locked(self, identifiers, locked):
        self._edit("Lock Selection" if locked else "Unlock Selection",
                   [(obj, "selection_locked", bool(locked)) for obj in self._objects(identifiers)])

    def _objects(self, identifiers):
        keys = set(identifiers)
        return [obj for obj in self.scene.objects if obj.identifier in keys]

    def replace_objects(self, objects, groups=(), root_order=()):
        """Start a new history when loading or creating a scene."""
        self.cancel_transform()
        self._selected_ids = ()
        self.scene.objects.clear()
        self.scene.groups[:] = groups
        self.scene.root_order[:] = root_order
        for obj in objects:
            self.scene.addObject(obj)
        self.scene.normalize_hierarchy()
        self.isolated_ids = None
        self._refresh_view(emit=False)
        self._base_dirty = False
        self.undo_stack.clear()
        self._history_changed()
        self.objects_changed.emit()
        self.view_changed.emit()
        self._emit_selection()

    def add_object(self, obj):
        self.cancel_transform()
        if self.find_object(obj.identifier) is not None or self.find_group(obj.identifier) is not None:
            obj.identifier = uuid4().hex
        self.undo_stack.push(SceneEdit(self, "Import Object", [*self.scene.objects, obj], self.selected_ids))

    def reset_transform(self, identifier, attribute=None):
        self.reset_transforms((identifier,), attribute)

    def reset_transforms(self, identifiers, attribute=None):
        defaults = {"position": [0.0] * 3, "rotation": [0.0] * 3, "scale": [1.0] * 3}
        if attribute is not None and attribute not in defaults:
            raise ValueError("Unknown transform")
        attributes = (attribute,) if attribute is not None else defaults
        self._edit("Reset " + (attribute.title() if attribute else "Transform"),
                   [(obj, name, defaults[name]) for obj in self._objects(identifiers) for name in attributes])

    def rename_object(self, identifier, name):
        obj = self.find_object(identifier)
        name = name.strip()
        return bool(obj is not None and name and self._edit("Rename Object", [(obj, "name", name)]))

    def set_transform_component(self, identifier, attribute, axis, value):
        return self.set_transform_components((identifier,), attribute, axis, value)

    def set_transform_components(self, identifiers, attribute, axis, value):
        self.cancel_transform()
        if attribute not in ("position", "rotation", "scale") or axis not in (0, 1, 2):
            raise ValueError("Unknown transform component")
        value = float(value)
        if not math.isfinite(value):
            return False
        updates = []
        for obj in self._objects(identifiers):
            vector = list(getattr(obj, attribute))
            vector[axis] = value
            updates.append((obj, attribute, vector))
        return self._edit("Change " + attribute.title(), updates)

    def set_material(self, identifier, material):
        obj = self.find_object(identifier)
        if obj is None:
            return False
        updated = copy(obj)
        updated.material_override = material
        return self._edit("Change Material", [(obj, "material_override", material)])

    def set_physics_properties(self, identifier, *, bounce=None, velocity=None, body_type=None, acceleration=None):
        obj = self.find_object(identifier)
        if obj is None:
            return False
        updated = copy(obj)
        updated.setPhysicsProperties(
            obj.restitution if bounce is None else bounce,
            obj.velocity if velocity is None else velocity,
            body_type,
            acceleration,
        )
        changes = []
        for field, storage in (("restitution", "_restitution"), ("body_type", "_body_type"),
                               ("velocity", "velocity"), ("acceleration", "acceleration")):
            if getattr(obj, field) != getattr(updated, field):
                changes.append((obj, storage, getattr(updated, storage)))
        return self._edit("Change Physics Properties", changes)

    def duplicate_selected(self):
        self.cancel_transform()
        sources = self._objects(self.selected_ids)
        if not sources:
            return
        names = {obj.name for obj in self.scene.objects}
        copies = []
        for obj in sources:
            # Share immutable mesh geometry and keep instance transforms independent.
            copy = deepcopy(obj, {id(obj.asset): obj.asset})
            copy.identifier = uuid4().hex
            base = re.sub(r"\.\d{3,}$", "", obj.name)
            index = 1
            while f"{base}.{index:03d}" in names:
                index += 1
            copy.name = f"{base}.{index:03d}"
            names.add(copy.name)
            copies.append(copy)
        groups, roots = self.organization()
        roots = list(roots)
        members = {group.identifier: list(keys) for group, keys in groups}
        for source, copy in zip(sources, copies):
            group = self.group_for_object(source.identifier)
            container = roots if group is None else members[group.identifier]
            container.insert(container.index(source.identifier) + 1, copy.identifier)
        organization = (tuple((group, tuple(members[group.identifier])) for group, keys in groups), tuple(roots))
        self.undo_stack.push(SceneEdit(self, "Duplicate Objects", [*self.scene.objects, *copies],
                                       [obj.identifier for obj in copies], organization))

    def delete_selected(self):
        self.delete_objects(self.selected_ids)

    def delete_objects(self, identifiers):
        self.cancel_transform()
        keys = set(identifiers)
        remaining = [obj for obj in self.scene.objects if obj.identifier not in keys]
        if len(remaining) != len(self.scene.objects):
            selection = [key for key in self.selected_ids if key not in keys]
            self.undo_stack.push(SceneEdit(self, "Delete Objects", remaining, selection))

    def history_objects(self):
        """Find instances that can reappear through undo or redo."""
        objects = dict.fromkeys(self.scene.objects)
        for index in range(self.undo_stack.count()):
            command = self.undo_stack.command(index)
            if isinstance(command, SceneEdit):
                objects.update(dict.fromkeys(command.before[0]))
                objects.update(dict.fromkeys(command.after[0]))
        return objects

    def create_group(self, name="Group", identifiers=()):
        self.cancel_transform()
        names = {group.name for group in self.scene.groups}
        base, index = name.strip() or "Group", 1
        name = base
        while name in names:
            name = f"{base}.{index:03d}"
            index += 1
        group = SceneGroup(name)
        keys = set(identifiers)
        group.members = [key for key in self.ordered_object_ids() if key in keys]
        groups, roots = self.organization()
        groups = tuple((item, tuple(key for key in members if key not in keys)) for item, members in groups)
        insertion = min((i for i, key in enumerate(roots) if key in keys), default=len(roots))
        roots = [key for key in roots if key not in keys]
        roots.insert(insertion, group.identifier)
        organization = ((*groups, (group, tuple(group.members))), tuple(roots))
        self.undo_stack.push(SceneEdit(self, "Create Group", self.scene.objects, self.selected_ids, organization))
        return group

    def rename_group(self, identifier, name):
        group = self.find_group(identifier)
        name = name.strip()
        return bool(group is not None and name and self._edit("Rename Group", [(group, "name", name)]))

    def set_group_visibility(self, identifier, visible):
        group = self.find_group(identifier)
        if group is not None:
            self._edit("Show Group" if visible else "Hide Group", [(group, "editor_visible", bool(visible))])

    def set_group_locked(self, identifier, locked):
        group = self.find_group(identifier)
        if group is not None:
            self._edit("Lock Group" if locked else "Unlock Group", [(group, "selection_locked", bool(locked))])

    def remove_group(self, identifier):
        self.cancel_transform()
        group = self.find_group(identifier)
        if group is None:
            return
        groups, roots = self.organization()
        groups = tuple((item, keys) for item, keys in groups if item is not group)
        roots = [child for key in roots for child in (group.members if key == identifier else (key,))]
        self.undo_stack.push(SceneEdit(self, "Remove Group", self.scene.objects, self.selected_ids, (groups, tuple(roots))))

    def move_objects(self, identifiers, group_id=None, before=None):
        """Move a selection as one stable block, without modifying transforms."""
        self.cancel_transform()
        group = self.find_group(group_id)
        if group_id is not None and group is None:
            return False
        keys = set(identifiers)
        moving = [key for key in self.ordered_object_ids() if key in keys]
        if not moving or before in keys:
            return False
        groups, roots = self.organization()
        containers = {item.identifier: [key for key in members if key not in keys] for item, members in groups}
        roots = [key for key in roots if key not in keys]
        target = roots if group_id is None else containers[group_id]
        if before is not None and before not in target:
            return False
        index = target.index(before) if before is not None else len(target)
        target[index:index] = moving
        organization = (tuple((item, tuple(containers[item.identifier])) for item, members in groups), tuple(roots))
        if organization == self.organization():
            return False
        self.undo_stack.push(SceneEdit(self, "Move Objects", self.scene.objects, self.selected_ids, organization))
        return True

    def move_group(self, identifier, before=None):
        self.cancel_transform()
        if self.find_group(identifier) is None or before == identifier:
            return False
        groups, roots = self.organization()
        roots = [key for key in roots if key != identifier]
        if before is not None and before not in roots:
            return False
        roots.insert(roots.index(before) if before is not None else len(roots), identifier)
        organization = (groups, tuple(roots))
        if organization == self.organization():
            return False
        self.undo_stack.push(SceneEdit(self, "Move Group", self.scene.objects, self.selected_ids, organization))
        return True

    def set_tool(self, tool):
        if tool not in ("select", "move"):
            raise ValueError("Unknown viewport tool")
        if tool != self.active_tool:
            self.cancel_transform()
            self.active_tool = tool
            self.tool_changed.emit(tool)

    def set_tool_options(self, **updates):
        options = {**self.tool_options, **updates}
        if set(options) != {"xray"} or not isinstance(options["xray"], bool):
            raise ValueError("Invalid viewport tool options")
        if options != self.tool_options:
            self.cancel_transform()
            self.tool_options = options
            self.tool_options_changed.emit(dict(options))

    def begin_transform(self, identifiers, label):
        self.cancel_transform()
        objects = [obj for obj in self._objects(identifiers) if obj.viewport_visible and not obj.viewport_locked]
        if not objects:
            return
        before = {obj.identifier: {name: list(getattr(obj, name)) for name in ("position", "rotation", "scale")}
                  for obj in objects}
        self._transform = (objects, before, self.scene.dirty, label)

    def preview_transform(self, updates):
        if self._transform is None:
            return
        objects, before, dirty, label = self._transform
        validated = []
        for obj in objects:
            values = updates.get(obj.identifier, {})
            for name, vector in values.items():
                if name not in ("position", "rotation", "scale") or len(vector) != 3:
                    raise ValueError("Invalid transform preview")
                vector = [float(value) for value in vector]
                if not all(math.isfinite(value) for value in vector):
                    raise ValueError("Non-finite transform preview")
                validated.append((obj, name, vector))
        for obj, name, vector in validated:
            setattr(obj, name, vector)
        changed = any(list(getattr(obj, name)) != vector for obj in objects
                      for name, vector in before[obj.identifier].items())
        self.scene.dirty = dirty or changed
        self.dirty_changed.emit()
        for obj in objects:
            self.object_changed.emit(obj)

    def finish_transform(self, commit=True):
        if self._transform is None:
            return
        objects, before, dirty, label = self._transform
        self._transform = None
        changes = [(obj, name, original, list(getattr(obj, name))) for obj in objects
                   for name, original in before[obj.identifier].items() if list(getattr(obj, name)) != original]
        if commit and changes:
            self.undo_stack.push(ObjectEdit(self, label, changes))
        else:
            for obj in objects:
                for name, vector in before[obj.identifier].items():
                    setattr(obj, name, list(vector))
                self.object_changed.emit(obj)
            self.scene.dirty = dirty
            self.dirty_changed.emit()
        self.transform_ended.emit()

    def cancel_transform(self):
        self.finish_transform(False)
