"""Shared material-inspector library actions without writing real user data."""
from dataclasses import replace
from pathlib import Path
import tempfile
import unittest
from unittest.mock import Mock, patch
from PySide6.QtWidgets import QApplication, QMessageBox
from simuo.materials import MaterialCatalog, MaterialDefinition, MaterialRecord, PRESETS, load_material, save_material
from simuo.ui.material_inspector import MaterialInspector


class LibraryInspectorTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.first = MaterialInspector(MaterialCatalog(self.root/'library'))
        self.second = MaterialInspector(MaterialCatalog(self.root/'library'))
        self.addCleanup(self.first.close)
        self.addCleanup(self.second.close)

    def test_save_refreshes_both_inspectors_without_assigning(self):
        self.first.set_material(PRESETS[0])
        self.first.edit_as_custom()
        original = self.first.assignment
        emitted = Mock()
        self.first.material_changed.connect(emitted)
        self.first.save_to_library()
        self.assertEqual(self.first.assignment, original)
        emitted.assert_not_called()
        saved = next(iter(self.first.catalog.personal.values()))
        self.assertEqual(saved.material.yield_strength, PRESETS[0].yield_strength)
        self.assertEqual(saved.material.ultimate_tensile_strength, PRESETS[0].ultimate_tensile_strength)
        self.assertGreaterEqual(self.second.combo.findData(saved.material.preset_id), 0)
        self.assertIsNone(self.second.assignment)
        self.second.combo.setCurrentIndex(self.second.combo.findData(saved.material.preset_id))
        self.assertEqual(self.second.assignment, saved.material)

    def test_edit_export_import_keeps_strengths_and_validation(self):
        custom = MaterialDefinition('Custom alloy', 10e9, .25, 1000., yield_strength=200e6, ultimate_tensile_strength=300e6)
        self.first.set_material(custom)
        self.first.yield_strength.setValue(350.)
        with patch('simuo.ui.material_inspector.QMessageBox.warning') as warning:
            self.first.save_to_library()
            warning.assert_called_once()
        self.assertFalse(self.first.catalog.personal)
        self.first.yield_strength.setValue(250.)
        path = self.root/'export.json'
        with patch('simuo.ui.material_inspector.QFileDialog.getSaveFileName', return_value=(str(path),'')):
            self.first.export_material()
        self.assertEqual(load_material(path).material.yield_strength, 250e6)
        with patch('simuo.ui.material_inspector.QFileDialog.getOpenFileName', return_value=(str(path),'')):
            self.second.import_material()
        self.assertEqual(len(self.first.catalog.personal), 1)
        self.assertEqual(len(self.second.catalog.personal), 1)
        self.assertEqual(self.first.assignment, custom)

    def test_reloaded_library_does_not_rewrite_old_project_snapshot(self):
        saved = self.first.catalog.save(MaterialRecord(PRESETS[0]))
        self.first.reload_catalog()
        self.first.set_material(saved.material)
        self.first.catalog.save(replace(saved, material=replace(saved.material, density=1.)), replace_id=saved.material.preset_id)
        self.first.reload_catalog()
        self.assertEqual(self.first.assignment, saved.material)
        self.assertEqual(self.first.combo.currentData(), 'custom')

    def test_structural_project_keeps_personal_material_strengths(self):
        from tests.structural_helpers import native_box
        from simuo.structural.geometry import load_geometry
        from simuo.structural.persistence import save_analysis, load_analysis
        from simuo.ui.structural_window import StructuralWindow
        from PySide6.QtCore import QSettings
        settings = QSettings(str(self.root/'layout.ini'), QSettings.IniFormat)
        with patch('simuo.ui.structural_window.QSettings', return_value=settings):
            window = StructuralWindow()
        window.confirm_unsaved = Mock(return_value=True)
        self.addCleanup(window.close)
        window.geometry = load_geometry(native_box(self.root))
        personal = self.first.catalog.save(MaterialRecord(PRESETS[0]))
        window.material_changed(personal.material)
        path = self.root/'design.simuO'
        save_analysis(path, window.setup())
        setup = load_analysis(path)
        self.assertEqual(setup.material.yield_strength, personal.material.yield_strength)
        self.assertEqual(setup.material.ultimate_tensile_strength, personal.material.ultimate_tensile_strength)
        window.pending_setup = setup
        window.analysis_path = str(path)
        with patch('simuo.ui.structural_window.remember_project'):
            window.apply_prepared_geometry()
        self.assertEqual(window.state.inputs.material, personal.material)
