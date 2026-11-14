"""Reserve standalone Alt for camera descent only while a viewport has focus."""
from PySide6.QtCore import QObject, QEvent, Qt
from PySide6.QtWidgets import QApplication


class VerticalNavigationFilter(QObject):
    def __init__(self, viewport):
        super().__init__(viewport)
        self.viewport = viewport
        QApplication.instance().installEventFilter(self)

    def eventFilter(self, watched, event):
        viewport = self.viewport
        if not hasattr(viewport, "keys"):
            return False
        if event.type() == QEvent.Type.Shortcut and viewport.hasFocus():
            viewport.keys.clear()
        if event.type() not in (QEvent.Type.KeyPress, QEvent.Type.KeyRelease, QEvent.Type.ShortcutOverride):
            return False
        if event.key() != Qt.Key.Key_Alt:
            return False
        if event.type() == QEvent.Type.KeyRelease and not event.isAutoRepeat():
            viewport.keys.discard(Qt.Key.Key_Alt)
        if not viewport.hasFocus() or event.modifiers() & (Qt.KeyboardModifier.ControlModifier | Qt.KeyboardModifier.MetaModifier):
            return False
        if event.type() == QEvent.Type.KeyPress:
            viewport.keys.add(Qt.Key.Key_Alt)
        event.accept()
        return True
