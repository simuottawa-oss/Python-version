"""Shared material inspector, scene snapshots, and effective Bullet mass."""
from dataclasses import replace
import json
from pathlib import Path
import tempfile
import unittest
from contextlib import contextmanager
from unittest.mock import patch

from PySide6.QtWidgets import QApplication, QMessageBox
from tests import ROOT
from tests.support import create_scene_window
from tests.integration.viewport_stub import ViewportStub
from simuo.materials import PRESETS, MaterialDefinition
from simuo.physics.physics_world import PhysicsWorld
from simuo.project.scene import SceneObject
from simuo.ui.material_inspector import MaterialInspector


@contextmanager
def physics_world(scene):
    world = PhysicsWorld(scene, gravity=0, floor=False)
    try:
        yield world
    finally:
        world.close()


class MaterialTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        viewport = patch("simuo.ui.scene_window.OpenGLViewport", ViewportStub)
        viewport.start()
        self.addCleanup(viewport.stop)
        self.window = create_scene_window()
        self.addCleanup(self.close)
        self.obj = SceneObject(meshPath=ROOT/"Assets/aluminum_cube.simuOPart")
        self.window.editor_state.add_object(self.obj)
        self.window.editor_state.select(self.obj.identifier)

    def close(self):
        with patch("simuo.ui.scene_window.QMessageBox.question", return_value=QMessageBox.StandardButton.Discard):
            self.window.close()

    def test_inspector_presets_custom_undo_and_original_part(self):
        inspector = self.window.panel_manager.docks["properties"].widget().material_section
        self.assertIsInstance(inspector, MaterialInspector)
        original = self.obj.part
        inspector.combo.setCurrentIndex(inspector.combo.findData("steel-a36"))
        self.assertEqual(self.obj.material, PRESETS[0])
        self.assertIs(self.obj.part, original)
        self.window.editor_state.undo_stack.undo()
        self.assertIsNone(self.obj.material_override)
        self.window.editor_state.undo_stack.redo()
        self.assertEqual(self.obj.material, PRESETS[0])
        inspector.edit_as_custom()
        inspector.young.setValue(123.)
        inspector._custom_changed()
        self.assertEqual(self.obj.material.young_modulus, 123e9)
        self.assertIsNone(self.obj.material.preset_id)
        inspector.reset_material()
        self.assertIsNone(self.obj.material_override)

    def test_scene_roundtrip_preserves_material_snapshot(self):
        custom_snapshot = replace(PRESETS[0], young_modulus=199e9)
        self.window.editor_state.set_material(self.obj.identifier, custom_snapshot)
        path = Path(self.temp.name)/"scene.simuO"
        self.assertTrue(self.window.saveFile(destination=path))
        data = json.loads(path.read_text())
        self.assertEqual(data["project_type"], "scene")
        self.assertEqual(data["version"], 2)
        self.window.loadFile(path, uploadToGPU=False)
        restored = self.window.scene.objects[0]
        self.assertEqual(restored.material_override, custom_snapshot)
        self.assertIsNone(restored.part.properties.get("material"))

    def test_density_mass_explicit_mass_and_legacy_fallback(self):
        self.window.editor_state.set_material(self.obj.identifier, PRESETS[0])
        self.obj.body_type = "dynamic"
        with physics_world(self.window.scene) as world:
            self.assertAlmostEqual(world.masses[0], 7850*.2**3)
        self.obj.part = replace(self.obj.part, mass_source="explicit", mass=12.3)
        with physics_world(self.window.scene) as world:
            self.assertAlmostEqual(world.masses[0], 12.3)
        legacy = SceneObject(meshPath=ROOT/"Assets/cube.simuOPart")
        legacy.body_type = "dynamic"
        legacy.material_override = PRESETS[0]
        self.window.scene.objects[:] = [legacy]
        with physics_world(self.window.scene) as world:
            self.assertEqual(world.masses, [1.])

    def test_invalid_material_does_not_replace_scene(self):
        path = Path(self.temp.name)/"bad.simuO"
        path.write_text(json.dumps({"format": ".simuO", "version": 2, "project_type": "scene", "objects": [
            {"name": "Bad", "meshPath": str(ROOT/"Assets/aluminum_cube.simuOPart"), "material": {"name": "Invalid", "density": -1}}]}))
        with patch("simuo.ui.scene_window.QMessageBox.warning"):
            self.assertFalse(self.window.tryLoadFile(path, uploadToGPU=False))
        self.assertEqual(self.window.scene.objects, [self.obj])

    def test_catalog_entries_are_valid_complete_snapshots(self):
        for preset in PRESETS:
            self.assertEqual(MaterialDefinition(**preset.to_dict()), preset)
            self.assertGreater(preset.young_modulus, 0)
            self.assertGreater(preset.density, 0)
