"""Transform previews share one undo transaction and cancel without side effects."""

import unittest


from PySide6.QtWidgets import QApplication
from simuo.editor.state import EditorState
from simuo.project.scene import Scene, SceneObject


class TransformSessions(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        self.scene = Scene()
        self.objects = [SceneObject('A'), SceneObject('B')]
        self.scene.objects[:] = self.objects
        self.state = EditorState(self.scene)
        self.state.select_many(obj.identifier for obj in self.objects)

    def preview(self):
        self.state.begin_transform(self.state.selected_ids, 'Move Objects')
        for x in (1, 2, 3):
            self.state.preview_transform({obj.identifier: {'position': [x, 0, 0]} for obj in self.objects})

    def test_one_command_for_multi_object_drag_and_exact_undo_redo(self):
        self.preview()
        self.assertEqual(self.state.undo_stack.count(), 0)
        self.assertTrue(self.scene.dirty)
        self.state.finish_transform()
        self.assertEqual(self.state.undo_stack.count(), 1)
        self.state.undo_stack.undo()
        self.assertTrue(all(obj.position == [0, 0, 0] for obj in self.objects))
        self.assertFalse(self.scene.dirty)
        self.assertEqual(self.state.selected_objects, tuple(self.objects))
        self.state.undo_stack.redo()
        self.assertTrue(all(obj.position == [3, 0, 0] for obj in self.objects))

    def test_cancel_and_noop_do_not_create_history_or_dirty_scene(self):
        self.preview()
        self.state.cancel_transform()
        self.assertTrue(all(obj.position == [0, 0, 0] for obj in self.objects))
        self.assertFalse(self.scene.dirty)
        self.assertEqual(self.state.undo_stack.count(), 0)
        self.state.begin_transform(self.state.selected_ids, 'Scale Objects')
        self.state.finish_transform()
        self.assertEqual(self.state.undo_stack.count(), 0)
        self.assertFalse(self.scene.dirty)

    def test_selection_tool_options_and_external_edits_cancel_preview(self):
        for cancel in (lambda: self.state.select(None), lambda: self.state.set_tool('move'),
                       lambda: self.state.set_tool_options(snap=True), lambda: self.state.isolate_selected(),
                       lambda: self.state.set_transform_component(self.objects[0].identifier, 'position', 1, 7)):
            with self.subTest(cancel=cancel):
                self.setUp()
                self.preview()
                cancel()
                self.assertEqual(self.objects[0].position[0], 0)
                self.assertEqual(self.objects[1].position, [0, 0, 0])
                self.assertIsNone(self.state._transform)

    def test_hidden_locked_and_group_locked_objects_are_excluded(self):
        self.objects[0].selection_locked = True
        self.objects[1].editor_visible = False
        self.preview()
        self.assertIsNone(self.state._transform)
        self.assertTrue(all(obj.position == [0, 0, 0] for obj in self.objects))

    def test_invalid_preview_is_atomic(self):
        self.state.begin_transform(self.state.selected_ids, 'Move Objects')
        with self.assertRaises(ValueError):
            self.state.preview_transform({self.objects[0].identifier: {'position': [1, 2, 3]},
                                          self.objects[1].identifier: {'position': [0, float('nan'), 0]}})
        self.assertTrue(all(obj.position == [0, 0, 0] for obj in self.objects))
        self.state.cancel_transform()
