"""A shared recording viewport for editor tests without a graphics driver."""

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import QWidget


class FakeViewport(QWidget):
    """Record scene updates without requiring a graphics driver."""

    object_picked = Signal(object)
    frame_requested = Signal()
    frame_scene_requested = Signal()
    escape_requested = Signal()
    box_selection_requested = Signal(object)
    transform_started = Signal(object, str)
    transform_previewed = Signal(object)
    transform_finished = Signal(bool)
    tools_visibility_requested = Signal()

    def __init__(self, parent, scene):
        super().__init__(parent)
        self.rendered = list(scene.objects)
        self.scene = scene
        self.pick_modifiers = Qt.NoModifier
        self.update_count = 0
        self.selected_object_id = None
        self.framed_object = None
        self.active_tool = "select"

    def set_tool(self, tool):
        self.active_tool = tool

    def set_tool_options(self, options):
        self.tool_options = dict(options)

    def cancel_interaction(self):
        self.transform_finished.emit(False)

    def discard_transform(self):
        pass

    def layout_tools(self):
        if hasattr(self, 'tool_sidebar'):
            self.tool_context.fit_to_width(max(1, self.width()-16))
            self.tool_sidebar.adjustSize()
            self.tool_sidebar.move(8, self.tool_context.geometry().bottom()+9)

    def frame_object(self, obj):
        self.framed_object = obj

    def set_selected_object(self, obj):
        self.selected_object_id = obj.identifier if obj is not None else None

    def set_selected_objects(self, objects):
        self.selected_object_ids = {obj.identifier for obj in objects}
        self.set_selected_object(objects[-1] if objects else None)

    def sync_scene_objects(self):
        self.rendered = list(self.scene.objects)

    def update(self):
        self.update_count += 1
        super().update()

    def clearRenderObjects(self):
        self.rendered.clear()

    def addNewObject(self, obj):
        self.rendered.append(obj)
