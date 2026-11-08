"""Exercise the real Render action, separate GL window and playback controls."""
from pathlib import Path
import sys
import tempfile
import traceback
from unittest.mock import patch

from PySide6.QtWidgets import QApplication, QMessageBox
from PySide6.QtGui import QSurfaceFormat
from PySide6.QtCore import QTimer
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
            steps = window.world.steps
            window.tick()
            assert window.world.steps == steps
            window.step_button.click()
            assert window.world.steps == steps+1
            window.reset_button.click()
            assert window.world.time == 0 and not window.running
            assert window.world.scene.objects[0].position == source.position
            window.gravity.setValue(0)
            assert window.world.gravity == 0
            window.floor.setChecked(False)
            assert not window.world.floor and window.ground not in window.render_scene.objects
            assert len(window.viewport.renderObjects) == 1
            window.floor.setChecked(True)
            assert window.world.floor and window.ground in window.render_scene.objects
            assert len(window.viewport.renderObjects) == 2
            window.gravity.setValue(-9.81)
            window.frame_button.click()
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
            print("PASS Test → Render, separate OpenGL window, automatic physics, editor isolation, pause/step/reset, gravity/floor controls, framing, independent windows, solver cleanup",flush=True)
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
