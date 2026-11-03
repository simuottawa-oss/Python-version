"""Silhouette bounds and native GPU checks for selection rendering.

GPU checks skip on Qt's display-free plugin, which has no OpenGL support.
"""

import os
from pathlib import Path
import unittest

import glm
import numpy as np
from PySide6.QtGui import QImage

from tests.support.paths import ROOT
from tests.support.qt import get_application

from simuo.rendering.picking import PickMesh
from simuo.rendering.viewport import OpenGLViewport
from simuo.rendering.meshes import load_obj_flat_shaded
from simuo.scene.model import Scene, SceneObject
from simuo.rendering.outline import outline_bounds


class OutlineBounds(unittest.TestCase):
    def test_outline_bounds_track_the_framebuffer_size_and_stay_on_screen(self):
        obj = SceneObject()
        mesh = PickMesh(load_obj_flat_shaded(ROOT / "Assets/cube.simuOPart"))
        rendered = {"SceneObject": obj, "pick_mesh": mesh}
        view = glm.lookAt(glm.vec3(0, 0, 10), glm.vec3(0), glm.vec3(0, 1, 0))
        projection = glm.perspective(glm.radians(60), 4 / 3, 0.1, 1000)
        a = outline_bounds(rendered, view, projection, 400, 300, 2)
        b = outline_bounds(rendered, view, projection, 800, 600, 4)
        self.assertAlmostEqual(b[0], a[0] * 2, delta=2)
        self.assertAlmostEqual(b[2], a[2] * 2, delta=2)
        self.assertLess(a[2], 400)
        self.assertLess(a[3], 300)
        obj.position[0] = 1000
        outside = outline_bounds(rendered, view, projection, 400, 300, 2)
        self.assertEqual(outside[2], 0)


@unittest.skipIf(os.environ.get("QT_QPA_PLATFORM") == "offscreen", "Native OpenGL display required")
class NativeSelectionOutline(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = get_application()

    def setUp(self):
        self.scene = Scene()
        self.cube = SceneObject("Cube", ROOT / "Assets/cube.simuOPart")
        self.scene.addObject(self.cube)
        self.viewport = OpenGLViewport(scene=self.scene)
        self.addCleanup(self.close_viewport)
        self.viewport.timer.stop()
        self.viewport.resize(400, 300)
        self.viewport.camera.position = glm.vec3(0, 0, 10)
        self.viewport.show()
        self.app.processEvents()
        self.assertTrue(self.viewport.isValid(), "Native OpenGL context failed to initialize")

    def close_viewport(self):
        self.viewport.close()
        self.viewport.cleanup_outline()

    def pixels(self):
        image = self.viewport.grabFramebuffer().convertToFormat(QImage.Format.Format_RGBA8888)
        return np.frombuffer(image.bits(), np.uint8).reshape(image.height(), image.width(), 4).copy()

    def test_box_selection_uses_visible_surfaces_and_xray_selects_through(self):
        blocker = SceneObject("Blocker", self.cube.meshPath)
        blocker.position[2] = 4
        blocker.scale = [2, 2, 1]
        self.scene.addObject(blocker)
        self.viewport.addNewObject(blocker)
        rect = (0, 0, 400, 300)
        self.assertEqual(self.viewport.select_box(rect), [blocker.identifier])
        self.viewport.tool_options['xray'] = True
        self.assertEqual(self.viewport.select_box(rect), [self.cube.identifier, blocker.identifier])
        self.viewport.tool_options['xray'] = False
        blocker.selection_locked = True
        self.assertEqual(self.viewport.select_box(rect), [])
        blocker.editor_visible = False
        self.assertEqual(self.viewport.select_box(rect), [self.cube.identifier])

    def test_selection_buffer_resizes_and_preserves_normal_rendering(self):
        before = self.pixels()
        self.assertEqual(self.viewport.select_box((0, 0, 400, 300)), [self.cube.identifier])
        np.testing.assert_array_equal(self.pixels(), before)
        self.viewport.resize(500, 250)
        self.app.processEvents()
        self.assertEqual(self.viewport.select_box((240, 115, 260, 135)), [self.cube.identifier])
        ratio = self.viewport.devicePixelRatioF()
        self.assertEqual(self.viewport.selection_buffer.size, (round(500*ratio), round(250*ratio)))

    def test_selection_only_adds_a_blue_outline_and_preserves_the_surface(self):
        before = self.pixels()
        self.viewport.set_selected_object(self.cube)
        after = self.pixels()
        changed = np.any(before != after, axis=2)
        blue = (after[:, :, 0] < 90) & (after[:, :, 1] > 125) & (after[:, :, 2] > 235)
        self.assertGreater(np.count_nonzero(changed), 0)
        self.assertTrue(np.all(blue[changed]), "Selection changed pixels other than the blue outline")
        np.testing.assert_array_equal(before[before.shape[0] // 2, before.shape[1] // 2],
                                      after[after.shape[0] // 2, after.shape[1] // 2])
        self.viewport.set_selected_object(None)
        np.testing.assert_array_equal(before, self.pixels())

    def test_fully_occluded_object_has_no_outline(self):
        blocker = SceneObject("Blocker", self.cube.meshPath)
        blocker.position[2] = 4
        blocker.scale = [2, 2, 1]
        self.scene.addObject(blocker)
        self.viewport.addNewObject(blocker)
        before = self.pixels()
        self.viewport.set_selected_object(self.cube)
        np.testing.assert_array_equal(before, self.pixels())

    def test_hidden_mesh_is_removed_from_shading_and_selection_outline(self):
        visible = self.pixels()
        self.cube.editor_visible = False
        hidden = self.pixels()
        self.assertTrue(np.any(visible != hidden))
        self.viewport.set_selected_object(self.cube)
        np.testing.assert_array_equal(hidden, self.pixels())
        self.cube.editor_visible = True
        self.viewport.set_selected_object(None)
        np.testing.assert_array_equal(visible, self.pixels())

    def test_outline_buffer_follows_viewport_resize_and_object_transforms(self):
        self.cube.rotation = [0, 25, 15]
        self.cube.scale = [-1.5, 0.75, 1]
        self.viewport.set_selected_object(self.cube)
        self.viewport.resize(500, 250)
        self.app.processEvents()
        pixels = self.pixels()
        self.assertEqual(self.viewport.selection_outline.size, (pixels.shape[1], pixels.shape[0]))
        blue = (pixels[:, :, 0] < 90) & (pixels[:, :, 1] > 125) & (pixels[:, :, 2] > 235)
        self.assertGreater(np.count_nonzero(blue), 0)

    def test_multiple_selected_objects_each_have_blue_outlines(self):
        other = SceneObject("Other", self.cube.meshPath)
        self.cube.position[0], other.position[0] = -2, 2
        self.scene.addObject(other)
        self.viewport.addNewObject(other)
        before = self.pixels()
        self.viewport.set_selected_objects((self.cube, other))
        after = self.pixels()
        changed = np.any(before != after, axis=2)
        blue = (after[:, :, 0] < 90) & (after[:, :, 1] > 125) & (after[:, :, 2] > 235)
        self.assertTrue(np.all(blue[changed]))
        self.assertGreater(np.count_nonzero(changed[:, :after.shape[1] // 2]), 0)
        self.assertGreater(np.count_nonzero(changed[:, after.shape[1] // 2:]), 0)

    def test_delete_undo_and_redo_update_gpu_meshes_and_pixels(self):
        from simuo.editor.state import EditorState

        state = EditorState(self.scene)
        state.objects_changed.connect(self.viewport.sync_scene_objects)
        state.selection_set_changed.connect(self.viewport.set_selected_objects)
        before = self.pixels()
        state.select(self.cube.identifier)
        state.delete_selected()
        self.assertEqual(self.viewport.renderObjects, [])
        self.assertTrue(np.any(before != self.pixels()))
        state.undo_stack.undo()
        self.assertEqual(len(self.viewport.renderObjects), 1)
        self.assertEqual(self.viewport.selected_object_ids, {self.cube.identifier})
        state.select(None)
        np.testing.assert_array_equal(before, self.pixels())
        state.undo_stack.redo()
        self.assertEqual(self.viewport.renderObjects, [])

    def test_mesh_restoration_reuses_geometry_when_source_was_removed(self):
        import tempfile

        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "temporary.simuOPart"
            path.write_bytes(self.cube.meshPath.read_bytes())
            obj = SceneObject("Temporary", path)
            self.scene.addObject(obj)
            self.viewport.sync_scene_objects()
            self.assertEqual(len(self.viewport.renderObjects), 2)
            path.unlink()
            self.scene.objects.remove(obj)
            self.viewport.sync_scene_objects()
            self.scene.addObject(obj)
            self.viewport.sync_scene_objects()
            self.assertEqual(len(self.viewport.renderObjects), 2)

    def test_group_visibility_and_isolation_remove_shading_and_outlines(self):
        from simuo.editor.state import EditorState

        state = EditorState(self.scene)
        state.view_changed.connect(self.viewport.update)
        state.selection_set_changed.connect(self.viewport.set_selected_objects)
        before = self.pixels()
        group = state.create_group("Group", [self.cube.identifier])
        from simuo.rendering.picking import pick_object
        state.set_group_locked(group.identifier, True)
        self.assertIsNone(pick_object(self.viewport.renderObjects, (0, 0, 10), (0, 0, -1)))
        state.undo_stack.undo()
        self.assertIs(pick_object(self.viewport.renderObjects, (0, 0, 10), (0, 0, -1)), self.cube)
        state.select(self.cube.identifier)
        state.set_group_visibility(group.identifier, False)
        hidden = self.pixels()
        self.assertTrue(np.any(before != hidden))
        self.assertTrue(self.cube.editor_visible)
        state.undo_stack.undo()
        state.select(None)
        np.testing.assert_array_equal(before, self.pixels())
        other = SceneObject("Other", self.cube.meshPath)
        other.position[0] = 3
        self.scene.addObject(other)
        self.viewport.addNewObject(other)
        both = self.pixels()
        state.select(other.identifier)
        state.isolate_selected()
        self.assertFalse(self.cube.viewport_visible)
        self.assertTrue(other.viewport_visible)
        self.assertTrue(np.any(both != self.pixels()))
        state.exit_isolation()
        state.select(None)
        np.testing.assert_array_equal(both, self.pixels())


if __name__ == "__main__":
    unittest.main()
