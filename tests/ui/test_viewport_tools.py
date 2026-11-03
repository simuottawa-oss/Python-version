"""Tool rail geometry survives legacy toolbar workspaces and repeated expansion."""

from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from PySide6.QtCore import QPoint, QSettings, Qt
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QMainWindow, QToolBar, QWidget

from tests.support.qt import get_application
from tests.support.viewports import FakeViewport
from simuo.ui.docking import PanelManager, PanelSpec
from simuo.ui.main_window import SimuOMainWindow


class ViewportToolLayouts(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = get_application()

    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.settings = QSettings(str(Path(self.directory.name) / 'layout.ini'), QSettings.IniFormat)

    def save_legacy_layout(self, customized=False):
        window = QMainWindow()
        window.resize(1280, 800)
        window.setCentralWidget(QWidget())
        old_toolbar = QToolBar('Viewport Tools', window)
        old_toolbar.setObjectName('editor.tools')
        window.addToolBar(Qt.LeftToolBarArea, old_toolbar)
        old_toolbar.addAction('Edit Position')
        manager = PanelManager(window, window.menuBar().addMenu('View'), self.settings)
        for identifier, title in (('object_hierarchy', 'Object Hierarchy'), ('properties', 'Properties')):
            manager.register_panel(PanelSpec(identifier, title, QWidget))
        manager.restore_layout()
        window.show()
        self.app.processEvents()
        if customized:
            window.addDockWidget(Qt.LeftDockWidgetArea, manager.docks['object_hierarchy'])
            manager.docks['properties'].hide()
        manager.save_layout()
        window.close()

    def open_editor(self):
        with patch('simuo.ui.main_window.OpenGLViewport', FakeViewport), patch(
            'simuo.ui.docking.QSettings', return_value=self.settings
        ):
            window = SimuOMainWindow()
        self.addCleanup(window.close)
        window.show()
        self.app.processEvents()
        return window

    def assert_compact_layout(self, window, expanded=False):
        viewport, rail = window.viewport, window.viewport_tools
        context = viewport.tool_context
        self.assertIs(rail.parentWidget(), viewport)
        self.assertFalse(window.findChildren(QToolBar))
        self.assertEqual(rail.x(), 8)
        self.assertGreater(rail.y(), context.geometry().bottom())
        self.assertLess(rail.height(), 220)
        self.assertLess(rail.width(), 110 if expanded else 50)
        self.assertTrue(viewport.rect().contains(rail.geometry()))
        widths = {button.width() for button in rail.buttons.values()}
        self.assertEqual(len(widths), 1)
        buttons = list(rail.buttons.values())
        for previous, current in zip(buttons, buttons[1:]):
            self.assertLess(previous.geometry().bottom(), current.y())

    def test_legacy_sidebar_does_not_reclaim_rail_or_leave_an_empty_toolbar_area(self):
        self.save_legacy_layout()
        window = self.open_editor()
        self.assertEqual(window.viewport.x(), 0)
        self.assert_compact_layout(window)
        window.viewport_tools.expand_action.trigger()
        self.app.processEvents()
        self.assert_compact_layout(window, expanded=True)
        window.close()
        reopened = self.open_editor()
        self.assertEqual(reopened.viewport.x(), 0)
        self.assert_compact_layout(reopened)

    def test_migration_preserves_custom_panel_positions_and_visibility(self):
        self.save_legacy_layout(customized=True)
        window = self.open_editor()
        self.assertEqual(window.dockWidgetArea(window.panel_manager.docks['object_hierarchy']), Qt.LeftDockWidgetArea)
        self.assertTrue(window.panel_manager.docks['properties'].isHidden())
        self.assert_compact_layout(window)

    def test_switching_tools_expansion_and_resizing_keep_options_separate(self):
        window = self.open_editor()
        rail = window.viewport_tools
        for size in ((800, 500), (1600, 1000), (1100, 700)):
            window.resize(*size)
            for tool in ('select', 'move', 'rotate', 'scale', 'select'):
                window.toolActions[tool].trigger()
                for expanded in (True, False):
                    rail.expand_action.setChecked(expanded)
                    self.app.processEvents()
                    self.assert_compact_layout(window, expanded)
                    self.assertTrue(window.toolActions[tool].isChecked())
        window.toolsVisibleAction.trigger()
        self.assertTrue(rail.isHidden())
        window.toolsVisibleAction.trigger()
        self.assert_compact_layout(window)

    def test_toolbar_background_clicks_do_not_select_or_move_camera(self):
        class MouseProbe(FakeViewport):
            def mousePressEvent(self, event):
                self.presses += 1

        with patch('simuo.ui.main_window.OpenGLViewport', MouseProbe), patch(
            'simuo.ui.docking.QSettings', return_value=self.settings
        ):
            window = SimuOMainWindow()
        self.addCleanup(window.close)
        window.viewport.presses = 0
        window.show()
        self.app.processEvents()
        for container in (window.viewport_tools, window.viewport.tool_context):
            for button in (Qt.LeftButton, Qt.RightButton):
                QTest.mouseClick(container, button, pos=QPoint(1, 1))
        self.assertEqual(window.viewport.presses, 0)
        QTest.mouseClick(window.viewport, Qt.LeftButton, pos=QPoint(200, 200))
        self.assertEqual(window.viewport.presses, 1)

    def test_option_text_and_arrows_fit_the_minimum_viewport_width(self):
        window = self.open_editor()
        viewport = window.viewport
        viewport.setFixedWidth(320)
        context = viewport.tool_context
        for tool in ('select', 'move', 'rotate', 'scale'):
            window.toolActions[tool].trigger()
            for pivot in ('median', 'active'):
                window.editor_state.set_tool_options(pivot=pivot)
                context.fit_to_width(304)
                self.app.processEvents()
                self.assertLessEqual(context.geometry().right(), 319)
                controls = [context.title, context.orientation_input, context.pivot_input,
                            context.snap_button, context.xray_button]
                controls = [control for control in controls if not control.isHidden()]
                for control in controls:
                    self.assertTrue(context.rect().contains(control.geometry()), control.objectName())
                for index, previous in enumerate(controls):
                    for current in controls[index+1:]:
                        self.assertFalse(previous.geometry().intersects(current.geometry()))
                self.assertGreater(window.viewport_tools.y(), context.geometry().bottom())
                for combo in (context.orientation_input, context.pivot_input):
                    if not combo.isHidden():
                        self.assertLessEqual(combo.fontMetrics().horizontalAdvance(combo.currentText()), combo.width()-36)
                        self.assertEqual(combo.fontMetrics().elidedText(combo.currentText(), Qt.ElideRight, combo.width()-36), combo.currentText())

    def test_dropdown_keyboard_choices_keep_the_same_tool_behavior(self):
        window = self.open_editor()
        window.toolActions['rotate'].trigger()
        context = window.viewport.tool_context
        context.orientation_input.setFocus()
        QTest.keyClick(context.orientation_input, Qt.Key_Down)
        context.pivot_input.setFocus()
        QTest.keyClick(context.pivot_input, Qt.Key_End)
        self.assertEqual(window.editor_state.tool_options['orientation'], 'local')
        self.assertEqual(window.editor_state.tool_options['pivot'], 'active')
        self.assertEqual(window.editor_state.undo_stack.count(), 0)
        self.assertFalse(window.scene.dirty)

    def test_top_bar_shows_only_relevant_controls_with_equal_heights(self):
        window = self.open_editor()
        context = window.viewport.tool_context
        expected = {'select': (False, False, False), 'move': (True, False, True),
                    'rotate': (True, True, True), 'scale': (False, True, True)}
        for tool, visible in expected.items():
            window.toolActions[tool].trigger()
            self.app.processEvents()
            for control, shown in zip((context.orientation_input, context.pivot_input, context.snap_button), visible):
                self.assertEqual(not control.isHidden(), shown)
                if shown:
                    self.assertEqual(control.height(), 26)
                    self.assertTrue(control.toolTip())
            self.assertEqual(context.xray_button.height(), 26)
        self.assertEqual(window.editor_state.undo_stack.count(), 0)
        self.assertFalse(window.scene.dirty)

    def test_dropdown_mouse_click_opens_a_list_below_the_control(self):
        window = self.open_editor()
        window.toolActions['move'].trigger()
        combo = window.viewport.tool_context.orientation_input
        QTest.mouseClick(combo, Qt.LeftButton, pos=QPoint(combo.width()-15, combo.height()//2))
        self.app.processEvents()
        self.assertTrue(combo.view().isVisible())
        popup = combo.view().window()
        self.assertGreaterEqual(popup.geometry().top(), combo.mapToGlobal(QPoint(0, combo.height())).y())
        combo.hidePopup()
