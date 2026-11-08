"""Native hierarchy buttons, elided scene titles, and drop surfaces."""

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import QApplication, QPushButton, QSizePolicy, QWidget


class ObjectNameButton(QPushButton):
    rename_requested = Signal()
    context_requested = Signal(object)
    drag_requested = Signal()

    def __init__(self):
        super().__init__()
        self.full_name = ""
        self.click_modifiers = Qt.KeyboardModifier.NoModifier
        self.press_position = None
        self.setObjectName("objectNameButton")
        self.setFixedHeight(22)
        self.setMinimumWidth(0)
        self.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Fixed)

    def set_name(self, name):
        self.full_name = name
        self.setAccessibleName(name)
        self.setToolTip(name)
        self._elide()

    def _elide(self):
        self.setText(self.fontMetrics().elidedText(self.full_name, Qt.TextElideMode.ElideRight, max(1, self.width() - 8)))

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self._elide()

    def mouseDoubleClickEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            self.rename_requested.emit()
            event.accept()
        else:
            super().mouseDoubleClickEvent(event)

    def mousePressEvent(self, event):
        if event.button() == Qt.MouseButton.RightButton:
            self.context_requested.emit(event.position().toPoint())
            event.accept()
        else:
            self.click_modifiers = event.modifiers()
            self.press_position = event.position().toPoint()
            super().mousePressEvent(event)

    def mouseMoveEvent(self, event):
        if (event.buttons() & Qt.MouseButton.LeftButton and self.press_position is not None
                and (event.position().toPoint() - self.press_position).manhattanLength() >= QApplication.startDragDistance()):
            self.press_position = None
            self.setDown(False)
            self.drag_requested.emit()
            return
        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event):
        super().mouseReleaseEvent(event)
        self.click_modifiers = Qt.KeyboardModifier.NoModifier
        self.press_position = None


class SceneHeaderButton(QPushButton):
    """Keep scene names from squeezing the adjacent hierarchy actions."""
    def __init__(self):
        super().__init__()
        self.scene_name = ""

    def set_scene_name(self, name):
        self.scene_name = name
        self.setAccessibleName(name)
        self.setToolTip(name)
        self._update_text()

    def _update_text(self):
        name = self.fontMetrics().elidedText(self.scene_name, Qt.TextElideMode.ElideRight, max(1, self.width() - 46))
        self.setText(f"{'▾' if self.isChecked() else '▸'}  {name}")

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self._update_text()


class DropSurface(QWidget):
    """Ordinary widgets keep native accessibility stable while accepting drops."""
    def __init__(self, panel=None):
        super().__init__()
        self.panel = panel
        self.setAcceptDrops(True)

    def dragEnterEvent(self, event):
        self.panel.drag_over(self, event)

    def dragMoveEvent(self, event):
        self.panel.drag_over(self, event)

    def dragLeaveEvent(self, event):
        self.panel.clear_drop_indicator()
        event.accept()

    def dropEvent(self, event):
        self.panel.drop_on(self, event)
