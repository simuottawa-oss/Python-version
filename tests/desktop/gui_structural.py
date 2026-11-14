"""Desktop check for the startup card, patch picking and real stress texture."""
from pathlib import Path
import tempfile
import traceback
import sys
import time
from unittest.mock import patch
import numpy as np
from PySide6.QtCore import Qt, QPoint, QTimer, QSettings
from PySide6.QtGui import QVector3D
from PySide6.QtWidgets import QApplication, QButtonGroup
from PySide6.QtTest import QTest

from tests.structural_helpers import native_box
from simuo.rendering.context import configure_opengl
from simuo.structural.geometry import load_geometry
from simuo.structural.meshing import generate_mesh, classify_patches
from simuo.structural.models import *
from simuo.structural.solver import solve_analysis
from simuo.ui.structural_window import StructuralWindow
from simuo.ui.startup import SimuOStartMenu
from simuo.project.project_format import read_project


def main():
    configure_opengl()
    app = QApplication([])
    app.setQuitOnLastWindowClosed(False)
    failures = []
    def error_hook(*exception):
        failures.append("".join(traceback.format_exception(*exception)))
        traceback.print_exception(*exception)
    sys.excepthook = error_hook
    with tempfile.TemporaryDirectory(prefix="simuo-structural-desktop-") as directory:
        geometry = load_geometry(native_box(directory, (.2, .2, .2)))
        mesh = generate_mesh(geometry, MeshSettings(.07))
        ends = [tuple(i for i, t in enumerate(geometry.points[geometry.triangles]) if np.allclose(t[:, 0], x)) for x in (-.1, .1)]
        setup = AnalysisSetup(geometry.path, geometry.fingerprint, "m", Material(1e6, 0.), mesh.settings,
                              (ends[0],), (SurfaceLoad(ends[1], "force", (100, 0, 0)),))
        result = solve_analysis(mesh, setup)
        settings = QSettings(str(Path(directory)/"layout.ini"), QSettings.Format.IniFormat)
        with patch("simuo.ui.structural_window.QSettings", return_value=settings):
            window = StructuralWindow()
        window.confirm_unsaved = lambda title: True
        window.geometry, window.patches, window.mesh, window.result = geometry, mesh.patches, mesh, result
        for surface_patch in mesh.patches:
            window.patch_list.addItem(surface_patch.label)
        window.refresh_view()
        window.show()
        def check():
            try:
                viewport = window.viewport
                assert viewport.isValid(), "A desktop OpenGL context is required"
                # Click the center ray; picking must select a visible surface patch.
                QTest.mouseClick(viewport, Qt.MouseButton.LeftButton, pos=QPoint(viewport.width()//2, viewport.height()//2))
                assert window.patch_list.selectedItems(), "Patch click did not select a surface"
                window.view_mode.setCurrentText("Stress")
                frame = viewport.grabFramebuffer()
                red = 0
                for y in range(35, frame.height()-105, 3):
                    for x in range(0, frame.width(), 3):
                        color = frame.pixelColor(x, y)
                        red += color.red() > 240 and color.green() < 30 and color.blue() < 10
                assert red > 100, f"Uniform axial stress did not render red: {red} pixels"
                output = Path(tempfile.gettempdir())/"simuo-structural-stress.png"
                assert frame.save(str(output))
                # Exercise a nonuniform texture field, then a zero field.
                result.averaged_von_mises = (mesh.points[:, 0]+.1)*5
                viewport.refresh()
                gradient_frame = viewport.grabFramebuffer()
                green = yellow = 0
                for y in range(35, gradient_frame.height()-105, 3):
                    for x in range(0, gradient_frame.width(), 3):
                        color = gradient_frame.pixelColor(x, y)
                        green += color.green() > 200 and color.red() < 150 and color.blue() < 10
                        yellow += color.green() > 200 and color.red() > 200 and color.blue() < 10
                assert green > 20 and yellow > 20, f"Missing green/yellow texture samples: {green}/{yellow}"
                result.averaged_von_mises[:] = 0
                viewport.refresh()
                zero = viewport.grabFramebuffer()
                color = zero.pixelColor(zero.width()//2, zero.height()//2)
                assert color.green() > 240 and color.red() < 10 and color.blue() < 10
                # Drive the point-force workflow through actual visible controls.
                window.material_section.combo.setCurrentIndex(window.material_section.combo.findData("aluminum-6061-t6"))
                window.highlight_faces(ends[0])
                window.add_support()
                window.new_load("point")
                QTest.mouseClick(viewport, Qt.MouseButton.LeftButton, pos=QPoint(viewport.width()//2, viewport.height()//2))
                window.force_fields[1].setValue(-100)
                assert window.apply_load_button.isEnabled()
                window.commit_load()
                assert len(window.point_loads) == 1
                def wait():
                    deadline = time.monotonic()+30
                    while window.job.running and time.monotonic() < deadline:
                        app.processEvents()
                        time.sleep(.01)
                    assert not window.job.running, "Desktop analysis worker timed out"
                window.generate_action.trigger()
                wait()
                assert window.result is None
                window.solve_action.trigger()
                wait()
                assert window.mesh is not None
                assert window.point_loads[0].identifier in window.mesh.point_nodes
                assert window.result is not None and window.result.force_error < 1e-8
                # Navigation works with the viewport focused, without RMB.
                viewport.setFocus()
                app.processEvents()
                position = np.array(viewport.camera.position)
                QTest.keyPress(viewport, Qt.Key_Space)
                viewport.navigate()
                QTest.keyRelease(viewport, Qt.Key_Space)
                assert viewport.camera.position.y > position[1]
                position = np.array(viewport.camera.position)
                QTest.keyPress(viewport, Qt.Key_Alt)
                viewport.navigate()
                QTest.keyRelease(viewport, Qt.Key_Alt)
                assert viewport.camera.position.y < position[1]
                assert not viewport.keys and viewport.hasFocus(), "Alt left camera moving or activated the menu"
                mesh_before = window.mesh
                window.force_fields[1].setValue(-150)
                window.force_fields[1].editingFinished.emit()
                QTest.qWait(500)
                assert not window.job.running and window.result is None
                assert window.mesh is mesh_before
                window.solve()
                wait()
                assert window.result is not None
                assert np.isclose(window.result.applied_force[1], -150)
                window.stress_range.setCurrentIndex(1)
                window.stress_max.setValue(window.result.averaged_von_mises.max()/2)
                window.stress_scale_changed()
                viewport.grabFramebuffer()
                assert viewport.saturated > 0
                window.stress_range.setCurrentIndex(0)
                computed_frame = viewport.grabFramebuffer()
                values = window.result.averaged_von_mises
                print(f"Computed display field: {values.min():.6g}..{values.max():.6g}; scaled max {viewport.maximum:.6g}", flush=True)
                assert computed_frame.save("/tmp/simuo-live-computed-stress.png")
                # Fixed-point tools share exact picking and render their own marker.
                window.activate_tool("fixed_point")
                QTest.mouseClick(viewport, Qt.MouseButton.LeftButton, pos=QPoint(viewport.width()//2, viewport.height()//2))
                assert len(viewport.point_supports) == 1
                assert window._selection[0] == "support"
                app.processEvents()
                assert window.grab().save("/tmp/simuo-live-fixed-point.png")
                window.remove_selected()
                assert window.mesh is mesh_before and window.mesh_current()
                window.solve()
                wait()
                target = str(Path(directory)/"point-design.simuO")
                with patch("simuo.ui.structural_window.QFileDialog.getSaveFileName", return_value=(target, "")), patch("simuo.ui.recent_projects.QSettings", return_value=settings), patch("simuo.ui.recent_projects.thumbnail_path", return_value=Path(directory)/"preview.png"):
                    assert window.save()
                assert read_project(target).project_type == "structural"
                window.select_item("material")
                app.processEvents()
                assert window.grab().save(str(Path(tempfile.gettempdir())/"simuo-structural-workspace.png"))
                print(f"PASS desktop point placement, shared material inspector, mesh/solve, .simuO save and stress rendering; {output}", flush=True)
                # Only the selected startup card may have a red outline.
                menu = SimuOStartMenu()
                problems = []
                def cards():
                    dialog = QApplication.activeModalWidget()
                    try:
                        group = dialog.findChild(QButtonGroup)
                        def red_border(card):
                            image = card.grab().toImage()
                            count = 0
                            for x in range(20, image.width()-20):
                                for y in (0, 1, image.height()-2, image.height()-1):
                                    color = image.pixelColor(x, y)
                                    count += color.red() > 150 and color.green() < 110 and color.blue() < 150
                            return count
                        for chosen, other in ((0, 2), (2, 0)):
                            group.button(chosen).setChecked(True)
                            group.button(other).setFocus()
                            QTest.mouseMove(group.button(other), QPoint(30, 30))
                            app.processEvents()
                            counts = [red_border(group.button(i)) for i in range(3)]
                            assert counts[chosen] > 20, counts
                            assert all(count < 5 for i, count in enumerate(counts) if i != chosen), counts
                        assert dialog.grab().save(str(Path(tempfile.gettempdir())/"simuo-startup-scene-picker.png"))
                        print("PASS startup: only the selected card is red while another card is hovered/focused", flush=True)
                    except BaseException:
                        problems.append(traceback.format_exc())
                    finally:
                        dialog.reject()
                QTimer.singleShot(100, cards)
                menu._show_new_scene_options()
                menu.close()
                assert not problems, "\n".join(problems)

            except BaseException:
                failures.append(traceback.format_exc())
                traceback.print_exc()
            finally:
                window.close()
                app.quit()
        QTimer.singleShot(1000, check)
        app.exec()
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
