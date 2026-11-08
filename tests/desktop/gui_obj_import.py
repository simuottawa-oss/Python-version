"""Real OpenGL check of OBJ -> temporary part -> saved scene -> reopen."""
import json
from pathlib import Path
import sys
import tempfile
import traceback
from unittest.mock import patch

from PySide6.QtWidgets import QApplication, QMessageBox
from PySide6.QtGui import QSurfaceFormat
from PySide6.QtCore import QTimer
from tests import ROOT
from tests.support import create_scene_window


def main():
    fmt = QSurfaceFormat()
    fmt.setVersion(3, 3)
    fmt.setProfile(QSurfaceFormat.CoreProfile)
    fmt.setDepthBufferSize(24)
    QSurfaceFormat.setDefaultFormat(fmt)
    app = QApplication([])
    errors, passed = [], []
    def error_hook(*exc):
        errors.append(''.join(traceback.format_exception(*exc)))
        traceback.print_exception(*exc)
    sys.excepthook = error_hook
    with tempfile.TemporaryDirectory(prefix='simuo obj desktop ') as folder:
        folder = Path(folder)
        source = folder/'source cube.obj'
        source.write_bytes((ROOT/'Assets/cube.simuOPart').read_bytes())
        scene, part = folder/'scene.simuO', folder/'saved cube.simuOPart'
        window = create_scene_window()
        window.show()
        def check():
            try:
                assert window.viewport.isValid()
                with patch('simuo.ui.scene_window.QFileDialog.getOpenFileName', return_value=(str(source), '')), \
                     patch('simuo.ui.scene_window.QMessageBox.question', return_value=QMessageBox.Yes):
                    window.importFile()
                assert len(window.scene.objects) == len(window.viewport.renderObjects) == 1
                assert window.viewport.renderObjects[0]['vertexCount'] == 36
                assert window.temporaryPartsList.count() == 1
                assert not window.temporaryPartsDock.isHidden()
                pending = window.scene.objects[0].meshPath
                assert pending.exists()
                image = window.viewport.grabFramebuffer()
                assert not image.isNull()
                assert image.save(str(Path(tempfile.gettempdir()) / 'simuo-obj-import.png'))
                print('PASS OBJ conversion, temporary directory/list, GPU upload and framebuffer', flush=True)
                with patch('simuo.ui.scene_window.QFileDialog.getSaveFileName', side_effect=[(str(scene), ''), ('', '')]):
                    assert not window.saveFile()
                assert pending.exists() and not scene.exists()
                print('PASS canceled part save leaves temporary part and scene intact', flush=True)
                with patch('simuo.ui.scene_window.QFileDialog.getSaveFileName', side_effect=[(str(scene), ''), (str(part), '')]):
                    assert window.saveFile()
                assert not pending.exists() and part.exists() and source.exists()
                assert window.temporaryPartsList.count() == 0
                assert window.temporaryPartsDock.isHidden()
                data = json.loads(scene.read_text())
                assert data['objects'][0]['meshPath'] == part.name
                window.loadFile(scene)
                assert len(window.viewport.renderObjects) == 1
                assert window.scene.objects[0].meshPath == part.resolve()
                assert not window.viewport.grabFramebuffer().isNull()
                print('PASS permanent part save, relative scene reference and GPU reload', flush=True)
                passed.append(True)
            except BaseException:
                error_hook(*sys.exc_info())
            finally:
                window.temporaryParts.cleanup()
                with patch('simuo.ui.scene_window.QMessageBox.question', return_value=QMessageBox.Discard):
                    window.close()
                app.quit()
        QTimer.singleShot(1200, check)
        QTimer.singleShot(15000, app.quit)
        app.exec()
        assert passed and not errors, errors or 'GUI checks did not complete'

if __name__ == '__main__':
    main()
