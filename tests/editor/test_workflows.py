"""Check object editing across panels, scene files, and scene replacement."""

import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from PySide6.QtCore import QLocale, QPoint, QPointF, QSettings, Qt
from PySide6.QtGui import QFocusEvent, QWheelEvent
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QMessageBox

from tests.support.viewports import FakeViewport
from tests.support.qt import get_application
from tests.support.paths import ROOT

from simuo.scene.model import Scene, SceneObject
from simuo.ui.main_window import SimuOMainWindow


class EditorWorkflow(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = get_application()

    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.folder = Path(self.directory.name)
        self.settings = QSettings(str(self.folder / "layout.ini"), QSettings.IniFormat)
        self.scene = Scene()
        # Duplicate names and a mesh named Axis must remain distinct editable objects.
        for name in ("Cube", "Cube", "Axis"):
            self.scene.addObject(SceneObject(name, ROOT / "Assets/cube.simuOPart"))
        self.scene.objects[1].position = [1.123456, 2.0, 3.0]
        with patch("simuo.ui.main_window.OpenGLViewport", FakeViewport), patch("simuo.ui.docking.QSettings", return_value=self.settings):
            self.window = SimuOMainWindow(scene=self.scene)
        self.addCleanup(self.close_editor)
        self.window.show()
        self.window.raise_()
        self.window.activateWindow()
        if self.app.platformName() != "offscreen":
            self.assertTrue(QTest.qWaitForWindowActive(self.window, 2000))
        self.app.processEvents()
        self.state = self.window.editor_state
        self.hierarchy = self.window.panel_manager.docks["object_hierarchy"].widget()
        self.properties = self.window.panel_manager.docks["properties"].widget()

    def close_editor(self):
        self.scene.dirty = False
        self.window.close()

    def select_second(self):
        self.hierarchy.rows[self.scene.objects[1].identifier].name_button.click()
        return self.scene.objects[1]

    def test_selection_does_not_edit_or_round_scene_values(self):
        self.assertEqual(self.properties.stack.currentIndex(), 0)
        self.assertFalse(self.properties.scroll.isEnabled())
        self.assertEqual(len(self.hierarchy.rows), 3)
        obj = self.select_second()
        self.assertIs(self.state.selected_object, obj)
        self.assertEqual(self.properties.name_input.text(), "Cube")
        self.assertEqual(self.properties.transform_inputs["position"][0].value(), 1.123)
        self.state.select(self.scene.objects[0].identifier)
        self.assertEqual(list(self.hierarchy.rows).index(self.hierarchy.selected_id), 0)
        self.assertEqual(obj.position[0], 1.123456)
        self.assertFalse(self.scene.dirty)

    def test_transform_edits_target_the_selected_object_and_repaint(self):
        obj = self.select_second()
        updates = self.window.viewport.update_count
        for attribute, axis, value in (("position", 0, 9.125), ("rotation", 1, -45.0), ("scale", 2, 2.5)):
            self.properties.transform_inputs[attribute][axis].setValue(value)
            self.assertEqual(getattr(obj, attribute)[axis], value)
        self.assertEqual(self.scene.objects[0].position, [0.0, 0.0, 0.0])
        self.assertEqual(self.scene.objects[0].scale, [1.0, 1.0, 1.0])
        self.assertTrue(self.scene.dirty)
        self.assertTrue(self.window.isWindowModified())
        self.assertGreater(self.window.viewport.update_count, updates)

    def test_typing_a_transform_commits_without_opening_a_dialog(self):
        obj = self.select_second()
        field = self.properties.transform_inputs["position"][0]
        field.setFocus()
        field.selectAll()
        QTest.keyClicks(field, "-12.5")
        self.assertEqual(obj.position[0], 1.123456)
        QTest.keyClick(field, Qt.Key_Return)
        self.assertEqual(obj.position[0], -12.5)
        self.assertIsNone(self.app.activeModalWidget())

    def test_renaming_from_either_panel_preserves_selection(self):
        obj = self.select_second()
        identifier = obj.identifier
        self.properties.name_input.setText("Renamed Cube")
        self.properties.name_input.editingFinished.emit()
        self.assertEqual(self.hierarchy.rows[self.scene.objects[1].identifier].name_button.full_name, "Renamed Cube")
        row = self.hierarchy.rows[identifier]
        row.begin_rename()
        row.name_edit.setText("From hierarchy")
        row.finish_rename()
        self.assertEqual(self.properties.name_input.text(), "From hierarchy")
        self.assertEqual(obj.identifier, identifier)
        self.assertIs(self.state.selected_object, obj)
        row.begin_rename()
        row.name_edit.setText("   ")
        row.finish_rename()
        self.assertEqual(obj.name, "From hierarchy")
        self.assertEqual(self.hierarchy.rows[self.scene.objects[1].identifier].name_button.full_name, "From hierarchy")

    def test_switching_selection_finishes_the_edit_on_the_previous_object(self):
        obj = self.select_second()
        field = self.properties.transform_inputs["position"][0]
        field.setFocus()
        field.selectAll()
        QTest.keyClicks(field, "42.5")
        button = self.hierarchy.rows[self.scene.objects[0].identifier].name_button
        QTest.mouseClick(button, Qt.LeftButton)
        self.assertIs(self.state.selected_object, self.scene.objects[0])
        self.assertEqual(obj.position[0], 42.5)
        self.assertEqual(self.scene.objects[0].position[0], 0.0)
        self.assertEqual(self.properties.transform_inputs["position"][0].value(), 0.0)

    def test_toolbar_switches_real_modes_without_opening_properties(self):
        self.select_second()
        dock = self.window.panel_manager.docks["properties"]
        dock.hide()
        for tool in ("move", "rotate", "scale", "select"):
            self.window.toolActions[tool].trigger()
            self.assertEqual(self.state.active_tool, tool)
            self.assertEqual(self.window.viewport.active_tool, tool)
            self.assertTrue(self.window.toolActions[tool].isChecked())
            self.assertFalse(dock.isVisible())
        self.assertFalse(self.scene.dirty)
        self.assertEqual(self.state.undo_stack.count(), 0)

    def test_viewport_toolbar_options_and_visibility(self):
        toolbar = self.window.viewport_tools
        self.assertIs(toolbar.parentWidget(), self.window.viewport)
        self.assertTrue(all(action.isEnabled() for action in self.window.toolActions.values()))
        self.assertFalse(self.window.frameSelectedAction.isEnabled())
        self.assertTrue(self.window.frameSceneAction.isEnabled())
        self.window.toolActions['move'].trigger()
        toolbar.orientation_input.setCurrentIndex(1)
        toolbar.pivot_input.setCurrentIndex(1)
        toolbar.snap_button.click()
        self.assertEqual(self.state.tool_options, {"orientation": "local", "pivot": "active", "snap": True, "xray": False})
        self.window.toolActions['scale'].trigger()
        self.assertFalse(toolbar.orientation_input.isEnabled())
        self.window.toolActions['select'].trigger()
        toolbar.xray_button.click()
        self.assertTrue(self.state.tool_options['xray'])
        self.window.viewport.tools_visibility_requested.emit()
        self.assertTrue(toolbar.isHidden())
        self.assertFalse(self.window.toolsVisibleAction.isChecked())
        self.window.toolsVisibleAction.trigger()
        self.assertFalse(toolbar.isHidden())
        self.assertFalse(self.scene.dirty)

    def test_drag_preview_updates_properties_and_commits_one_undo_step(self):
        obj = self.select_second()
        viewport = self.window.viewport
        original = list(obj.position)
        viewport.transform_started.emit((obj.identifier,), "Move Objects")
        for x in (2, 3, 4):
            viewport.transform_previewed.emit({obj.identifier: {'position': [x, 2, 3]}})
            self.assertEqual(self.properties.transform_inputs['position'][0].value(), x)
            self.assertEqual(self.state.undo_stack.count(), 0)
        viewport.transform_finished.emit(True)
        self.assertEqual(self.state.undo_stack.count(), 1)
        self.window.undoAction.trigger()
        self.assertEqual(obj.position, original)
        self.assertFalse(self.scene.dirty)
        self.window.redoAction.trigger()
        self.assertEqual(obj.position, [4, 2, 3])

    def test_save_and_undo_cancel_unfinished_drag_previews(self):
        obj = self.select_second()
        self.state.set_transform_component(obj.identifier, 'position', 0, 10)
        self.state.mark_saved()
        self.state.begin_transform((obj.identifier,), 'Move Objects')
        self.state.preview_transform({obj.identifier: {'position': [20, 20, 20]}})
        path = self.folder / 'no-preview.simuO'
        self.window.writeProject(path)
        self.assertEqual(json.loads(path.read_text())['objects'][1]['position'][0], 10)
        self.state.begin_transform((obj.identifier,), 'Move Objects')
        self.state.preview_transform({obj.identifier: {'position': [30, 30, 30]}})
        self.window.undoAction.trigger()
        self.assertEqual(obj.position[0], 1.123456)
        self.assertEqual(obj.position[1:], [2, 3])

    def test_frame_scene_toolbar_and_shortcut_respect_visibility_and_preserve_selection(self):
        selected = self.select_second()
        hidden = self.scene.objects[2]
        self.state.set_visibility(hidden.identifier, False)
        self.state.mark_saved()
        for trigger in (self.window.frameSceneAction.trigger, self.window.viewport.frame_scene_requested.emit):
            trigger()
            self.assertEqual(self.window.viewport.framed_object, tuple(self.scene.objects[:2]))
            self.assertIs(self.state.selected_object, selected)
            self.assertFalse(self.scene.dirty)
        self.state.isolate_selected()
        self.window.frameSceneAction.trigger()
        self.assertIs(self.window.viewport.framed_object, selected)

    def test_import_waits_for_explicit_selection(self):
        mesh = ROOT / "Assets/teapot.simuOPart"
        with patch("simuo.ui.main_window.QFileDialog.getOpenFileName", return_value=(str(mesh), "")):
            self.window.importFile()
        obj = self.scene.objects[-1]
        self.assertEqual(len(self.hierarchy.rows), 4)
        self.assertIsNone(self.state.selected_object)
        self.assertIs(self.window.viewport.rendered[-1], obj)
        self.assertEqual(self.properties.stack.currentIndex(), 0)
        self.window.viewport.object_picked.emit(obj.identifier)
        self.assertEqual(self.properties.name_input.text(), "teapot")
        self.assertTrue(self.scene.dirty)

    def test_viewport_and_hierarchy_share_selection_and_highlighting(self):
        obj = self.scene.objects[2]
        self.window.viewport.object_picked.emit(obj.identifier)
        self.assertIs(self.state.selected_object, obj)
        self.assertEqual(list(self.hierarchy.rows).index(self.hierarchy.selected_id), 2)
        self.assertEqual(self.properties.name_input.text(), "Axis")
        self.assertEqual(self.window.viewport.selected_object_id, obj.identifier)
        self.select_second()
        self.assertEqual(self.window.viewport.selected_object_id, self.scene.objects[1].identifier)
        self.window.viewport.object_picked.emit(None)
        self.assertIsNone(self.state.selected_object)
        self.assertEqual([row for row in self.hierarchy.rows.values() if row.is_selected], [])
        self.assertEqual(self.properties.stack.currentIndex(), 0)
        self.assertIsNone(self.window.viewport.selected_object_id)
        self.assertFalse(self.scene.dirty)

    def test_import_preserves_an_existing_explicit_selection(self):
        obj = self.select_second()
        with patch("simuo.ui.main_window.QFileDialog.getOpenFileName", return_value=(str(ROOT / "Assets/cube.simuOPart"), "")):
            self.window.importFile()
        self.assertIs(self.state.selected_object, obj)
        self.assertEqual(self.properties.name_input.text(), "Cube")
        self.assertEqual(list(self.hierarchy.rows).index(self.hierarchy.selected_id), 1)

    def test_inspector_reset_controls_and_foldouts(self):
        obj = self.select_second()
        self.properties.transform_inputs["rotation"][1].setValue(45)
        self.properties.transform_inputs["scale"][0].setValue(2)
        self.properties.reset_buttons["position"].click()
        self.assertEqual(obj.position, [0.0, 0.0, 0.0])
        self.assertEqual(obj.rotation[1], 45)
        changes = []
        self.state.object_changed.connect(changes.append)
        self.state.reset_transform(obj.identifier)
        self.assertEqual(obj.rotation, [0.0, 0.0, 0.0])
        self.assertEqual(obj.scale, [1.0, 1.0, 1.0])
        self.assertEqual(changes, [obj])
        self.assertEqual(self.properties.mesh_name.text(), "cube.simuOPart")
        self.properties.transform_section.toggle.click()
        self.assertTrue(self.properties.transform_section.body.isHidden())
        self.window.focusProperties("position")
        self.assertFalse(self.properties.transform_section.body.isHidden())

    def test_vector_rows_fit_a_narrow_inspector(self):
        self.select_second()
        dock = self.window.panel_manager.docks["properties"]
        self.window.resizeDocks([dock], [280], Qt.Horizontal)
        self.app.processEvents()
        for fields in self.properties.transform_inputs.values():
            self.assertEqual(len({field.y() for field in fields}), 1)
            self.assertLess(fields[0].x(), fields[1].x())
            self.assertLess(fields[1].x(), fields[2].x())
            for field in fields:
                self.assertGreaterEqual(field.width(), 40)
                self.assertLess(field.geometry().right(), field.parentWidget().width())

    def test_reset_stays_inside_the_section_header_at_different_widths(self):
        obj = self.select_second()
        section = self.properties.transform_section
        dock = self.window.panel_manager.docks["properties"]
        for width in (260, 340, 500):
            self.window.resizeDocks([dock], [width], Qt.Horizontal)
            self.app.processEvents()
            self.assertIs(section.reset_button.parentWidget(), section.header)
            self.assertTrue(section.header.rect().contains(section.reset_button.geometry()))
            self.assertFalse(section.toggle.geometry().intersects(section.reset_button.geometry()))
            self.assertEqual(section.header.height(), 32)
        self.properties.transform_inputs["rotation"][1].setValue(45)
        section.toggle.click()
        section.reset_button.click()
        self.assertEqual(obj.position, [0.0, 0.0, 0.0])
        self.assertEqual(obj.rotation, [0.0, 0.0, 0.0])
        self.assertTrue(section.body.isHidden())

    def test_compact_numbers_keep_precision_and_follow_locale(self):
        self.select_second()
        field = self.properties.transform_inputs["scale"][0]
        self.assertEqual(field.text(), "X 1")
        field.setValue(2.5)
        self.assertEqual(field.text(), "X 2.5")
        field.setLocale(QLocale("de_DE"))
        self.assertEqual(field.text(), "X 2,5")
        self.assertEqual(field.value(), 2.5)

    def test_scrolling_over_an_unfocused_number_does_not_edit_the_scene(self):
        obj = self.select_second()
        field = self.properties.transform_inputs["position"][0]
        self.properties.name_input.setFocus()
        self.app.processEvents()
        self.assertFalse(field.hasFocus())
        event = QWheelEvent(QPointF(5, 5), QPointF(5, 5), QPoint(), QPoint(0, 120),
                            Qt.NoButton, Qt.NoModifier, Qt.NoScrollPhase, False)
        QApplication.sendEvent(field, event)
        self.assertEqual(obj.position[0], 1.123456)
        self.assertFalse(self.scene.dirty)

    def test_save_and_load_preserve_ids_names_and_transforms(self):
        obj = self.select_second()
        self.properties.transform_inputs["scale"][0].setValue(3.5)
        self.state.set_visibility(obj.identifier, False)
        self.state.set_selection_locked(obj.identifier, True)
        ids = [obj.identifier for obj in self.scene.objects]
        path = self.folder / "scene.simuO"
        self.assertTrue(self.window.writeProject(path))
        self.assertFalse(self.scene.dirty)
        self.assertFalse(self.window.isWindowModified())
        saved = json.loads(path.read_text())
        self.assertEqual(len(saved["objects"]), 3)
        self.window.loadFile(path)
        self.assertEqual([obj.identifier for obj in self.scene.objects], ids)
        self.assertEqual(self.scene.objects[1].scale[0], 3.5)
        self.assertFalse(self.scene.objects[1].editor_visible)
        self.assertTrue(self.scene.objects[1].selection_locked)
        self.assertEqual(self.state.scene_name, "scene")
        self.assertIsNone(self.state.selected_object)
        self.assertEqual(self.properties.stack.currentIndex(), 0)
        self.assertEqual(len(self.hierarchy.rows), 3)
        self.assertEqual(len(self.window.viewport.rendered), 3)

    def test_older_files_and_duplicate_ids_get_distinct_objects(self):
        path = self.folder / "older.simuO"
        path.write_text(json.dumps({"version": 1, "objects": [
            {"name": "Old Cube", "meshPath": "Assets/cube.simuOPart"},
            {"name": "Same", "id": "repeated", "meshPath": "Assets/cube.simuOPart"},
            {"name": "Same", "id": "repeated", "meshPath": "Assets/cube.simuOPart"},
        ]}))
        self.window.loadFile(path)
        ids = [obj.identifier for obj in self.scene.objects]
        self.assertEqual(len(set(ids)), 3)
        self.assertEqual(ids[1], "repeated")
        self.assertTrue(all(obj.editor_visible for obj in self.scene.objects))
        self.assertFalse(any(obj.selection_locked for obj in self.scene.objects))
        self.hierarchy.rows[self.scene.objects[2].identifier].name_button.click()
        self.properties.transform_inputs["position"][2].setValue(7)
        self.assertEqual(self.scene.objects[2].position[2], 7)
        self.assertEqual(self.scene.objects[1].position[2], 0)

    def test_new_scene_clears_selection_and_disables_old_controls(self):
        old = self.select_second()
        self.window.newProject()
        self.assertEqual(self.scene.objects, [])
        self.assertEqual(self.window.viewport.rendered, [])
        self.assertIsNone(self.state.selected_object)
        self.assertEqual(len(self.hierarchy.rows), 0)
        self.assertEqual(self.properties.stack.currentIndex(), 0)
        self.properties.transform_inputs["position"][0].setValue(50)
        self.assertEqual(old.position[0], 1.123456)
        self.assertFalse(self.scene.dirty)

    def test_cancel_keeps_the_modified_scene_for_new_open_and_close(self):
        obj = self.select_second()
        self.properties.transform_inputs["position"][0].setValue(10)
        with patch("simuo.ui.main_window.QMessageBox.question", return_value=QMessageBox.Cancel), patch(
            "simuo.ui.main_window.QFileDialog.getOpenFileName", return_value=("unused.simuO", "")
        ), patch.object(self.window, "loadFile") as load:
            self.window.newProject()
            self.window.openFile()
            self.assertFalse(self.window.close())
            load.assert_not_called()
        self.assertTrue(self.window.isVisible())
        self.assertIs(self.state.selected_object, obj)
        self.assertEqual(len(self.scene.objects), 3)
        self.assertTrue(self.scene.dirty)

    def test_canceling_save_or_a_failed_save_does_not_discard_the_scene(self):
        obj = self.select_second()
        self.properties.transform_inputs["position"][0].setValue(10)
        with patch("simuo.ui.main_window.QMessageBox.question", return_value=QMessageBox.Save), patch(
            "simuo.ui.main_window.QFileDialog.getSaveFileName", return_value=("", "")
        ):
            self.window.newProject()
        self.assertIs(self.state.selected_object, obj)
        self.assertTrue(self.scene.dirty)
        old_path = self.folder / "original.simuO"
        self.window.projectPath = old_path
        with patch.object(Path, "write_text", side_effect=OSError("Cannot write")), patch(
            "simuo.ui.main_window.QMessageBox.critical"
        ) as error:
            self.assertFalse(self.window.writeProject(self.folder / "new.simuO"))
            error.assert_called_once()
        self.assertEqual(self.window.projectPath, old_path)
        self.assertTrue(self.scene.dirty)

    def test_camera_keys_are_released_when_focus_leaves_viewport(self):
        from simuo.rendering.viewport import OpenGLViewport

        viewport = OpenGLViewport()
        self.addCleanup(viewport.close)
        self.addCleanup(viewport.timer.stop)
        viewport.keys.add(Qt.Key_W)
        QApplication.sendEvent(viewport, QFocusEvent(QFocusEvent.Type.FocusOut))
        self.assertEqual(viewport.keys, set())

    def test_batch_inspector_edits_and_reset_undo_together(self):
        a, b, other = self.scene.objects
        self.state.select_many([a.identifier, b.identifier])
        self.assertEqual(self.properties.name_input.text(), "2 objects selected")
        self.assertFalse(self.properties.name_input.isEnabled())
        field = self.properties.transform_inputs["position"][0]
        self.assertTrue(field.mixed)
        self.assertIn("—", field.text())
        field.setValue(25)
        self.assertEqual((a.position[0], b.position[0], other.position[0]), (25, 25, 0))
        self.assertFalse(field.mixed)
        self.window.undoAction.trigger()
        self.assertEqual(a.position[0], 0)
        self.assertEqual(b.position[0], 1.123456)
        self.assertTrue(field.mixed)
        self.properties.transform_section.reset_button.click()
        self.assertEqual(a.position, [0, 0, 0])
        self.assertEqual(b.position, [0, 0, 0])
        self.window.undoAction.trigger()
        self.assertEqual(b.position, [1.123456, 2, 3])

    def test_typing_the_active_value_into_a_mixed_field_updates_all(self):
        a, b, _ = self.scene.objects
        self.state.select_many([a.identifier, b.identifier])
        field = self.properties.transform_inputs["position"][0]
        field.setFocus()
        field.selectAll()
        QTest.keyClicks(field, "1.123")
        QTest.keyClick(field, Qt.Key_Return)
        self.assertEqual(a.position[0], 1.123)
        self.assertEqual(b.position[0], 1.123)
        self.assertEqual(self.state.undo_stack.count(), 1)

    def test_focusing_a_mixed_field_without_typing_does_not_edit(self):
        self.state.select_many(obj.identifier for obj in self.scene.objects[:2])
        field = self.properties.transform_inputs["position"][0]
        field.setFocus()
        self.properties.transform_inputs["scale"][0].setFocus()
        self.assertEqual(self.scene.objects[1].position[0], 1.123456)
        self.assertFalse(self.state.undo_stack.canUndo())

    def test_duplicate_delete_and_undo_keep_panels_and_viewport_in_sync(self):
        originals = tuple(self.scene.objects)
        self.state.select_many(obj.identifier for obj in originals[:2])
        self.hierarchy.setFocus()
        self.app.processEvents()
        self.window.duplicateAction.trigger()
        copies = self.state.selected_objects
        self.assertEqual(len(copies), 2)
        self.assertEqual(len(self.hierarchy.rows), 5)
        self.assertEqual(len(self.window.viewport.rendered), 5)
        self.assertEqual(self.window.viewport.selected_object_ids, set(self.state.selected_ids))
        self.window.deleteAction.trigger()
        self.assertEqual(self.scene.objects, list(originals))
        self.assertEqual(self.properties.stack.currentIndex(), 0)
        self.window.undoAction.trigger()
        self.assertEqual(self.state.selected_objects, copies)
        self.assertEqual(len(self.window.viewport.rendered), 5)
        self.window.undoAction.trigger()
        self.assertEqual(self.scene.objects, list(originals))
        self.assertEqual(self.state.selected_objects, originals[:2])
        self.assertFalse(self.window.isWindowModified())
        self.window.redoAction.trigger()
        self.assertEqual(self.state.selected_objects, copies)

    def test_text_editing_shortcuts_do_not_delete_or_duplicate_objects(self):
        obj = self.select_second()
        field = self.properties.name_input
        field.setFocus()
        field.selectAll()
        self.app.processEvents()
        self.assertFalse(self.window.deleteAction.isEnabled())
        self.assertFalse(self.window.duplicateAction.isEnabled())
        QTest.keyClick(field, Qt.Key_Backspace)
        self.assertEqual(len(self.scene.objects), 3)
        self.assertEqual(field.text(), "")
        QTest.keyClicks(field, "Typing")
        QTest.keySequence(field, self.window.undoAction.shortcuts()[0])
        self.assertEqual(obj.name, "Cube")
        self.assertEqual(len(self.scene.objects), 3)
        self.hierarchy.setFocus()
        self.app.processEvents()
        self.assertTrue(self.window.deleteAction.isEnabled())

    def test_shortcuts_work_in_floating_hierarchy_and_search_select_all_is_local(self):
        self.select_second()
        dock = self.window.panel_manager.docks["object_hierarchy"]
        dock.setFloating(True)
        dock.show()
        dock.activateWindow()
        if self.app.platformName() != "offscreen":
            self.assertTrue(QTest.qWaitForWindowActive(dock, 2000))
        self.hierarchy.setFocus()
        self.app.processEvents()
        QTest.keySequence(self.hierarchy, self.window.duplicateAction.shortcut())
        self.assertEqual(len(self.scene.objects), 4)
        QTest.keySequence(self.hierarchy, self.window.undoAction.shortcuts()[0])
        self.assertEqual(len(self.scene.objects), 3)
        self.hierarchy.search.setFocus()
        QTest.keyClicks(self.hierarchy.search, "cube")
        QTest.keySequence(self.hierarchy.search, self.window.selectAllAction.shortcuts()[0])
        self.assertEqual(self.hierarchy.search.selectedText(), "cube")
        self.assertEqual(len(self.state.selected_objects), 1)

    def test_saved_checkpoint_updates_title_and_loading_clears_history(self):
        obj = self.select_second()
        self.state.rename_object(obj.identifier, "Saved")
        path = self.folder / "checkpoint.simuO"
        self.window.writeProject(path)
        self.assertFalse(self.window.isWindowModified())
        self.window.undoAction.trigger()
        self.assertTrue(self.window.isWindowModified())
        self.window.redoAction.trigger()
        self.assertFalse(self.window.isWindowModified())
        self.window.loadFile(path)
        self.assertFalse(self.window.undoAction.isEnabled())
        self.assertFalse(self.window.redoAction.isEnabled())

    def test_save_commits_pending_numeric_and_name_edits_before_checkpoint(self):
        obj = self.select_second()
        path = self.folder / "pending.simuO"
        field = self.properties.transform_inputs["position"][0]
        field.setFocus()
        field.selectAll()
        QTest.keyClicks(field, "77.5")
        self.window.writeProject(path)
        self.assertEqual(json.loads(path.read_text())["objects"][1]["position"][0], 77.5)
        self.assertFalse(self.scene.dirty)
        self.state.undo_stack.undo()
        self.assertEqual(obj.position[0], 1.123456)
        self.assertTrue(self.scene.dirty)
        name = self.properties.name_input
        name.setFocus()
        name.selectAll()
        QTest.keyClicks(name, "Committed on save")
        self.window.writeProject(path)
        self.assertEqual(json.loads(path.read_text())["objects"][1]["name"], "Committed on save")

    def test_viewport_modifier_picks_share_multiple_selection_with_the_panels(self):
        a, b, _ = self.scene.objects
        self.window.viewport.object_picked.emit(a.identifier)
        self.window.viewport.pick_modifiers = Qt.ControlModifier
        self.window.viewport.object_picked.emit(b.identifier)
        self.assertEqual(self.state.selected_objects, (a, b))
        self.assertTrue(self.hierarchy.rows[a.identifier].is_selected)
        self.assertTrue(self.hierarchy.rows[b.identifier].is_selected)
        self.assertEqual(self.properties.name_input.text(), "2 objects selected")
        self.window.viewport.object_picked.emit(None)
        self.assertEqual(self.state.selected_objects, (a, b))
        self.window.viewport.object_picked.emit(a.identifier)
        self.assertEqual(self.state.selected_objects, (b,))
        self.window.viewport.pick_modifiers = Qt.NoModifier
        self.window.viewport.object_picked.emit(None)
        self.assertFalse(self.state.selected_objects)

    def test_right_clicking_a_different_row_commits_the_previous_transform(self):
        obj = self.select_second()
        field = self.properties.transform_inputs["position"][0]
        field.setFocus()
        field.selectAll()
        QTest.keyClicks(field, "42.5")
        from unittest.mock import Mock
        with patch.object(self.hierarchy, "context_menu", return_value=Mock()):
            QTest.mouseClick(self.hierarchy.rows[self.scene.objects[0].identifier].name_button, Qt.RightButton)
        self.assertEqual(obj.position[0], 42.5)

    def test_groups_order_flags_and_expansion_round_trip_while_isolation_does_not(self):
        a, b, c = self.scene.objects
        group = self.state.create_group("Assembly", [a.identifier, b.identifier])
        self.state.move_objects([b.identifier], group.identifier, a.identifier)
        self.state.move_group(group.identifier)
        self.state.set_group_visibility(group.identifier, False)
        self.state.set_group_locked(group.identifier, True)
        self.state.select(c.identifier)
        self.state.isolate_selected()
        group.expanded = False
        ids = list(group.members)
        roots = list(self.scene.root_order)
        path = self.folder / "groups.simuO"
        self.window.writeProject(path)
        saved = json.loads(path.read_text())
        self.assertEqual(saved["groups"][0]["objects"], ids)
        self.assertTrue(saved["objects"][0]["editor"]["visible"])
        self.window.loadFile(path)
        loaded = self.scene.groups[0]
        self.assertEqual(loaded.identifier, group.identifier)
        self.assertEqual(loaded.name, "Assembly")
        self.assertEqual(loaded.members, ids)
        self.assertFalse(loaded.expanded)
        self.assertFalse(loaded.editor_visible)
        self.assertTrue(loaded.selection_locked)
        self.assertEqual(self.scene.root_order, roots)
        self.assertIsNone(self.state.isolated_ids)
        self.assertFalse(self.scene.objects[0].viewport_visible)
        self.assertTrue(self.scene.objects[0].viewport_locked)
        self.assertTrue(self.scene.objects[2].viewport_visible)
        self.assertFalse(self.window.isWindowModified())
        self.assertEqual(self.state.undo_stack.count(), 0)

    def test_group_shortcut_and_view_actions_work_with_hidden_hierarchy(self):
        self.select_second()
        dock = self.window.panel_manager.docks["object_hierarchy"]
        dock.hide()
        self.window.viewport.setFocus()
        self.app.processEvents()
        QTest.keySequence(self.window.viewport, self.window.groupAction.shortcut())
        self.assertEqual(len(self.scene.groups), 1)
        self.assertTrue(dock.isVisible())
        group = self.scene.groups[0]
        row = self.hierarchy.group_rows[group.identifier]
        self.assertEqual(row.name_stack.currentIndex(), 1)
        row.finish_rename()
        dock.hide()
        self.hierarchy.search.setText("not found")
        self.window.showSelectedAction.trigger()
        self.assertTrue(dock.isVisible())
        self.assertEqual(self.hierarchy.search.text(), "")
        self.window.isolateAction.trigger()
        self.assertIsNotNone(self.state.isolated_ids)
        self.assertTrue(self.window.isolateAction.isChecked())
        self.hierarchy.isolation_button.click()
        self.assertIsNone(self.state.isolated_ids)
        self.assertFalse(self.window.isolateAction.isChecked())

    def test_escape_cancels_properties_rename_without_changing_history(self):
        obj = self.select_second()
        field = self.properties.name_input
        field.setFocus()
        field.selectAll()
        QTest.keyClicks(field, "Discarded name")
        QTest.keyClick(field, Qt.Key_Escape)
        self.hierarchy.setFocus()
        self.assertEqual(obj.name, "Cube")
        self.assertEqual(field.text(), "Cube")
        self.assertEqual(self.state.undo_stack.count(), 0)

    def test_empty_hierarchy_click_commits_previous_field_before_clearing_selection(self):
        obj = self.select_second()
        field = self.properties.transform_inputs["position"][0]
        field.setFocus()
        field.selectAll()
        QTest.keyClicks(field, "48.5")
        self.hierarchy.search.setText("no results")
        QTest.mouseClick(self.hierarchy.stack.widget(1), Qt.LeftButton)
        self.assertEqual(obj.position[0], 48.5)
        self.assertIsNone(self.state.selected_object)
        self.assertEqual(self.properties.stack.currentIndex(), 0)
        self.state.undo_stack.undo()
        self.assertEqual(obj.position[0], 1.123456)

    def test_viewport_escape_exits_isolation_before_closing_window(self):
        self.select_second()
        self.state.isolate_selected()
        self.window.viewport.escape_requested.emit()
        self.assertIsNone(self.state.isolated_ids)
        self.assertTrue(self.window.isVisible())
        self.assertFalse(self.window.isolateAction.isChecked())

    def test_show_selected_view_action_resets_state_filters_and_restores_hierarchy(self):
        obj = self.select_second()
        self.hierarchy.set_filter("visibility_filter", "hidden")
        self.hierarchy.set_filter("lock_filter", "locked")
        self.window.panel_manager.docks["object_hierarchy"].hide()
        self.window.showSelectedAction.trigger()
        self.assertFalse(self.hierarchy.has_active_filters())
        self.assertFalse(self.hierarchy.rows[obj.identifier].isHidden())
        self.assertIs(self.state.selected_object, obj)


if __name__ == "__main__":
    unittest.main()
