"""Round-trip panel state alongside the upstream part and physics data."""

import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

from PySide6.QtCore import QSettings
from PySide6.QtWidgets import QApplication, QMessageBox

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "src"))
from simuO import SimuOMainWindow
from viewport_stub import ViewportStub


class PanelIntegrationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        folder = tempfile.TemporaryDirectory()
        self.addCleanup(folder.cleanup)
        self.folder = Path(folder.name).resolve()
        settings = QSettings(str(self.folder / "layout.ini"), QSettings.IniFormat)
        with patch("simuO.OpenGLViewport", ViewportStub), patch("simuo.ui.docking.QSettings", return_value=settings):
            self.window = SimuOMainWindow()
        self.addCleanup(self.window.temporaryParts.cleanup)
        self.addCleanup(self.window.deleteLater)

    def test_upstream_scene_keeps_physics_after_panel_edits(self):
        source = self.folder / "upstream.simuO"
        mesh = str(ROOT / "Assets/aluminum_cube.simuOPart")
        source.write_text(json.dumps({"version": 1, "objects": [
            {"name": "Part", "meshPath": mesh, "velocity": [1, 2, 3],
             "angularVelocity": [0, 0.2, 0], "acceleration": [0, -1, 0],
             "restitution": 0.35, "body_type": "dynamic"}
        ]}))
        self.window.loadFile(source)
        obj = self.window.scene.objects[0]
        state = self.window.editor_state
        state.select(obj.identifier)
        group = state.create_group("Moving parts", state.selected_ids)
        state.set_selection_locked(obj.identifier, True)
        state.set_transform_component(obj.identifier, "position", 0, 2.5)
        saved = self.folder / "combined.simuO"
        self.assertTrue(self.window.saveFile(destination=saved))
        self.window.loadFile(saved)
        loaded = self.window.scene.objects[0]
        self.assertEqual(loaded.identifier, obj.identifier)
        self.assertEqual(loaded.position[0], 2.5)
        self.assertEqual(loaded.velocity, [1, 2, 3])
        self.assertEqual(loaded.angularVelocity, [0, 0.2, 0])
        self.assertEqual(loaded.acceleration, [0, -1, 0])
        self.assertEqual(loaded.restitution, 0.35)
        self.assertEqual(loaded.body_type, "dynamic")
        self.assertEqual(loaded.part.mass, obj.part.mass)
        self.assertTrue(loaded.selection_locked)
        self.assertEqual(self.window.scene.groups[0].identifier, group.identifier)
        self.assertEqual(self.window.scene.groups[0].members, [loaded.identifier])
        self.assertEqual(state.undo_stack.count(), 0)

    def test_feature_branch_scene_loads_hierarchy_without_physics_fields(self):
        source = self.folder / "panels.simuO"
        source.write_text(json.dumps({"version": 1, "objects": [
            {"id": "legacy", "name": "Old part", "meshPath": str(ROOT / "Assets/cube.simuOPart"),
             "editor": {"visible": False, "selection_locked": True}}
        ], "groups": [{"id": "folder", "name": "Old group", "objects": ["legacy"]}],
            "hierarchy_order": ["folder"]}))
        self.window.loadFile(source)
        obj = self.window.scene.objects[0]
        self.assertEqual(obj.identifier, "legacy")
        self.assertFalse(obj.viewport_visible)
        self.assertTrue(obj.viewport_locked)
        self.assertEqual(obj.body_type, "static")
        self.assertEqual(self.window.scene.root_order, ["folder"])
        self.assertTrue(self.window.saveFile(destination=source))
        self.window.loadFile(source)
        self.assertEqual(self.window.scene.groups[0].members, ["legacy"])

    def test_save_promotes_temporary_parts_referenced_by_undo_history(self):
        source = self.folder / "cube.obj"
        source.write_bytes((ROOT / "Assets/cube.simuOPart").read_bytes())
        with patch("simuO.QFileDialog.getOpenFileName", return_value=(str(source), "")), \
             patch("simuO.QMessageBox.question", return_value=QMessageBox.Yes):
            self.window.importFile()
        original = self.window.scene.objects[0]
        state = self.window.editor_state
        state.select(original.identifier)
        state.duplicate_selected()
        duplicate = state.selected_object
        state.delete_selected()
        saved_part = self.folder / "permanent.simuOPart"
        with patch("simuO.QFileDialog.getSaveFileName", return_value=(str(saved_part), "")):
            self.assertTrue(self.window.saveFile(destination=self.folder / "scene.simuO"))
        state.undo_stack.undo()
        self.assertEqual(self.window.scene.objects, [original, duplicate])
        self.assertEqual(duplicate.meshPath, saved_part)
        self.assertTrue(duplicate.meshPath.is_file())
        self.assertEqual(self.window.active_temporary_parts(), [])
