"""Exercise the real Render action, separate GL window and playback controls."""
from pathlib import Path
import sys
import tempfile
import traceback
from unittest.mock import patch

import numpy as np
from PySide6.QtWidgets import QApplication, QMainWindow, QMessageBox
from PySide6.QtGui import QSurfaceFormat, QMouseEvent
from PySide6.QtCore import QTimer, Qt, QPoint, QPointF, QEvent
from PySide6.QtTest import QTest
from tests import ROOT
from simuo.project.scene import SceneObject
from tests.support import create_scene_window


def main():
    fmt = QSurfaceFormat()
    fmt.setVersion(3,3)
    fmt.setProfile(QSurfaceFormat.CoreProfile)
    fmt.setDepthBufferSize(24)
    QSurfaceFormat.setDefaultFormat(fmt)
    app = QApplication([])
    errors = []
    finished = False

    def error(*exc):
        errors.append("".join(traceback.format_exception(*exc)))
        traceback.print_exception(*exc)

    sys.excepthook = error
    main_window = create_scene_window()
    source = SceneObject(meshPath=ROOT / "Assets/aluminum_cube.simuOPart")
    source.angularVelocity = [0,.5,0]
    main_window.scene.addObject(source)
    main_window.show()

    def finish():
        with patch("simuo.ui.scene_window.QMessageBox.question",return_value=QMessageBox.Discard):
            main_window.close()
        app.quit()

    def opened():
        try:
            # Avoid tiling desktop policies so exact compact sizes can be tested.
            def show_untiled(window):
                window.setWindowFlag(Qt.WindowType.X11BypassWindowManagerHint, True)
                QMainWindow.show(window)
            with patch("simuo.ui.physics_render.PhysicsRenderWindow.show", show_untiled):
                main_window.renderAction.trigger()
            assert len(main_window.renderWindows) == 1
            QTimer.singleShot(1000,check)
        except BaseException:
            error(*sys.exc_info())
            finish()

    def check():
        nonlocal finished
        try:
            window = main_window.renderWindows[0]
            assert window.isVisible() and window is not main_window
            assert window.viewport.isValid()
            assert window.world.steps > 0
            assert window.world.scene.objects[0].position != source.position
            assert source.position == [0,1.1,0] and source.angularVelocity == [0,.5,0]
            window.play.click()
            assert not window.running
            window.timer.stop()
            viewport = window.viewport
            assert viewport.read_only
            obj = window.world.scene.objects[0]
            transform = (list(obj.position), list(obj.rotation), list(obj.scale))
            dirty = window.render_scene.dirty
            for running in (True, False):
                window.set_running(running)
                center = viewport.rect().center()
                QTest.mousePress(viewport, Qt.LeftButton, pos=center)
                QTest.mouseMove(viewport, center + QPoint(40, 20))
                QTest.mouseRelease(viewport, Qt.LeftButton, pos=center)
                assert viewport.selectedObject is None and viewport.mover is None
                assert viewport.debug_ray is None
                assert (obj.position, obj.rotation, obj.scale) == transform
                assert window.render_scene.dirty == dirty
            # Right-drag still changes the camera without changing objects.
            yaw = viewport.camera.yaw
            QTest.mousePress(viewport, Qt.RightButton, pos=center)
            viewport.ignore_center_event = False
            position = QPointF(center.x() + 30, center.y() - 10)
            viewport.mouseMoveEvent(QMouseEvent(
                QEvent.Type.MouseMove, position, position, Qt.NoButton,
                Qt.RightButton, Qt.NoModifier))
            QTest.mouseRelease(viewport, Qt.RightButton, pos=center)
            assert viewport.camera.yaw != yaw
            assert (obj.position, obj.rotation, obj.scale) == transform
            camera_position = tuple(viewport.camera.position)
            QTest.keyPress(viewport, Qt.Key_W)
            viewport.update_camera(0.1)
            QTest.keyRelease(viewport, Qt.Key_W)
            assert tuple(viewport.camera.position) != camera_position
            window.timer.start(16)
            steps = window.world.steps
            window.tick()
            assert window.world.steps == steps
            previous = [*obj.position, *obj.rotation, *obj.velocity, *obj.angularVelocity]
            window.step_button.click()
            assert window.world.steps == steps+1
            forward = [*obj.position, *obj.rotation, *obj.velocity, *obj.angularVelocity]
            window.set_running(True)
            window.back_button.click()
            assert not window.running and window.world.steps == steps
            np.testing.assert_allclose(
                [*obj.position, *obj.rotation, *obj.velocity, *obj.angularVelocity], previous, atol=1e-8)
            window.step_button.click()
            np.testing.assert_allclose(
                [*obj.position, *obj.rotation, *obj.velocity, *obj.angularVelocity], forward, atol=1e-8)
            window.reset_button.click()
            assert window.world.time == 0 and not window.running
            assert not window.back_action.isEnabled()
            assert window.world.scene.objects[0].position == source.position
            window.gravity.setValue(0)
            assert window.world.gravity == 0
            window.step_button.click()
            assert window.back_action.isEnabled()
            window.gravity.setValue(-1)
            assert not window.back_action.isEnabled()
            window.floor.setChecked(False)
            assert not window.world.floor and window.ground not in window.render_scene.objects
            assert len(window.viewport.renderObjects) == 1
            window.floor.setChecked(True)
            assert window.world.floor and window.ground in window.render_scene.objects
            assert len(window.viewport.renderObjects) == 2
            window.gravity.setValue(-9.81)
            window.frame_button.click()
            window.resize(640, 480)
            app.processEvents()
            assert window.width() == 640 and window.height() == 480, (window.size(), window.minimumSizeHint())
            assert viewport.width() >= 280 and viewport.height() >= 240
            assert window.gravity.isVisible() and window.floor.isVisible()
            assert window.details_dock.geometry().right() < window.width()
            for button in (window.back_button, window.play, window.step_button,
                           window.reset_button, window.frame_button, window.settings_button):
                assert button.isVisible() and button.geometry().right() < window.playback_toolbar.width()
            assert window.toolBarArea(window.playback_toolbar) == Qt.ToolBarArea.BottomToolBarArea
            assert viewport.geometry().bottom() < window.playback_toolbar.geometry().top()
            assert window.playback_toolbar.geometry().bottom() < window.statusBar().geometry().top()
            assert window.settings_action.isChecked()
            viewport_width = viewport.width()
            window.settings_button.click()
            app.processEvents()
            assert not window.details_dock.isVisible() and not window.settings_action.isChecked()
            assert viewport.width() > viewport_width
            window.settings_button.click()
            app.processEvents()
            assert window.details_dock.isVisible() and window.settings_action.isChecked()
            assert window.grab().save(str(Path(tempfile.gettempdir()) / "simuo-physics-layout-small.png"))
            window.resize(1100, 800)
            app.processEvents()
            assert window.grab().save(str(Path(tempfile.gettempdir()) / "simuo-physics-layout.png"))
            frame = window.viewport.grabFramebuffer()
            assert not frame.isNull()
            assert frame.save(str(Path(tempfile.gettempdir()) / "simuo-physics-playback.png"))
            window.play.click()
            assert window.running
            main_window.renderAction.trigger()
            assert len(main_window.renderWindows) == 2
            second = main_window.renderWindows[-1]
            assert second.world.client != window.world.client
            second.close()
            assert second.world.client == -1
            window.close()
            assert window.world.client == -1
            assert not errors,errors
            finished = True
            print("PASS Render: read-only viewport, camera, bottom toolbar, rewind/resume, settings toggle, compact layout, gravity/floor, independent worlds, cleanup",flush=True)
        except BaseException:
            error(*sys.exc_info())
        finally:
            finish()

    QTimer.singleShot(700,opened)
    QTimer.singleShot(15000,finish)
    app.exec()
    assert finished and not errors,errors or "Playback test timed out"


if __name__ == "__main__":
    main()
