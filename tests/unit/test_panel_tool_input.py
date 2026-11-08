"""Mouse tool gestures, selection modifiers, cancellation, and camera isolation."""

import unittest


import glm
import numpy as np
from PySide6.QtCore import QEvent, QPointF, Qt
from PySide6.QtGui import QFocusEvent, QKeyEvent, QMouseEvent
from PySide6.QtWidgets import QApplication

from tests import ROOT
from simuo.editor.state import EditorState
from simuo.parts.part_assets import loadObjFlatShaded
from simuo.rendering.picking import PickMesh
from simuo.rendering.viewport import OpenGLViewport
from simuo.project.scene import Scene, SceneObject


class ToolInput(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])
        cls.mesh = PickMesh(loadObjFlatShaded(ROOT / 'Assets/cube.simuOPart'))

    def setUp(self):
        self.scene = Scene()
        self.objects = [SceneObject('Left'), SceneObject('Right')]
        for obj, x in zip(self.objects, (-2, 2)):
            obj.position[0] = x
            self.scene.addObject(obj)
        self.state = EditorState(self.scene)
        self.viewport = OpenGLViewport(scene=self.scene)
        self.viewport.timer.stop()
        self.addCleanup(self.viewport.close)
        self.viewport.resize(800, 600)
        self.viewport.camera.position = glm.vec3(0, 0, 10)
        self.viewport.renderObjects = [{'SceneObject': obj, 'pick_mesh': self.mesh} for obj in self.objects]
        self.viewport.object_picked.connect(lambda key: self.state.select_from_viewport(key, self.viewport.pick_modifiers))
        self.viewport.box_selection_requested.connect(self.state.select_many)
        self.viewport.frame_requested.connect(self.state.frame_selected)
        self.state.selection_set_changed.connect(self.viewport.set_selected_objects)
        self.viewport.transform_started.connect(self.state.begin_transform)
        self.viewport.transform_previewed.connect(self.state.preview_transform)
        self.viewport.transform_finished.connect(self.state.finish_transform)
        self.state.transform_ended.connect(self.viewport.discard_transform)
        self.state.tool_changed.connect(self.viewport.set_tool)
        self.state.tool_options_changed.connect(self.viewport.set_tool_options)

    def mouse(self, kind, point, modifiers=Qt.NoModifier, button=Qt.LeftButton):
        point = QPointF(float(point[0]), float(point[1]))
        held = Qt.NoButton if kind == QEvent.Type.MouseButtonRelease else button
        changed = Qt.NoButton if kind == QEvent.Type.MouseMove else button
        QApplication.sendEvent(self.viewport, QMouseEvent(kind, point, point, changed, held, modifiers))

    def key(self, key):
        QApplication.sendEvent(self.viewport, QKeyEvent(QEvent.Type.KeyPress, key, Qt.NoModifier))

    def start_move(self):
        self.state.select(self.objects[0].identifier)
        self.state.set_tool('move')
        handle = next(h for h in self.viewport.gizmo().handles if h.key == 'x')
        start = handle.points[-1]
        self.mouse(QEvent.Type.MouseButtonPress, start)
        self.mouse(QEvent.Type.MouseMove, start + [50, 10])
        return start

    def test_drag_commits_on_release_and_freezes_camera(self):
        before = glm.vec3(self.viewport.camera.position)
        start = self.start_move()
        self.assertIsNotNone(self.viewport.drag)
        self.assertGreater(self.objects[0].position[0], -2)
        self.assertEqual(self.state.undo_stack.count(), 0)
        self.key(Qt.Key_W)
        self.viewport.update_camera(.5)
        self.assertEqual(self.viewport.camera.position, before)
        self.mouse(QEvent.Type.MouseButtonRelease, start + [80, 10])
        self.assertEqual(self.state.undo_stack.count(), 1)
        self.assertIsNone(self.viewport.drag)
        self.state.undo_stack.undo()
        np.testing.assert_allclose(self.objects[0].position, [-2, 0, 0])
        np.testing.assert_allclose(self.objects[1].position, [2, 0, 0])
        self.assertFalse(self.scene.dirty)
        # Keys pressed during a gesture must not start moving after release.
        self.viewport.update_camera(.5)
        self.assertEqual(self.viewport.camera.position, before)

    def test_escape_right_click_focus_loss_and_tool_switch_cancel(self):
        for cancel in (lambda: self.key(Qt.Key_Escape),
                       lambda: self.mouse(QEvent.Type.MouseButtonPress, (200, 200), button=Qt.RightButton),
                       lambda: QApplication.sendEvent(self.viewport, QFocusEvent(QEvent.Type.FocusOut)),
                       lambda: self.state.set_tool('select')):
            with self.subTest(cancel=cancel):
                escapes = []
                self.viewport.escape_requested.connect(lambda: escapes.append(True))
                self.start_move()
                cancel()
                self.assertIsNone(self.viewport.drag)
                self.assertFalse(self.viewport.right_mouse_down)
                self.assertEqual(escapes, [])
                np.testing.assert_allclose(self.objects[0].position, [-2, 0, 0])
                self.assertEqual(self.state.undo_stack.count(), 0)
                self.assertFalse(self.scene.dirty)

    def test_framing_cancels_preview_before_moving_camera(self):
        self.start_move()
        self.state.frame_requested.connect(self.viewport.frame_object)
        self.key(Qt.Key_F)
        self.assertIsNone(self.viewport.drag)
        np.testing.assert_allclose(self.objects[0].position, [-2, 0, 0])
        self.assertEqual(self.state.undo_stack.count(), 0)
        self.assertFalse(self.scene.dirty)

    def box(self, start, end, modifiers=Qt.NoModifier):
        self.mouse(QEvent.Type.MouseButtonPress, start, modifiers)
        self.mouse(QEvent.Type.MouseMove, end, modifiers)
        self.mouse(QEvent.Type.MouseButtonRelease, end, modifiers)

    def test_box_replace_add_toggle_and_empty_clear(self):
        self.box((220, 230), (380, 370))
        self.assertEqual(self.state.selected_objects, (self.objects[0],))
        self.box((420, 230), (580, 370), Qt.ShiftModifier)
        self.assertEqual(self.state.selected_objects, tuple(self.objects))
        self.box((220, 230), (380, 370), Qt.ControlModifier)
        self.assertEqual(self.state.selected_objects, (self.objects[1],))
        self.box((30, 400), (100, 500))
        self.assertEqual(self.state.selected_objects, ())
        self.assertFalse(self.scene.dirty)
        self.assertEqual(self.state.undo_stack.count(), 0)

    def test_escape_cancels_box_and_restores_prepress_selection(self):
        self.state.select(self.objects[1].identifier)
        self.mouse(QEvent.Type.MouseButtonPress, (220, 230))
        self.mouse(QEvent.Type.MouseMove, (380, 370))
        self.assertEqual(self.state.selected_objects, ())
        self.key(Qt.Key_Escape)
        self.assertIsNone(self.viewport.box_rect())
        self.assertEqual(self.state.selected_objects, (self.objects[1],))

    def test_move_has_no_handles_for_multiple_selected_objects(self):
        self.state.set_tool('move')
        self.state.select_many(obj.identifier for obj in self.objects)
        self.assertIsNone(self.viewport.gizmo())
        self.assertEqual(self.state.selected_objects, tuple(self.objects))

    def test_modified_click_bypasses_gizmo_and_keeps_multi_selection(self):
        self.state.select(self.objects[0].identifier)
        self.state.set_tool('move')
        for obj in (self.objects[1], self.objects[0]):
            point = self.viewport.projection().point(obj.position)[:2]
            self.mouse(QEvent.Type.MouseButtonPress, point, Qt.ControlModifier)
            self.mouse(QEvent.Type.MouseButtonRelease, point, Qt.ControlModifier)
        self.assertEqual(self.state.selected_objects, (self.objects[1],))
        self.assertIsNone(self.viewport.drag)
        self.assertEqual(self.state.undo_stack.count(), 0)
