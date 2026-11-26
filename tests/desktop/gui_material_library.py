"""Desktop check of the shared Custom inspector and persistent JSON library."""
from pathlib import Path
import tempfile
from unittest.mock import patch
from PySide6.QtCore import Qt
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QWidget, QHBoxLayout
from simuo.materials import MaterialCatalog, load_material
from simuo.ui.material_inspector import MaterialInspector
from simuo.ui.theme import load_stylesheet


def main():
    app = QApplication.instance() or QApplication([])
    with tempfile.TemporaryDirectory(prefix='simuo-material-desktop-') as directory:
        root = Path(directory)
        host = QWidget()
        host.setWindowTitle('Material Library Check')
        host.setStyleSheet(load_stylesheet('main_window')+load_stylesheet('properties'))
        layout = QHBoxLayout(host)
        first, second = [MaterialInspector(MaterialCatalog(root/'library')) for _ in range(2)]
        layout.addWidget(first)
        layout.addWidget(second)
        host.resize(760, 720)
        host.show()
        try:
            QTest.qWait(150)
            first.combo.setCurrentIndex(first.combo.findData('custom'))
            first.name.setFocus()
            first.name.selectAll()
            QTest.keyClicks(first.name, 'Desktop alloy')
            QTest.keyClick(first.name, Qt.Key_Return)
            for control, value in ((first.young,'70'),(first.poisson,'0.3'),(first.density,'2700'),
                                   (first.yield_strength,'240'),(first.ultimate_tensile_strength,'260')):
                control.setFocus()
                control.lineEdit().selectAll()
                QTest.keyClicks(control.lineEdit(), value)
                QTest.keyClick(control, Qt.Key_Return)
            QTest.mouseClick(first.save_button, Qt.LeftButton)
            QTest.qWait(50)
            saved = next(iter(first.catalog.personal.values()))
            assert saved.material.yield_strength == 240e6
            assert saved.material.ultimate_tensile_strength == 260e6
            second.combo.setCurrentIndex(second.combo.findData(saved.material.preset_id))
            assert second.assignment == saved.material
            exported = root/'alloy.json'
            with patch('simuo.ui.material_inspector.QFileDialog.getSaveFileName', return_value=(str(exported),'')):
                QTest.mouseClick(first.export_button, Qt.LeftButton)
            assert load_material(exported).material.yield_strength == 240e6
            with patch('simuo.ui.material_inspector.QFileDialog.getOpenFileName', return_value=(str(exported),'')):
                QTest.mouseClick(second.import_button, Qt.LeftButton)
            assert len(second.catalog.personal) == 1
            assert MaterialCatalog(root/'library').get(saved.material.preset_id) == saved
            assert host.grab().save('/tmp/simuo-material-library.png')
            print('PASS material Custom controls, exact strengths, save, cross-inspector refresh, JSON import/export and restart persistence', flush=True)
        finally:
            host.close()
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
