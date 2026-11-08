"""Desktop pointer movement, explicit constraint preservation and cancellation."""
import copy
from pathlib import Path
import sys
import tempfile
import traceback

from PySide6.QtCore import Qt, QTimer
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication
from simuo.ui.parts.feature_editor import FeaturePartEditor
from simuo.parts.sketch_geometry import Sketch


def main():
    app = QApplication([])
    editor = FeaturePartEditor()
    editor.new_sketch()
    editor.commit(Sketch([[-.05,0],[.05,0],[.05,.07]], False, [None,None]))
    editor.select_mode()
    editor.show()
    errors, done = [], []
    def error(*exc):
        errors.append("".join(traceback.format_exception(*exc)))
        traceback.print_exception(*exc)
    sys.excepthook = error

    def drag(index, point, cancel=False):
        canvas = editor.canvas
        QTest.mousePress(canvas, Qt.LeftButton, pos=canvas.screen(editor.sketch.points[index]).toPoint())
        QTest.mouseMove(canvas, canvas.screen(point).toPoint(), delay=50)
        app.processEvents()
        if cancel:
            QTest.keyClick(canvas, Qt.Key_Escape)
        QTest.mouseRelease(canvas, Qt.LeftButton, pos=canvas.screen(point).toPoint())
        app.processEvents()

    def check():
        try:
            editor.canvas.fit()
            before = editor.model.geometry()
            history = len(editor.history)
            drag(1, [.075,.025])
            assert abs(editor.sketch.points[1][0]-.075) < 1/editor.canvas.zoom
            assert abs(editor.sketch.points[1][1]-.025) < 1/editor.canvas.zoom
            assert len(editor.history) == history+1
            editor.undo()
            assert editor.model.geometry() == before
            editor.redo()
            print("PASS native mouse drag moves free point and supports single-step undo/redo", flush=True)

            editor.undo()
            editor.select_line(0)
            editor.apply_geometric_constraint("horizontal")
            assert abs(editor.sketch.points[1][1]-editor.sketch.points[0][1]) < 1e-8
            editor.canvas.fit()
            drag(1, [.08,.03])
            assert abs(editor.sketch.points[1][0]-.08) < 1/editor.canvas.zoom
            assert abs(editor.sketch.points[1][1]-editor.sketch.points[0][1]) < 1e-8
            snapshot = copy.deepcopy(editor.model.geometry())
            drag(1, [.09,.04], cancel=True)
            assert editor.model.geometry() == snapshot
            print("PASS horizontal relation limits drag; Esc cancels without changing the model", flush=True)
            with tempfile.TemporaryDirectory() as folder:
                path = Path(folder)/"dragged.simuOPart"
                assert editor._save_to(path)
                assert editor.open_path(path)
                assert editor.model.geometry() == snapshot
            done.append(True)
            print("PASS moved point coordinates and constraints survive native save/reopen", flush=True)
        except BaseException:
            error(*sys.exc_info())
        finally:
            editor.dirty = False
            editor.close()
            app.quit()
    QTimer.singleShot(500, check)
    QTimer.singleShot(15000, app.quit)
    app.exec()
    assert done and not errors, errors or "Point drag test timed out"


if __name__ == "__main__":
    main()
