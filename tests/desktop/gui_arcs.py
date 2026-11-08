"""Desktop arc drawing, manual radius, save/export and scene/Render integration."""
from pathlib import Path
import sys
import tempfile
import traceback
from unittest.mock import patch

from PySide6.QtCore import Qt,QTimer
from PySide6.QtGui import QSurfaceFormat
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication,QMessageBox
from simuo.ui.parts.part_editor import PartEditor
from simuo.parts.part_assets import load_asset
from simuo.project.scene import Scene,SceneObject
from tests.support import create_scene_window


def main():
    fmt=QSurfaceFormat()
    fmt.setVersion(3,3)
    fmt.setProfile(QSurfaceFormat.CoreProfile)
    fmt.setDepthBufferSize(24)
    QSurfaceFormat.setDefaultFormat(fmt)
    app=QApplication([])
    errors,passed,windows=[],[],[]
    def error(*exc):
        errors.append(''.join(traceback.format_exception(*exc)))
        traceback.print_exception(*exc)
    sys.excepthook=error
    with tempfile.TemporaryDirectory(prefix='simuo arc desktop ') as folder:
        folder=Path(folder)
        path=folder/'radius part.simuOPart'
        editor=PartEditor()
        editor.show()
        windows.append(editor)
        def finish():
            with patch('simuo.ui.scene_window.QMessageBox.question',return_value=QMessageBox.Discard):
                for window in reversed(windows):
                    if isinstance(window,PartEditor):
                        window.dirty=False
                    window.close()
            app.quit()
        def render_check():
            try:
                window=windows[-1]
                render=window.renderWindows[0]
                assert render.viewport.isValid() and render.world.steps>0
                assert not render.viewport.grabFramebuffer().isNull()
                assert render.world.scene.objects[0].part.sketch.is_arc(0)
                print('PASS curved solid renders and participates in live physics',flush=True)
                passed.append(True)
            except BaseException:
                error(*sys.exc_info())
            finally:
                finish()
        def scene_check():
            try:
                window=windows[-1]
                assert window.viewport.isValid()
                assert window.viewport.renderObjects[0]['vertexCount']>36
                assert not window.viewport.grabFramebuffer().isNull()
                window.openPhysicsRender()
                QTimer.singleShot(600,render_check)
            except BaseException:
                error(*sys.exc_info())
                finish()
        def draw():
            try:
                editor.canvas.fit()
                editor.arc_action.trigger()
                for point in [[-.05,0],[0,.05],[.05,0]]:
                    QTest.mouseClick(editor.canvas,Qt.LeftButton,pos=editor.canvas.screen(point).toPoint())
                assert editor.sketch.is_arc(0)
                assert editor.sketch.dimensions[0] is None
                editor.select_line(0)
                assert 'radius' in editor.dimension_label.text()
                editor.length.setValue(75)
                editor.dimension_button.click()
                assert abs(editor.sketch.dimension_value(0)-.075)<1e-9
                editor.line_action.trigger()
                QTest.mouseClick(editor.canvas,Qt.LeftButton,pos=editor.canvas.screen(editor.sketch.points[0]).toPoint())
                assert editor.sketch.closed
                editor.canvas.fit()
                app.processEvents()
                assert editor.grab().save(str(Path(tempfile.gettempdir()) / 'simuo-arcs.png'))
                assert len(editor.canvas.labels)==1
                print('PASS three-point Arc tool, manual R75 dimension and line closure',flush=True)
                assert editor._save_to(path)
                assert editor.open_path(path)
                assert editor.sketch.is_arc(0)
                assert abs(editor.sketch.dimension_value(0)-.075)<1e-9
                for kind in ('obj','stl'):
                    output=folder/f'arc.{kind}'
                    with patch('simuo.ui.parts.part_editor.QFileDialog.getSaveFileName',return_value=(str(output),'')):
                        assert editor.export_mesh(kind)
                    assert output.is_file()
                assert load_asset(path).part.sketch.is_arc(0)
                print('PASS editable arc file reload and OBJ/STL exports',flush=True)
                scene=Scene()
                scene.addObject(SceneObject(meshPath=path))
                window=create_scene_window(scene=scene)
                window.viewport.frameObject(scene.objects[0])
                window.show()
                windows.append(window)
                QTimer.singleShot(600,scene_check)
            except BaseException:
                error(*sys.exc_info())
                finish()
        QTimer.singleShot(700,draw)
        QTimer.singleShot(20000,finish)
        app.exec()
        assert passed and not errors,errors or 'Arc desktop check timed out'

if __name__=='__main__':
    main()
