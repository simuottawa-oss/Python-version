"""Startup routing and offscreen workflows using real spawned analysis workers."""
from pathlib import Path
import tempfile
import time
import unittest
from unittest.mock import Mock, patch

from PySide6.QtCore import QTimer
from PySide6.QtWidgets import QApplication, QButtonGroup

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
        window.patch_list.clearSelection()
        for i, patch in enumerate(window.patches):
            if set(patch.triangles) <= set(triangles):
                window.patch_list.item(i).setSelected(True)

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
