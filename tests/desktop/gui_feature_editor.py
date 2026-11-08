"""Real desktop: plane selection, 3D picking, face sketching, extrusion and reload."""
from pathlib import Path
import sys
import tempfile
import traceback
from unittest.mock import patch

from PySide6.QtCore import Qt,QTimer
from PySide6.QtGui import QSurfaceFormat
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication,QDialogButtonBox,QDoubleSpinBox,QMessageBox
from simuo.ui.parts.feature_editor import FeaturePartEditor
from simuo.parts.part_assets import load_asset
from simuo.parts.part_format import load_part
from simuo.project.scene import Scene,SceneObject
from tests.support import create_scene_window


def main():
    fmt = QSurfaceFormat()
    fmt.setVersion(3,3)
    fmt.setProfile(QSurfaceFormat.CoreProfile)
    fmt.setDepthBufferSize(24)
    QSurfaceFormat.setDefaultFormat(fmt)
    app = QApplication([])
    errors,complete,windows = [],[],[]

    def error(*exc):
        errors.append("".join(traceback.format_exception(*exc)))
        traceback.print_exception(*exc)

    sys.excepthook = error
    with tempfile.TemporaryDirectory(prefix="simuo 3d features ") as folder:
        path = Path(folder)/"face-extrusions.simuOPart"
        editor = FeaturePartEditor()
        editor.show()
        windows.append(editor)

        def finish():
            with patch("simuo.ui.scene_window.QMessageBox.question",return_value=QMessageBox.Discard):
                for window in reversed(windows):
                    if isinstance(window,FeaturePartEditor):
                        window.dirty = False
                    window.close()
            app.quit()

        def draw_rectangle(x,y):
            editor.canvas.fit()
            points = [[-x/2,-y/2],[x/2,-y/2],[x/2,y/2],[-x/2,y/2]]
            for point in points+[points[0]]:
                QTest.mouseClick(editor.canvas,Qt.LeftButton,pos=editor.canvas.screen(point).toPoint())
            assert editor.sketch.closed
            editor.feature_actions["Finish Sketch"].trigger()

        def extrude_dialog(mm):
            def accept():
                dialog = QApplication.activeModalWidget()
                assert dialog is not None and dialog.windowTitle()=="Extrude Face"
                dialog.findChild(QDoubleSpinBox,"extrudeDistance").setValue(mm)
                dialog.findChild(QDialogButtonBox).button(QDialogButtonBox.Ok).click()
            QTimer.singleShot(100,accept)
            editor.feature_actions["Extrude…"].trigger()

        def render_check():
            try:
                window = windows[-1]
                render = window.renderWindows[0]
                assert render.viewport.isValid() and render.world.steps>0
                assert not render.viewport.grabFramebuffer().isNull()
                assert render.world.scene.objects[0].part.features is not None
                assert abs(render.world.masses[0]-.318)<1e-5
                complete.append(True)
                print("PASS feature solid imports into the main OpenGL scene and live physics renderer",flush=True)
            except BaseException:
                error(*sys.exc_info())
            finally:
                finish()

        def scene_check():
            try:
                window = windows[-1]
                assert window.viewport.isValid()
                assert not window.viewport.grabFramebuffer().isNull()
                window.renderAction.trigger()
                QTimer.singleShot(600,render_check)
            except BaseException:
                error(*sys.exc_info())
                finish()

        def check():
            try:
                assert editor.stack.currentWidget() is editor.viewport
                planes = editor.tree.topLevelItem(0)
                top = planes.child(2)
                editor.tree.scrollToItem(top)
                QTest.mouseClick(editor.tree.viewport(),Qt.LeftButton,pos=editor.tree.visualItemRect(top).center())
                assert editor.selected_support["name"]=="Top"
                editor.feature_actions["New Sketch"].trigger()
                draw_rectangle(.12,.08)
                extrude_dialog(30)
                assert editor.model.has_solid and len(editor.model.faces)==6
                assert abs(float(editor.model.size[1])-.03)<1e-6
                print("PASS real hierarchy Top Plane selection, sketch closure and Extrude dialog",flush=True)
                app.processEvents()
                face = next(i for i,f in enumerate(editor.model.faces) if f["normal"][1]>.9)
                position = editor.viewport.project(editor.model.faces[face]["frame"]["origin"])[0]
                assert editor.viewport.pick(position)==face
                QTest.mouseClick(editor.viewport,Qt.LeftButton,pos=position.toPoint())
                assert editor.selected_support["type"]=="face"
                editor.feature_actions["New Sketch"].trigger()
                assert editor.active_feature["support"]["type"]=="face"
                draw_rectangle(.04,.02)
                editor.edit_sketch()
                editor.select_line(0)
                editor.length.setValue(50)
                editor.dimension_button.click()
                editor.finish_sketch()
                extrude_dialog(20)
                assert abs(editor.model.volume-.000308)<1e-8
                # Pull an existing planar face directly, without drawing a
                # third outline. The top of the boss has no boundary holes.
                index = next(i for i,f in enumerate(editor.model.faces) if f["normal"][1]>.9 and abs(f["frame"]["origin"][1]-.05)<1e-7)
                position = editor.viewport.project(editor.model.faces[index]["frame"]["origin"])[0]
                QTest.mouseClick(editor.viewport,Qt.LeftButton,pos=position.toPoint())
                assert editor.viewport.selected_face==index
                extrude_dialog(10)
                assert abs(editor.model.volume-.000318)<1e-8
                assert editor.viewport.grab().save(str(Path(tempfile.gettempdir()) / 'simuo-features-viewport.png'))
                assert editor.grab().save(str(Path(tempfile.gettempdir()) / 'simuo-features-editor.png'))
                feature_geometry = editor.model.geometry()
                editor.undo()
                assert abs(editor.model.volume-.000308)<1e-8
                editor.redo()
                assert editor.model.geometry()==feature_geometry
                assert editor._save_to(path)
                assert editor.open_path(path)
                assert editor.model.geometry()==feature_geometry
                assert load_part(path).features is not None
                print("PASS 3D face picking, dimensioned face sketch, joined extrusion, direct face pull, undo/redo and feature-file reload",flush=True)
                scene = Scene()
                obj = SceneObject(meshPath=path)
                scene.addObject(obj)
                window = create_scene_window(scene=scene)
                window.viewport.frameObject(obj)
                window.show()
                windows.append(window)
                QTimer.singleShot(500,scene_check)
            except BaseException:
                error(*sys.exc_info())
                finish()

        QTimer.singleShot(500,check)
        QTimer.singleShot(25000,finish)
        app.exec()
        assert complete and not errors,errors or "Feature editor test timed out"


if __name__=="__main__":
    main()
