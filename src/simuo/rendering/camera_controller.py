"""Shared Qt navigation controls for scene, structural and playback viewports."""
import glm
from PySide6.QtCore import QObject, QEvent, Qt
from PySide6.QtWidgets import QApplication


class CameraController(QObject):
    """Translate viewport input into camera motion; tools keep their own events.

    Speeds are in viewport world units per second. Structural rendering uses
    normalized coordinates, so its viewport supplies a smaller movement speed.
    """
    CAMERA_KEYS = frozenset((Qt.Key_W, Qt.Key_A, Qt.Key_S, Qt.Key_D,
                            Qt.Key_Space, Qt.Key_Alt, Qt.Key_Left, Qt.Key_Right))
    SHORTCUT_KEYS = frozenset((Qt.Key_Control, Qt.Key_Meta, Qt.Key_AltGr))
    SHORTCUT_MODIFIERS = Qt.ControlModifier | Qt.MetaModifier | Qt.GroupSwitchModifier

    def __init__(self, viewport, *, move_speed=10., look_sensitivity=.12,
                 turn_speed=90., dolly_step=.15):
        super().__init__(viewport)
        self.viewport = viewport
        self.keys = set()
        self.move_speed = move_speed
        self.look_sensitivity = look_sensitivity
        self.turn_speed = turn_speed
        self.dolly_step = dolly_step
        QApplication.instance().installEventFilter(self)

    @property
    def camera(self):
        return self.viewport.camera

    def key_press(self, event):
        """Return whether navigation handled this key, leaving tool keys alone."""
        if event.key() in self.SHORTCUT_KEYS or event.modifiers() & self.SHORTCUT_MODIFIERS:
            self.keys.clear()
            event.ignore()
            return True
        if event.key() not in self.CAMERA_KEYS:
            return False
        self.keys.add(event.key())
        event.accept()
        return True

    def key_release(self, event):
        if not event.isAutoRepeat():
            self.keys.discard(event.key())
        if event.key() in self.CAMERA_KEYS:
            event.accept()
            return True
        return False

    def advance(self, seconds, *, blocked=False):
        """Move relative to the view, using elapsed time rather than frame count."""
        if blocked:
            self.keys.clear()
            return False
        if seconds <= 0 or not self.keys:
            return False
        turn = int(Qt.Key_Right in self.keys)-int(Qt.Key_Left in self.keys)
        if turn:
            self.camera.rotate(turn*self.turn_speed*seconds, 0., sensitivity=1.)
        delta = glm.vec3(0.)
        for positive, negative, vector in ((Qt.Key_W, Qt.Key_S, self.camera.front),
                                           (Qt.Key_D, Qt.Key_A, self.camera.right),
                                           (Qt.Key_Space, Qt.Key_Alt, self.camera.world_up)):
            delta += (int(positive in self.keys)-int(negative in self.keys))*vector
        self.camera.position += delta*self.move_speed*seconds
        return bool(turn or glm.length(delta))

    def look(self, dx, dy):
        """Apply a mouse delta, with positive dy looking upward."""
        self.camera.rotate(dx, dy, self.look_sensitivity)

    def dolly(self, steps):
        self.camera.position += self.camera.front*steps*self.dolly_step

    def eventFilter(self, watched, event):
        # Standalone Alt must not activate a menu while it is camera descent.
        if event.type() == QEvent.Type.Shortcut and self.viewport.hasFocus():
            self.keys.clear()
        if event.type() not in (QEvent.Type.KeyPress, QEvent.Type.KeyRelease, QEvent.Type.ShortcutOverride):
            return False
        if event.key() != Qt.Key_Alt:
            return False
        if event.type() == QEvent.Type.KeyRelease:
            self.key_release(event)
        if not self.viewport.hasFocus() or event.modifiers() & self.SHORTCUT_MODIFIERS:
            return False
        if event.type() == QEvent.Type.KeyPress:
            self.key_press(event)
        event.accept()
        return True
