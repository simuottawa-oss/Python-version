"""GPU-free viewport for scene workflow tests."""

from PySide6.QtCore import Signal
from PySide6.QtWidgets import QWidget


class ViewportStub(QWidget):
    object_picked = Signal(object)
    box_selection_requested = Signal(object)
    transform_started = Signal(object, str)
    transform_previewed = Signal(object)
    transform_finished = Signal(bool)
    frame_requested = Signal()
    frame_scene_requested = Signal()
    escape_requested = Signal()
    tools_visibility_requested = Signal()

    def __init__(self, parent=None, scene=None):
        super().__init__(parent)
        self.scene = scene
        self.renderObjects = list(scene.objects)
        self.pick_modifiers = None

    def layout_tools(self):
        pass

    def request_frame(self):
        self.update()

    def set_selected_objects(self, objects):
        pass

    def set_tool(self, tool):
        pass

    def set_tool_options(self, options):
        pass

    def discard_transform(self):
        pass

    def cancel_interaction(self):
        pass

    def sync_scene_objects(self):
        self.renderObjects[:] = self.scene.objects

    def clearRenderObjects(self):
        self.renderObjects.clear()

    def addNewObject(self, obj):
        self.renderObjects.append(obj)

    def frameObject(self, objects):
        pass
