"""Desktop smoke check for Properties, scene persistence, and Render overrides."""
from pathlib import Path
import sys
import tempfile
import traceback
from unittest.mock import patch

from PySide6.QtCore import QTimer
from PySide6.QtGui import QSurfaceFormat
from PySide6.QtWidgets import QApplication, QDialogButtonBox, QMessageBox
from tests import ROOT
from simuo.ui.properties_dialog import PropertiesDialog
from simuo.project.scene import SceneObject
from tests.support import create_scene_window


def main():
    fmt = QSurfaceFormat()
    fmt.setVersion(3, 3)
    fmt.setProfile(QSurfaceFormat.CoreProfile)
    fmt.setDepthBufferSize(24)
    QSurfaceFormat.setDefaultFormat(fmt)
    app = QApplication([])
    failures, passed = [], []
    def error_hook(*exc):
        failures.append(''.join(traceback.format_exception(*exc)))
        traceback.print_exception(*exc)
    sys.excepthook = error_hook
    with tempfile.TemporaryDirectory(prefix='simuo properties gui ') as directory:
        window = create_scene_window()
        window.show()
        def finish():
            for child in list(window.renderWindows):
                child.close()
            with patch('simuo.ui.scene_window.QMessageBox.question', return_value=QMessageBox.Discard):
                window.close()
            app.quit()
        def check_render():
            try:
                assert len(window.renderWindows) == 1
                render = window.renderWindows[0]
                render.set_running(False)
                assert render.viewport.isValid()
                world = render.world
                assert world.time > 0
                settings = world.bullet.getDynamicsInfo(world.bodies[0], -1, physicsClientId=world.client)
                assert abs(settings[5]-.8) < 1e-8
                assert not render.viewport.grabFramebuffer().isNull()
                assert window.scene.objects[0].velocity == [1, 2, -3]
                print('PASS edited bounce reaches Bullet; live Render and source-scene isolation', flush=True)
                passed.append(True)
            except BaseException:
                error_hook(*sys.exc_info())
            finally:
                finish()
        def edit_dialog():
            dialog = QApplication.activeModalWidget()
            try:
                assert isinstance(dialog, PropertiesDialog)
                dialog.bounce.setValue(.8)
                for widget, value in zip(dialog.velocity, [1, 2, -3]):
                    widget.setValue(value)
                dialog.grab().save(str(Path(tempfile.gettempdir()) / 'simuo-properties.png'))
                dialog.findChild(QDialogButtonBox).button(QDialogButtonBox.Ok).click()
            except BaseException:
                error_hook(*sys.exc_info())
                if dialog:
                    dialog.reject()
        def start():
            try:
                obj = SceneObject(meshPath=ROOT/'Assets/aluminum_cube.simuOPart')
                window.viewport.addNewObject(obj)
                window.scene.addObject(obj)
                window.viewport.frameObject(obj)
                QTimer.singleShot(150, edit_dialog)
                window.propertiesAction.trigger()
                assert not failures
                assert obj.restitution == .8 and obj.velocity == [1, 2, -3]
                assert window.scene.dirty
                print('PASS Properties button, real dialog editing and OK', flush=True)
                path = Path(directory)/'edited.simuO'
                assert window.saveFile(destination=path)
                window.loadFile(path)
                assert window.scene.objects[0].restitution == .8
                assert window.scene.objects[0].velocity == [1, 2, -3]
                print('PASS saved scene restores edited bounce and velocity', flush=True)
                window.openPhysicsRender()
                QTimer.singleShot(500, check_render)
            except BaseException:
                error_hook(*sys.exc_info())
                finish()
        QTimer.singleShot(1000, start)
        QTimer.singleShot(15000, finish)
        app.exec()
        assert passed and not failures, failures or 'Checks did not finish'

if __name__ == '__main__':
    main()
