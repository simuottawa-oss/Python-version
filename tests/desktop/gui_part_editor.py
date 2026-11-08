"""Desktop startup routing, real sketch interaction, save, scene import and Render."""
from tests import ROOT
from pathlib import Path
import sys
import tempfile
import traceback
import subprocess
from unittest.mock import patch



def startup_check(action):
    from PySide6.QtCore import QTimer
    from PySide6.QtWidgets import QPushButton
    from simuo import app
    from simuo.ui.startup_dialog import StartupDialog

    path = str(ROOT / "Assets/sketch_plate.simuOPart") if action == "open_part" else None
    label = "Open Part…" if path else "New Part"

    def automate():
        chooser = StartupDialog()
        button = next(button for button in chooser.findChildren(QPushButton) if button.text() == label)
        QTimer.singleShot(350, button.click)
        return chooser

    with (
        patch.object(sys, "argv", ["src/main.py"]),
        patch("simuo.ui.startup_dialog.StartupDialog", side_effect=automate),
        patch("simuo.ui.startup_dialog.QFileDialog.getOpenFileName", return_value=(path, "")),
        patch("simuo.ui.parts.part_editor.run_part_editor", return_value=0) as launch,
    ):
        assert app.main() == 0
        launch.assert_called_once_with(path)
    print(f"PASS startup {action} routing", flush=True)


def main():
    for action in ("new_part","open_part"):
        subprocess.run([sys.executable, "-m", "tests.desktop.gui_part_editor", "--startup", action],check=True)
    from PySide6.QtCore import Qt, QTimer
    from PySide6.QtGui import QSurfaceFormat
    from PySide6.QtTest import QTest
    from PySide6.QtWidgets import QApplication, QMessageBox
    from simuo.ui.parts.part_editor import PartEditor
    from simuo.parts.part_assets import load_asset
    from simuo.project.scene import Scene,SceneObject
    from tests.support import create_scene_window
    fmt = QSurfaceFormat()
    fmt.setVersion(3,3)
    fmt.setProfile(QSurfaceFormat.CoreProfile)
    fmt.setDepthBufferSize(24)
    QSurfaceFormat.setDefaultFormat(fmt)
    app = QApplication([])
    errors,completed,windows = [],[],[]

    def error(*exc):
        errors.append("".join(traceback.format_exception(*exc)))
        traceback.print_exception(*exc)

    sys.excepthook = error
    with tempfile.TemporaryDirectory(prefix="simuo sketch gui ") as folder:
        path = Path(folder)/"drawn plate.simuOPart"
        editor = PartEditor()
        editor.show()
        windows.append(editor)

        def finish():
            with patch("simuo.ui.scene_window.QMessageBox.question",return_value=QMessageBox.Discard):
                for window in reversed(windows):
                    if isinstance(window,PartEditor):
                        window.dirty = False
                    window.close()
            app.quit()

        def render_check():
            try:
                scene_window = windows[-1]
                render = scene_window.renderWindows[0]
                assert render.viewport.isValid() and render.world.steps>0
                assert not render.viewport.grabFramebuffer().isNull()
                assert render.world.scene.objects[0].part.sketch is not None
                print("PASS saved sketch part imports into the OpenGL scene and live physics Render",flush=True)
                completed.append(True)
            except BaseException:
                error(*sys.exc_info())
            finally:
                finish()

        def scene_check():
            try:
                window = windows[-1]
                assert window.viewport.isValid()
                assert window.viewport.renderObjects[0]["vertexCount"]==36
                assert window.viewport.grabFramebuffer().save(str(Path(tempfile.gettempdir()) / 'simuo-sketch-scene.png'))
                window.renderAction.trigger()
                QTimer.singleShot(700,render_check)
            except BaseException:
                error(*sys.exc_info())
                finish()

        def draw():
            try:
                editor.canvas.fit()
                points = [[-.06,-.04],[.06,-.04],[.06,.04],[-.06,.04]]
                for point in points+[points[0]]:
                    QTest.mouseClick(editor.canvas,Qt.LeftButton,pos=editor.canvas.screen(point).toPoint())
                assert editor.sketch.closed and len(editor.sketch.edges)==4
                editor.canvas.grab()
                assert editor.sketch.dimensions == [None]*4
                assert editor.canvas.labels == []
                editor.lines.selectRow(0)
                editor.length.setValue(180)
                editor.dimension_button.click()
                assert abs(editor.sketch.length(0)-.18)<1e-8
                editor.canvas.grab()
                assert [index for index, _ in editor.canvas.labels] == [0]
                editor.canvas.fit()
                app.processEvents()
                assert editor.grab().save(str(Path(tempfile.gettempdir()) / 'simuo-part-editor.png'))
                file_menu = editor.menuBar().actions()[0].menu()
                with patch("simuo.ui.parts.part_editor.QFileDialog.getSaveFileName",return_value=(str(path),"")):
                    next(a for a in file_menu.actions() if a.shortcut().toString()=="Ctrl+S").trigger()
                assert path.exists() and not editor.dirty
                assert load_asset(path).part.sketch.closed
                with patch("simuo.ui.parts.part_editor.QFileDialog.getOpenFileName",return_value=(str(path),"")):
                    next(a for a in file_menu.actions() if a.text()=="Open Part…").trigger()
                assert abs(editor.sketch.length(0)-.18)<1e-8
                print("PASS real mouse line drawing, face closure, driving dimension, File Save and Open",flush=True)
                scene = Scene()
                obj = SceneObject(meshPath=path)
                scene.addObject(obj)
                window = create_scene_window(scene=scene)
                window.viewport.frameObject(obj)
                window.show()
                windows.append(window)
                QTimer.singleShot(700,scene_check)
            except BaseException:
                error(*sys.exc_info())
                finish()

        QTimer.singleShot(500,draw)
        QTimer.singleShot(20000,finish)
        app.exec()
        assert completed and not errors,errors or "Part-editor GUI test timed out"


if __name__=="__main__":
    startup_check(sys.argv[2]) if len(sys.argv)>2 and sys.argv[1]=="--startup" else main()
