"""Desktop integration test. Run with the application's Python on a desktop."""
import json
from pathlib import Path
import sys
import tempfile
import traceback
from unittest.mock import patch


from PySide6.QtWidgets import QApplication, QMessageBox
from PySide6.QtGui import QSurfaceFormat
from PySide6.QtCore import QPoint, Qt, QTimer
from PySide6.QtTest import QTest
from tests import ROOT
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

    def error_hook(*exc):
        errors.append("".join(traceback.format_exception(*exc)))
        traceback.print_exception(*exc)

    sys.excepthook = error_hook
    with tempfile.TemporaryDirectory(prefix="simuo-part-render-") as temp:
        folder = Path(temp)
        startup = folder / "startup.simuO"
        sample = ROOT / "Assets/aluminum_cube.simuOPart"
        startup.write_text(json.dumps({"version":1,"objects":[{"name":"Startup cube","meshPath":str(sample)}]}))
        window = create_scene_window(projectPath=startup)
        window.show()

        def check():
            nonlocal finished
            try:
                assert window.viewport.isValid(), "No valid OpenGL context"
                assert len(window.viewport.renderObjects) == 1
                assert window.viewport.renderObjects[0]["vertexCount"] == 36
                assert window.scene.objects[0].position == [0,1.1,0]
                image = window.viewport.grabFramebuffer()
                assert not image.isNull()
                cyan = 0
                for y in range(0,image.height(),3):
                    for x in range(0,image.width(),3):
                        c = image.pixelColor(x,y)
                        cyan += c.green()>c.red()*1.4 and c.blue()>c.red()*1.4 and c.green()>50
                assert cyan > 100, f"No clearly visible cyan part: {cyan} samples"
                assert image.save(str(Path(tempfile.gettempdir()) / "simuo-json-part.png"))
                print(f"PASS startup JSON part, shaders, camera framing, colored framebuffer ({cyan} cyan samples)",flush=True)

                obj = window.scene.objects[0]
                viewport = window.viewport
                center = viewport.projection().point(obj.position)
                QTest.mouseClick(viewport, Qt.LeftButton, pos=QPoint(round(center[0]), round(center[1])))
                assert window.editor_state.selected_object is obj
                hierarchy = window.panel_manager.docks["object_hierarchy"]
                assert hierarchy.widget().state.selected_object is obj
                window.toolActions["move"].trigger()
                assert all(not window.toolActions[tool].isEnabled() for tool in ("rotate", "scale"))
                options = viewport.tool_context
                for control in (options.orientation_input, options.pivot_input, options.snap_button):
                    assert control.isVisible() and not control.isEnabled()
                handle = next(handle for handle in viewport.gizmo().handles if handle.key == "x")
                a, b = handle.points
                start = QPoint(round(b[0]), round(b[1]))
                delta = (b - a) * 0.5
                end = start + QPoint(round(delta[0]), round(delta[1]))
                position = list(obj.position)
                QTest.mousePress(viewport, Qt.LeftButton, pos=start)
                QTest.mouseMove(viewport, end)
                QTest.mouseRelease(viewport, Qt.LeftButton, pos=end)
                assert obj.position != position, "Move gizmo did not change the selected part"
                window.undoAction.trigger()
                assert obj.position == position
                print("PASS viewport selection, hierarchy, move gizmo and undo on JSON part", flush=True)

                obj.position = [1,2,3]
                obj.rotation = [10,20,30]
                obj.velocity = [2,3,4]
                obj.acceleration = [0,-9.81,0]
                obj.angularVelocity = [0,1,0]
                window.projectPath = folder / "roundtrip.simuO"
                window.saveFile()
                stored = json.loads(window.projectPath.read_text())
                assert not Path(stored["objects"][0]["meshPath"]).is_absolute()
                window.loadFile(window.projectPath)
                loaded = window.scene.objects[0]
                assert loaded.position == [1,2,3] and loaded.rotation == [10,20,30]
                assert loaded.velocity == [2,3,4] and loaded.acceleration == [0,-9.81,0]
                assert loaded.angularVelocity == [0,1,0]
                assert loaded.part.mass == obj.part.mass
                assert loaded.part.properties == obj.part.properties
                print("PASS portable save/reload of transforms, motion, material and custom properties",flush=True)

                with patch("simuo.ui.scene_window.QFileDialog.getOpenFileName",return_value=(str(ROOT / "Assets/cube.simuOPart"),"")):
                    window.importFile()
                assert len(window.scene.objects) == len(window.viewport.renderObjects) == 2
                assert window.scene.objects[-1].part is None
                # Draw legacy last so a missing per-object uniform would turn it cyan.
                frame = window.viewport.grabFramebuffer()
                assert not frame.isNull()
                with patch("simuo.ui.scene_window.QFileDialog.getOpenFileName",return_value=(str(sample),"")):
                    window.importFile()
                assert len(window.scene.objects) == len(window.viewport.renderObjects) == 3
                assert window.scene.objects[-1].name == "Aluminum cube"
                assert window.scene.objects[-1].part is not None
                print("PASS live imports of legacy and JSON parts in one viewport",flush=True)

                invalid = folder / "invalid.simuOPart"
                invalid.write_text('{"format":')
                previous_objects = window.scene.objects[:]
                previous_gpu = window.viewport.renderObjects[:]
                with patch("simuo.ui.scene_window.QFileDialog.getOpenFileName",return_value=(str(invalid),"")), patch("simuo.ui.scene_window.QMessageBox.warning") as warning:
                    window.importFile()
                    warning.assert_called_once()
                assert window.scene.objects == previous_objects
                assert window.viewport.renderObjects == previous_gpu
                startup.write_text(json.dumps({"objects":[{"name":"Broken","meshPath":str(invalid)}]}))
                with patch("simuo.ui.scene_window.QMessageBox.warning") as warning:
                    assert not window.tryLoadFile(startup)
                    warning.assert_called_once()
                assert window.scene.objects == previous_objects
                assert window.viewport.renderObjects == previous_gpu
                print("PASS invalid imports/projects preserve the current scene and GPU objects",flush=True)
                assert not errors, errors
                finished = True
            except BaseException:
                error_hook(*sys.exc_info())
            finally:
                with patch("simuo.ui.scene_window.QMessageBox.question", return_value=QMessageBox.Discard):
                    window.close()
                app.quit()

        QTimer.singleShot(1200,check)
        QTimer.singleShot(15000,app.quit)
        app.exec()
        assert finished and not errors, errors or "GUI check timed out"


if __name__ == "__main__":
    main()
