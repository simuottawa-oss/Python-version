"""Startup routing and offscreen workflows using real spawned analysis workers."""
from pathlib import Path
import tempfile
import time
import unittest
from dataclasses import replace
import numpy as np
from unittest.mock import Mock, patch

from PySide6.QtCore import QTimer
from PySide6.QtGui import QVector3D
from PySide6.QtWidgets import QApplication, QButtonGroup, QWidget

from tests.structural_helpers import native_box, end_selection
from simuo.ui.startup import SimuOStartMenu
from simuo.ui.structural_window import StructuralWindow
from simuo.structural.jobs import BackgroundJob
from simuo.structural.models import MeshSettings
from simuo.materials import MaterialDefinition
from PySide6.QtCore import QSettings


class StructuralWorkflowTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.path = native_box(self.temp.name)

    def wait(self, window, timeout=30):
        deadline = time.monotonic()+timeout
        while window.job.running and time.monotonic() < deadline:
            self.app.processEvents()
            time.sleep(.01)
        self.assertFalse(window.job.running, "Worker did not complete")
        window.error.assert_not_called()

    def window(self):
        settings = QSettings(str(Path(self.temp.name)/"layout.ini"), QSettings.Format.IniFormat)
        with patch("simuo.ui.structural_window.QSettings", return_value=settings):
            window = StructuralWindow()
        window.confirm_unsaved = Mock(return_value=True)
        window.error = Mock()
        self.addCleanup(window.close)
        return window

    def choose(self, window, triangles):
        window.highlight_faces(triangles)

    def test_debug_menu_dock_toggles_from_view_menu(self):
        window = self.window()
        dock = window.panel_manager.docks["debug"]
        view_menu = next(
            action.menu()
            for action in window.menuBar().actions()
            if action.text() == "View"
        )
        action = dock.toggleViewAction()

        self.assertIn(action, view_menu.actions())
        self.assertEqual(dock.windowTitle(), "Debug Menu")
        self.assertIsInstance(dock.widget(), QWidget)
        self.assertIsNone(dock.widget().layout())
        self.assertTrue(dock.isHidden())

        action.trigger()
        self.assertFalse(dock.isHidden())
        self.assertTrue(action.isChecked())

        action.trigger()
        self.assertTrue(dock.isHidden())
        self.assertFalse(action.isChecked())

    def solved_bending_window(self):
        window = self.window()
        window.prepare_geometry(self.path)
        self.wait(window)
        window.material_changed(MaterialDefinition("Steel", 2e11, .3, 7850., yield_strength=250e6))
        self.choose(window, end_selection(window.geometry, 0, -.5))
        window.add_support()
        window.new_load("force")
        self.choose(window, end_selection(window.geometry, 0, .5))
        window.force_fields[1].setValue(-1000.)
        window.add_load()
        window.generate_mesh()
        self.wait(window)
        window.solve()
        self.wait(window)
        return window

    def test_deformation_preview_scale_controls_preserve_analysis_and_camera(self):
        window = self.solved_bending_window()
        viewport = window.viewport
        result, mesh = window.result, window.mesh
        original_points, original_u = mesh.points.copy(), result.displacement.copy()
        original_stress = result.averaged_von_mises.copy()
        dirty, undo_index = window.dirty, window.state.undo_stack.index()
        camera = np.array(viewport.camera.position)
        window.view_mode.setCurrentText("Setup")
        window.deformation_action.setChecked(True)
        self.assertTrue(viewport.deformation_enabled)
        self.assertTrue(window.deformed_shape.isChecked())
        self.assertEqual(window.view_mode.currentText(), "Stress")
        self.assertEqual(viewport.tool, "select")
        expected_scale = max(1., .1*np.linalg.norm(np.ptp(mesh.points, axis=0))/np.linalg.norm(original_u, axis=1).max())
        np.testing.assert_allclose(viewport.display_points(), original_points+expected_scale*original_u)
        self.assertAlmostEqual(viewport.deformation_scale, expected_scale)
        np.testing.assert_allclose(viewport.camera.position, camera)
        self.assertIsNone(viewport.pick_surface(viewport.width()/2, viewport.height()/2))
        self.assertIn("Visual magnification", window.deformation_hint.text())
        self.assertIn("fracture", window.deformation_hint.text())
        window.deformation_mode.setCurrentIndex(window.deformation_mode.findData("true"))
        np.testing.assert_allclose(viewport.display_points(), original_points+original_u)
        window.deformation_mode.setCurrentIndex(window.deformation_mode.findData("custom"))
        window.deformation_custom.setValue(20.)
        window.deformation_custom.editingFinished.emit()
        np.testing.assert_allclose(viewport.display_points(), original_points+20*original_u)
        window.view_mode.setCurrentText("Mesh")
        self.assertTrue(viewport.deformation_enabled)
        window.frame_selected()
        projected = np.asarray([viewport.matrices().map(QVector3D(*p)).toTuple()
                                for p in viewport.normalized(viewport.display_points())])
        self.assertTrue((np.abs(projected) <= 1.00001).all())
        window.deformed_shape.setChecked(False)
        self.assertFalse(viewport.deformation_enabled)
        self.assertFalse(window.deformation_action.isChecked())
        np.testing.assert_array_equal(viewport.display_points(), original_points)
        np.testing.assert_array_equal(mesh.points, original_points)
        np.testing.assert_array_equal(result.displacement, original_u)
        np.testing.assert_array_equal(result.averaged_von_mises, original_stress)
        self.assertIs(window.result, result)
        self.assertEqual((window.dirty, window.state.undo_stack.index()), (dirty, undo_index))
        self.assertFalse(window.job.running)
        window.deformation_action.setChecked(True)
        saved = str(Path(self.temp.name)/"bending-preview.simuO")
        with patch("simuo.ui.structural_window.QFileDialog.getSaveFileName", return_value=(saved, "")):
            self.assertTrue(window.save())
        window.open_path(saved)
        self.wait(window)
        self.assertIsNone(window.result)
        self.assertFalse(window.deformation_action.isChecked())
        self.assertFalse(window.deformation_action.isEnabled())
        self.assertEqual(window.deformation_mode.currentData(), "auto")
        self.assertEqual(window.deformation_custom.value(), 1.)

    def test_deformation_preview_editing_invalidation_and_reset(self):
        window = self.solved_bending_window()
        result = window.result
        window.deformation_action.setChecked(True)
        window.material_changed(replace(window.state.inputs.material, yield_strength=None))
        self.assertIs(window.result, result)
        self.assertTrue(window.viewport.deformation_enabled)
        self.assertIn("not supplied", window.stress_hint.text())
        window.stress_range.setCurrentIndex(window.stress_range.findData("auto"))
        self.assertTrue(window.viewport.deformation_enabled)
        window.activate_tool("fixed_point")
        self.assertFalse(window.viewport.deformation_enabled)
        self.assertFalse(window.deformed_shape.isChecked())
        self.assertEqual(window.viewport.tool, "fixed_point")
        self.assertIs(window.result, result)
        window.deformation_action.setChecked(True)
        window.view_mode.setCurrentText("Setup")
        self.assertFalse(window.deformation_action.isChecked())
        window.select_load(window.loads[0].identifier)
        window.deformation_action.setChecked(True)
        window.load_kind.setCurrentIndex(window.load_kind.findData("area"))
        self.assertFalse(window.deformation_action.isEnabled())
        self.assertFalse(window.viewport.deformation_enabled)
        self.assertIs(window.result, result)
        window.cancel_placement()
        self.assertTrue(window.deformation_action.isEnabled())
        window.deformation_action.setChecked(True)
        window.force_fields[1].setValue(-2000.)
        window.force_fields[1].editingFinished.emit()
        self.assertIsNone(window.result)
        self.assertFalse(window.deformation_action.isChecked())
        self.assertFalse(window.deformation_action.isEnabled())
        window.deformation_mode.setCurrentIndex(window.deformation_mode.findData("custom"))
        window.deformation_custom.setValue(15.)
        window.new_analysis()
        self.assertEqual(window.deformation_mode.currentData(), "auto")
        self.assertEqual(window.deformation_custom.value(), 1.)
        self.assertFalse(window.deformed_shape.isChecked())

    def test_viewport_selection_toggle_support_highlight_and_beam_ends(self):
        window = self.window()
        window.prepare_geometry(self.path)
        self.wait(window)
        with self.assertRaisesRegex(ValueError, "Select one or more faces"):
            window.selected_triangles()
        window.select_patch(0, False)
        window.select_patch(1, True)
        self.assertEqual(window.viewport.selected, {0, 1})
        window.select_patch(0, True)
        self.assertEqual(window.selected_triangles(), window.patches[1].triangles)
        window.set_beam_end(True)
        self.assertEqual(window.beam_clamp, window.patches[1].triangles)
        window.select_patch(2, False)
        window.set_beam_end(False)
        self.assertEqual(window.beam_free, window.patches[2].triangles)
        window.add_support()
        support = window.conditions[0]
        window.cancel_placement()
        window.select_patch(0, False)
        window.select_item("support", support.identifier)
        self.assertEqual(window.viewport.selected, {2})
        self.assertEqual(window.selected_triangles(), support.triangles)
        window.new_analysis()
        self.assertFalse(window.viewport.selected)

    def test_structural_card_is_enabled_and_routes_callback(self):
        callback = Mock()
        menu = SimuOStartMenu(on_structural=callback)
        self.addCleanup(menu.close)
        observed = []
        def choose_card():
            dialog = QApplication.activeModalWidget()
            group = dialog.findChild(QButtonGroup)
            observed.append(group.button(2).isEnabled())
            group.button(2).setChecked(True)
            dialog.accept()
        QTimer.singleShot(0, choose_card)
        menu._show_new_scene_options()
        self.assertEqual(observed, [True])
        callback.assert_called_once_with()

    def test_unified_area_preview_edit_conversion_cancel_and_undo(self):
        from simuo.structural.load_regions import area_region
        window = self.window()
        window.prepare_geometry(self.path)
        self.wait(window)
        window.material_section.combo.setCurrentIndex(window.material_section.combo.findData("aluminum-6061-t6"))
        tip = end_selection(window.geometry, 0, .5)
        self.choose(window, end_selection(window.geometry, 0, -.5))
        window.add_support()
        window.generate_mesh()
        self.wait(window)
        mesh = window.mesh
        self.assertEqual(set(window.tool_actions), {"select", "clamp", "pinned_face", "fixed_point", "force"})
        window.activate_tool("force")
        self.assertEqual(window.load_kind.currentData(), "area")
        window.point_picked(tip[0], (.2, .3, .5))
        self.assertFalse(window.area_loads)
        self.assertTrue(window.save_load_button.isEnabled())
        window.area_radius.setValue(.01)
        window.force_fields[1].setValue(-100)
        window.apply_load_draft()
        load = window.area_loads[0]
        self.assertEqual(load.value, (0., -100., 0.))
        self.assertTrue(window.mesh_current())
        self.assertIs(window.mesh, mesh)
        window.solve()
        self.wait(window)
        result = window.result
        window.load_kind.setCurrentIndex(window.load_kind.findData("force"))
        self.assertTrue(window._load_draft)
        self.assertIs(window.result, result)
        self.assertEqual(window.tool_mode.currentData(), "force")
        self.assertIn("moment change", window.load_hint.text())
        window.cancel_placement()
        self.assertEqual(window.area_loads, [load])
        self.assertIs(window.result, result)
        self.assertEqual(window.tool_mode.currentData(), "area")
        window.load_kind.setCurrentIndex(window.load_kind.findData("force"))
        window.apply_load_draft()
        self.assertFalse(window.area_loads)
        self.assertEqual(window.loads[0].identifier, load.identifier)
        self.assertEqual(window.loads[0].value, load.value)
        self.assertIs(window.mesh, mesh)
        self.assertIsNone(window.result)
        window.state.undo_stack.undo()
        self.assertEqual(window.area_loads, [load])
        self.assertEqual(window.load_kind.currentData(), "area")
        window.state.undo_stack.redo()
        self.assertEqual(window.load_kind.currentData(), "force")
        # A face-to-area conversion requires an explicit center.
        window.tool_mode.setCurrentIndex(window.tool_mode.findData("area"))
        self.assertFalse(window.save_load_button.isEnabled())
        window.point_picked(tip[0], (.2, .3, .5))
        self.assertTrue(window.save_load_button.isEnabled())
        window.apply_load_draft()
        self.assertEqual(window.area_loads[0].identifier, load.identifier)
        window.area_radius.setValue(.02)
        window.area_radius.editingFinished.emit()
        self.assertEqual(window.area_loads[0].radius, .02)
        self.assertIs(window.mesh, mesh)
        # Reposition and resize remain independent of embedded point nodes.
        window.begin_point_placement()
        window.point_picked(tip[0], (.3, .3, .4))
        self.assertEqual(window.area_loads[0].barycentric, (.3, .3, .4))
        self.assertTrue(window.mesh_current())
        window.duplicate_load()
        self.assertEqual(len(window.area_loads), 2)
        window.remove_selected()
        self.assertEqual(len(window.area_loads), 1)
        saved = str(Path(self.temp.name)/"area.simuO")
        with patch("simuo.ui.structural_window.QFileDialog.getSaveFileName", return_value=(saved, "")):
            self.assertTrue(window.save())
        expected = window.area_loads[0]
        window.open_path(saved)
        self.wait(window)
        self.assertEqual(window.area_loads, [expected])

    def test_point_conversion_pressure_input_and_mode_sync(self):
        window = self.window()
        window.prepare_geometry(self.path)
        self.wait(window)
        tip = end_selection(window.geometry, 0, .5)
        window.new_load("point")
        window.point_picked(tip[0], (.2, .3, .5))
        window.force_fields[1].setValue(-100)
        window.commit_load()
        point = window.point_loads[0]
        window.tool_mode.setCurrentIndex(window.tool_mode.findData("area"))
        self.assertTrue(window.save_load_button.isEnabled())
        window.apply_load_draft()
        self.assertFalse(window.point_loads)
        self.assertEqual(window.area_loads[0].identifier, point.identifier)
        window.state.undo_stack.undo()
        self.assertEqual(window.point_loads, [point])
        window.state.undo_stack.redo()
        window.tool_input.setCurrentIndex(window.tool_input.findData("pressure"))
        self.assertTrue(window._load_draft)
        self.assertEqual(window.pressure.value(), 0.)
        self.assertEqual(window.force_fields[1].value(), 0.)
        self.assertFalse(window.save_load_button.isEnabled())
        window.pressure.setValue(12.)
        window.pressure_units.setCurrentIndex(window.pressure_units.findData(1e6))
        self.assertAlmostEqual(window.pressure.value(), .012)
        window.pressure_direction.setCurrentIndex(1)
        window.apply_load_draft()
        self.assertEqual(window.area_loads[0].kind, "pressure")
        self.assertEqual(window.area_loads[0].value, (-12000.,))
        window.load_kind.setCurrentIndex(window.load_kind.findData("point"))
        self.assertEqual(window.load_kind.currentData(), "area")
        self.assertIn("Total force", window.statusBar().currentMessage())
        window.load_input.setCurrentIndex(window.load_input.findData("force"))
        window.force_fields[0].setValue(20.)
        window.load_kind.setCurrentIndex(window.load_kind.findData("point"))
        window.apply_load_draft()
        self.assertEqual(window.point_loads[0].identifier, point.identifier)
        self.assertEqual(window.point_loads[0].force, (20., 0., 0.))

    def test_strength_only_edits_preserve_results_and_running_solver(self):
        window = self.window()
        window.prepare_geometry(self.path)
        self.wait(window)
        material = MaterialDefinition("Custom", 2e11, .3, 2700., yield_strength=1., ultimate_tensile_strength=2.)
        window.material_changed(material)
        self.choose(window, end_selection(window.geometry, 0, -.5))
        window.add_support()
        window.new_load("force")
        tip = end_selection(window.geometry, 0, .5)
        index = next(i for i, patch in enumerate(window.patches) if patch.triangles == tip)
        window.select_patch(index, False)
        window.force_fields[0].setValue(1000)
        window.commit_load()
        window.generate_mesh()
        self.wait(window)
        window.solve()
        revision = window.job.revision
        process = window.job.process
        changed = replace(material, yield_strength=200e6, ultimate_tensile_strength=300e6)
        window.material_changed(changed)
        self.assertEqual(window.job.revision, revision)
        self.assertIs(window.job.process, process)
        self.wait(window)
        result = window.result
        self.assertIsNotNone(result)
        self.assertEqual(window.viewport.maximum, 200e6)
        raw = result.averaged_von_mises.copy()
        window.material_changed(material)
        self.assertIs(window.result, result)
        self.assertIn("elastic range", window.report.text())
        self.assertEqual(window.viewport.maximum, 1.)
        window.stress_range.setCurrentIndex(window.stress_range.findData("uts"))
        self.assertEqual(window.viewport.maximum, 2.)
        self.assertIn("does not predict fracture", window.report.text())
        window.stress_range.setCurrentIndex(window.stress_range.findData("custom"))
        window.stress_max.setValue(4.)
        window.stress_scale_changed()
        self.assertEqual(window.viewport.maximum, 4e6)
        np.testing.assert_array_equal(result.averaged_von_mises, raw)
        self.assertIs(window.result, result)

    def test_launcher_structural_and_saved_analysis_routing(self):
        from simuo.app import main
        from simuo.structural.persistence import save_analysis
        from simuo.structural.geometry import load_geometry
        from simuo.structural.models import AnalysisSetup, Material
        geometry = load_geometry(self.path)
        saved = str(Path(self.temp.name)/"example.simuO")
        save_analysis(saved, AnalysisSetup(geometry.path, geometry.fingerprint, "m", Material(2e11, .3), MeshSettings(.1)))
        for arguments, target in ((["--structural"], None), (["--structural", str(self.path)], str(self.path)), ([saved], saved)):
            with patch("sys.argv", ["simuo", *arguments]), patch("simuo.ui.structural_window.run_structural", return_value=0) as run:
                self.assertEqual(main(), 0)
                run.assert_called_once_with(target)
        with patch("sys.argv", ["simuo"]), patch("simuo.app.startup_menu", return_value=("structural", None)), patch("simuo.ui.structural_window.run_structural", return_value=0) as run:
            self.assertEqual(main(), 0)
            run.assert_called_once_with(None)

    def test_import_setup_mesh_solve_save_reopen_and_invalidation(self):
        window = self.window()
        window.prepare_geometry(self.path)
        self.wait(window)
        clamp, tip = [end_selection(window.geometry, 0, x) for x in (-.5, .5)]
        window.material_changed(MaterialDefinition("Custom", 2e11, 0., 2700.))
        window.size.setValue(.08)
        self.choose(window, clamp)
        window.add_support()
        self.choose(window, tip)
        window.load_kind.setCurrentIndex(window.load_kind.findData("force"))
        window.force_fields[0].setValue(1000)
        window.add_load()
        window.generate_mesh()
        self.wait(window)
        self.assertIsNotNone(window.mesh)
        window.solve()
        self.wait(window)
        self.assertAlmostEqual(window.result.displacement[:, 0].max(), 5e-7, places=10)
        saved = str(Path(self.temp.name)/"saved.simuO")
        with patch("simuo.ui.structural_window.QFileDialog.getSaveFileName", return_value=(saved, "")):
            window.save()
        self.assertTrue(Path(saved).is_file())
        mesh = window.mesh
        window.material_changed(MaterialDefinition("Custom", 2e11, .1, 2700.))
        self.assertIsNone(window.result)
        self.assertIs(window.mesh, mesh)
        window.size.setValue(.05)
        window.mesh_size_changed()
        self.assertIsNone(window.mesh)
        window.open_path(saved)
        self.wait(window)
        self.assertEqual(window.supports, [clamp])
        self.assertEqual(window.loads[0].value, (1000., 0., 0.))
        self.assertIsNone(window.mesh)
        self.assertIsNone(window.result)

    def test_point_tool_edit_reposition_undo_and_common_project_save(self):
        from dataclasses import replace
        from simuo.project.project_format import read_project
        window = self.window()
        window.prepare_geometry(self.path)
        self.wait(window)
        window.material_section.combo.setCurrentIndex(window.material_section.combo.findData("aluminum-6061-t6"))
        clamp = end_selection(window.geometry, 0, -.5)
        self.choose(window, clamp)
        window.add_support()
        window.new_load("point")
        hit = window.viewport.pick_surface(window.viewport.width()/2, window.viewport.height()/2)
        self.assertIsNotNone(hit)
        window.viewport.point_picked.emit(hit[0], hit[1])
        window.force_fields[1].setValue(-100.)
        self.assertTrue(window.apply_load_button.isEnabled())
        window.commit_load()
        self.assertEqual(len(window.point_loads), 1)
        self.assertEqual(window.viewport.tool, "point")
        load = window.point_loads[0]
        window.generate_mesh()
        self.wait(window)
        mesh = window.mesh
        self.assertIn(load.identifier, mesh.point_nodes)
        window.solve()
        self.wait(window)
        self.assertLess(window.result.force_error, 1e-8)
        window.force_fields[1].setValue(-200.)
        window.commit_load()
        self.assertIs(window.mesh, mesh)
        self.assertIsNone(window.result)
        self.assertEqual(window.point_loads[0].force[1], -200.)
        window.begin_point_placement()
        window.point_picked(load.source_triangle, (.1, .2, .7))
        window.commit_load()
        self.assertIs(window.mesh, mesh)
        self.assertFalse(window.mesh_current())
        self.assertEqual(window.point_loads[0].barycentric, (.1, .2, .7))
        window.state.undo_stack.undo()
        self.assertEqual(window.point_loads[0].barycentric, load.barycentric)
        self.assertEqual(window.force_fields[1].value(), -200.)
        saved = str(Path(self.temp.name)/"point-design.simuO")
        with patch("simuo.ui.structural_window.QFileDialog.getSaveFileName", return_value=(saved, "")):
            self.assertTrue(window.save())
        self.assertEqual(read_project(saved).project_type, "structural")
        window.open_path(saved)
        self.wait(window)
        self.assertEqual(window.point_loads[0].identifier, load.identifier)
        self.assertEqual(window.point_loads[0].barycentric, load.barycentric)
        self.assertEqual(window.state.inputs.material.preset_id, "aluminum-6061-t6")
        self.assertIsNone(window.mesh)

    def test_pressure_controls_and_escape_cancel_placement(self):
        window = self.window()
        window.prepare_geometry(self.path)
        self.wait(window)
        tip = end_selection(window.geometry, 0, .5)
        window.new_load("pressure")
        index = next(i for i, patch in enumerate(window.patches) if set(patch.triangles) == set(tip))
        window.select_patch(index, False)
        self.assertEqual(window.loads[0].value, (0.,))
        window.pressure.setValue(12.)
        window.pressure_direction.setCurrentIndex(1)
        window.commit_load()
        self.assertEqual(window.loads[0].value, (-12000.,))
        self.assertEqual(window.loads[0].kind, "pressure")
        self.assertFalse(window.point_loads)
        window.new_load("point")
        window.point_picked(0, (.2, .3, .5))
        window.force_fields[0].setValue(10)
        window.cancel_placement()
        self.assertIsNone(window.viewport.draft_point)
        self.assertEqual(window.viewport.tool, "select")
        self.assertEqual(len(window.point_loads), 1)

    def test_automatic_support_placement_and_manual_results(self):
        from dataclasses import replace
        window = self.window()
        window.prepare_geometry(self.path)
        self.wait(window)
        self.assertFalse(window.solve_action.isEnabled())
        window.material_changed(MaterialDefinition("Steel", 2e11, .3, 7800.))
        window.size.setValue(.08)
        clamp = end_selection(window.geometry, 0, -.5)
        clamp_index = next(i for i, p in enumerate(window.patches) if p.triangles == clamp)
        window.activate_tool("clamp")
        window.select_patch(clamp_index, False)
        self.assertEqual(len(window.conditions), 1)
        support = window.conditions[0]
        self.assertEqual(window._selection, ("support", support.identifier))
        self.assertEqual(window.viewport.tool, "clamp")
        window.select_patch(clamp_index, False)
        self.assertEqual(len(window.conditions), 1)
        window.new_load("point")
        tip = end_selection(window.geometry, 0, .5)
        window.point_picked(tip[0], (1/3, 1/3, 1/3))
        self.assertEqual(window.point_loads[0].force, (0., 0., 0.))
        window.force_fields[1].setValue(-100.)
        count = window.state.undo_stack.count()
        window.force_fields[1].editingFinished.emit()
        self.assertEqual(window.state.undo_stack.count(), count+1)
        window.force_fields[1].editingFinished.emit()
        self.assertEqual(window.state.undo_stack.count(), count+1)
        window.generate_action.trigger()
        self.wait(window)
        self.assertIsNotNone(window.mesh)
        self.assertIsNone(window.result)
        self.assertFalse(window.generate_action.isEnabled())
        window.solve_action.trigger()
        self.wait(window)
        self.assertIsNotNone(window.result)
        mesh = window.mesh
        self.assertTrue(window.solve_action.isEnabled())
        with patch.object(window.job, "start", wraps=window.job.start) as start:
            window.force_fields[1].setValue(-200.)
            window.force_fields[1].editingFinished.emit()
            # Pump events longer than the old auto-solve debounce interval.
            deadline = time.monotonic()+.7
            while time.monotonic() < deadline:
                self.app.processEvents()
                time.sleep(.01)
            start.assert_not_called()
        self.assertIs(window.mesh, mesh)
        self.assertIsNone(window.result)
        self.assertEqual(window.point_loads[0].force[1], -200.)
        self.assertIn("Choose Run Analysis", window.report.text())
        window.solve()
        self.wait(window)
        self.assertIsNotNone(window.result)
        self.assertAlmostEqual(window.result.applied_force[1], -200.)
        result = window.result
        window.load_name.setText("Renamed")
        window.load_name.editingFinished.emit()
        self.assertIs(window.result, result)
        # Meshing finishes without calculating, including when inputs are edited.
        window.size.setValue(.09)
        window.generate_action.trigger()
        self.assertEqual(window.job.operation, "mesh")
        window.force_fields[1].setValue(-300.)
        window.force_fields[1].editingFinished.emit()
        self.wait(window)
        self.assertIsNone(window.result)
        self.assertTrue(window.mesh_current())
        mesh = window.mesh
        window.duplicate_load()
        self.assertEqual(len(window.point_loads), 2)
        self.assertTrue(window.mesh_current())
        window.select_item("support", support.identifier)
        window.support_kind.setCurrentIndex(window.support_kind.findData("pinned_face"))
        self.assertIs(window.mesh, mesh)
        self.assertFalse(window.solve_action.isEnabled())
        self.assertIn("3 rigid-body motions", window.readiness.text())
        window.support_kind.setCurrentIndex(window.support_kind.findData("fixed_face"))
        self.assertTrue(window.solve_action.isEnabled())
        window.activate_tool("fixed_point")
        load = window.point_loads[0]
        window.point_picked(load.source_triangle, load.barycentric)
        self.assertTrue(window.mesh_current())
        self.assertEqual(window.conditions[-1].kind, "fixed_point")
        window.point_picked(load.source_triangle, load.barycentric)
        self.assertEqual(len(window.conditions), 2)
        window.remove_selected()
        self.assertTrue(window.mesh_current())
        self.assertIs(window.mesh, mesh)

    def test_generate_mesh_does_not_require_analysis_setup_or_run_calculations(self):
        window = self.window()
        window.prepare_geometry(self.path)
        self.wait(window)
        self.assertEqual(window.generate_action.text(), "Generate Mesh")
        self.assertTrue(window.generate_action.isEnabled())
        self.assertFalse(window.solve_action.isEnabled())
        with patch.object(window.job, "start", wraps=window.job.start) as start:
            window.generate_action.trigger()
            self.wait(window)
            self.assertEqual([call.args[0] for call in start.call_args_list], ["mesh"])
        self.assertIsNotNone(window.mesh)
        self.assertIsNone(window.result)
        self.assertFalse(window.generate_action.isEnabled())
        self.assertFalse(window.solve_action.isEnabled())

    def test_face_tools_place_extend_and_duplicate_without_confirmation(self):
        window = self.window()
        window.prepare_geometry(self.path)
        self.wait(window)
        window.new_load("force")
        window.select_patch(0, False)
        self.assertEqual(window.loads[0].value, (0., 0., 0.))
        identity = window.loads[0].identifier
        window.select_patch(1, True)
        self.assertEqual(len(window.loads), 1)
        self.assertEqual(window.loads[0].identifier, identity)
        self.assertEqual(set(window.loads[0].triangles), set(window.patches[0].triangles) | set(window.patches[1].triangles))
        window.select_patch(2, False)
        self.assertEqual(len(window.loads), 2)
        window.select_patch(2, False)
        self.assertEqual(len(window.loads), 2)
        window.duplicate_load()
        self.assertEqual(len(window.loads), 3)
        self.assertEqual(window.loads[-1].triangles, window.loads[-2].triangles)
        window.activate_tool("pinned_face")
        window.select_patch(0, False)
        window.select_patch(1, True)
        self.assertEqual(len(window.conditions), 1)
        self.assertEqual(window.conditions[0].kind, "pinned_face")
        self.assertEqual(len(window.conditions[0].triangles), 4)
        window.cancel_placement()
        self.assertEqual(window.viewport.tool, "select")

    def test_other_project_type_opens_without_replacing_design(self):
        import json
        window = self.window()
        window.prepare_geometry(self.path)
        self.wait(window)
        geometry = window.geometry
        scene = Path(self.temp.name)/"scene.simuO"
        scene.write_text(json.dumps({"format": ".simuO", "version": 2, "project_type": "scene", "objects": []}))
        with patch("simuo.ui.project_open.open_project_window") as opened:
            window.open_path(scene)
            opened.assert_called_once_with(scene, window)
        self.assertIs(window.geometry, geometry)
        self.assertFalse(window.mesh)

    def test_cancellation_close_failure_and_stale_revision(self):
        window = self.window()
        window.prepare_geometry(self.path)
        window.cancel()
        self.assertFalse(window.job.running)
        window.prepare_geometry(self.path)
        window.close()
        self.assertFalse(window.job.running)
        job = BackgroundJob()
        self.addCleanup(job.cancel)
        job.start("prepare", str(self.path), "m", MeshSettings(.1))
        # A newer input revision must prevent this prepared geometry being accepted.
        job.revision += 1
        messages = []
        deadline = time.monotonic()+20
        while job.running and time.monotonic() < deadline:
            messages.extend(job.poll())
            time.sleep(.01)
        self.assertFalse(job.running)
        self.assertFalse(any(kind == "result" for kind, _ in messages))
        job.start("prepare", str(self.path.parent/"missing.simuOPart"), "m", MeshSettings(.1))
        errors = []
        deadline = time.monotonic()+20
        while job.running and time.monotonic() < deadline:
            errors.extend(value for kind, value in job.poll() if kind == "error")
            time.sleep(.01)
        self.assertTrue(errors)
        self.assertIn("FileNotFoundError", errors[0])
