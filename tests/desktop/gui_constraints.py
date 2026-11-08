"""Desktop selection, line relations, constraint deletion, undo and part save."""
import copy
from pathlib import Path
import sys
import tempfile
import traceback

from PySide6.QtCore import Qt,QTimer
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication
from simuo.ui.parts.feature_editor import FeaturePartEditor
from simuo.parts.part_assets import load_asset


def main():
    app=QApplication([])
    errors,passed=[],[]
    def error(*exc):
        errors.append(''.join(traceback.format_exception(*exc)))
        traceback.print_exception(*exc)
    sys.excepthook=error
    with tempfile.TemporaryDirectory(prefix='simuo constraints desktop ') as directory:
        editor=FeaturePartEditor()
        editor.showMaximized()
        def finish():
            editor.dirty=False
            editor.close()
            app.quit()
        def check():
            try:
                editor.feature_actions['New Sketch'].trigger()
                editor.canvas.fit()
                points=[[-.06,-.04],[.06,-.033],[.062,.04],[-.06,.04]]
                for point in points+[points[0]]:
                    QTest.mouseClick(editor.canvas,Qt.LeftButton,pos=editor.canvas.screen(point).toPoint())
                assert editor.sketch.closed
                menu=next(action.menu() for action in editor.menuBar().actions() if action.text()=='Constraints')
                actions={action.text():action for action in menu.actions()}
                editor.select_line(0)
                actions['Make horizontal'].trigger()
                editor.select_line(1)
                actions['Make vertical'].trigger()
                assert len(editor.sketch.constraints)==2
                print('PASS real line drawing and Horizontal/Vertical menu actions',flush=True)
                editor.select_segments([])
                for index in (0,1):
                    a,b=(editor.sketch.points[i] for i in editor.sketch.edges[index])
                    center=[(a[j]+b[j])/2 for j in (0,1)]
                    QTest.mouseClick(editor.canvas,Qt.LeftButton,Qt.ControlModifier,pos=editor.canvas.screen(center).toPoint())
                assert editor.selected_segments()==[0,1]
                actions['Make equal'].trigger()
                assert abs(editor.sketch.length(0)-editor.sketch.length(1))<1e-8
                editor.select_line(0)
                editor.length.setValue(100)
                editor.dimension_button.click()
                assert abs(editor.sketch.length(1)-.1)<1e-8
                print('PASS Ctrl-click multi-selection, Equal and linked driving dimension',flush=True)
                equal_row=next(row for row in range(editor.constraint_list.count())
                               if editor.constraint_list.item(row).data(Qt.UserRole)==('relation',2))
                before=copy.deepcopy(editor.sketch.points)
                editor.constraint_list.setCurrentRow(equal_row)
                editor.constraint_list.setFocus()
                QTest.keyClick(editor.constraint_list,Qt.Key_Delete)
                assert len(editor.sketch.constraints)==2 and len(editor.sketch.edges)==4
                assert editor.sketch.points==before
                editor.undo()
                assert len(editor.sketch.constraints)==3
                editor.redo()
                assert len(editor.sketch.constraints)==2
                print('PASS Delete releases a selected relation, preserves geometry, and supports undo/redo',flush=True)
                editor.finish_sketch()
                editor.extrude_active(.01)
                path=Path(directory)/'constrained part.simuOPart'
                assert editor._save_to(path) and editor.open_path(path)
                assert len(editor.sketch.constraints)==2
                assert load_asset(path).part.volume>0
                editor.edit_sketch()
                editor.propertiesDock.show()
                editor.canvas.fit()
                app.processEvents()
                assert editor.grab().save(str(Path(tempfile.gettempdir()) / 'simuo-constraints.png'))
                print('PASS constrained feature extrusion and file roundtrip',flush=True)
                passed.append(True)
            except BaseException:
                error(*sys.exc_info())
            finally:
                finish()
        QTimer.singleShot(700,check)
        QTimer.singleShot(20000,finish)
        app.exec()
        assert passed and not errors,errors or 'Constraints desktop test timed out'

if __name__=='__main__':
    main()
