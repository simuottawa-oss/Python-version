"""Exercise workspace behavior with real Qt widgets and isolated preferences.

For a display-free run: QT_QPA_PLATFORM=offscreen python -m unittest discover -s tests -v
"""

from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from PySide6.QtCore import QByteArray, QSettings, Qt
from PySide6.QtWidgets import QMainWindow, QWidget

from tests.support.viewports import FakeViewport
from tests.support.qt import get_application

from simuo.ui.docking import PanelManager, PanelSpec

TEST_PANELS = (
    PanelSpec("object_hierarchy", "Object Hierarchy", QWidget, default_height=240),
    PanelSpec("properties", "Properties", QWidget, default_height=400),
)


class PanelWorkspaces(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = get_application()

    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.settings = QSettings(
            str(Path(self.directory.name) / "workspace.ini"), QSettings.Format.IniFormat
        )

    def make_editor(self, specs=TEST_PANELS):
        window = QMainWindow()
        window.resize(1280, 800)
        window.setCentralWidget(QWidget())
        manager = PanelManager(window, window.menuBar().addMenu("View"), self.settings)
        for spec in specs:
            manager.register_panel(spec)
        manager.restore_layout()
        window.show()
        self.app.processEvents()
        self.addCleanup(window.close)
        return window, manager

    def test_view_action_tracks_closing_and_reopening_a_panel(self):
        _, manager = self.make_editor()
        dock = manager.docks["properties"]
        action = dock.toggleViewAction()
        self.assertTrue(action.isChecked())
        dock.close()
        self.assertFalse(action.isChecked())
        self.assertFalse(dock.isVisible())
        action.trigger()
        self.assertTrue(action.isChecked())
        self.assertTrue(dock.isVisible())

    def test_reset_recovers_floating_hidden_and_tabbed_panels(self):
        window, manager = self.make_editor()
        hierarchy, properties = manager.docks.values()
        window.tabifyDockWidget(hierarchy, properties)
        manager.reset_action.trigger()
        self.app.processEvents()
        self.assertEqual(window.tabifiedDockWidgets(hierarchy), [])
        window.tabifyDockWidget(hierarchy, properties)
        properties.setFloating(True)
        hierarchy.hide()
        manager.reset_action.trigger()
        self.app.processEvents()

        for dock in manager.docks.values():
            self.assertTrue(dock.isVisible())
            self.assertTrue(dock.toggleViewAction().isChecked())
            self.assertFalse(dock.isFloating())
            self.assertEqual(window.dockWidgetArea(dock), Qt.DockWidgetArea.RightDockWidgetArea)
            self.assertEqual(window.tabifiedDockWidgets(dock), [])
        self.assertEqual(hierarchy.x(), properties.x())
        self.assertEqual(hierarchy.width(), properties.width())
        self.assertLess(hierarchy.geometry().bottom(), properties.y())
        self.assertLess(hierarchy.height(), properties.height())

    def test_hidden_floating_and_resized_layout_survives_reopening(self):
        window, manager = self.make_editor()
        hierarchy, properties = manager.docks.values()
        window.addDockWidget(Qt.DockWidgetArea.LeftDockWidgetArea, hierarchy)
        window.resizeDocks([hierarchy], [350], Qt.Orientation.Horizontal)
        properties.setFloating(True)
        properties.resize(360, 420)
        properties.hide()
        self.app.processEvents()
        expected_width = hierarchy.width()
        manager.save_layout()
        window.close()

        restored_window, restored = self.make_editor()
        hierarchy, properties = restored.docks.values()
        self.assertEqual(restored_window.dockWidgetArea(hierarchy), Qt.DockWidgetArea.LeftDockWidgetArea)
        self.assertAlmostEqual(hierarchy.width(), expected_width, delta=2)
        self.assertTrue(properties.isFloating())
        self.assertFalse(properties.isVisible())
        self.assertFalse(properties.toggleViewAction().isChecked())
        properties.toggleViewAction().trigger()
        self.assertTrue(properties.isVisible())
        self.assertEqual(properties.size().width(), 360)
        self.assertEqual(properties.size().height(), 420)

    def test_tab_groups_survive_reopening(self):
        window, manager = self.make_editor()
        hierarchy, properties = manager.docks.values()
        window.tabifyDockWidget(hierarchy, properties)
        self.app.processEvents()
        manager.save_layout()
        window.close()
        restored_window, restored = self.make_editor()
        hierarchy, properties = restored.docks.values()
        self.assertIn(properties, restored_window.tabifiedDockWidgets(hierarchy))

    def test_new_panel_is_available_with_an_older_saved_layout(self):
        window, manager = self.make_editor()
        manager.docks["properties"].hide()
        manager.save_layout()
        window.close()
        extra = PanelSpec("future_panel", "Future Panel", QWidget)
        _, restored = self.make_editor((*TEST_PANELS, extra))
        self.assertTrue(restored.docks["future_panel"].isVisible())
        self.assertFalse(restored.docks["properties"].isVisible())

    def test_invalid_saved_layout_falls_back_to_defaults(self):
        self.settings.setValue("workspace/state", QByteArray(b"invalid layout"))
        window, manager = self.make_editor()
        for dock in manager.docks.values():
            self.assertTrue(dock.isVisible())
            self.assertEqual(window.dockWidgetArea(dock), Qt.DockWidgetArea.RightDockWidgetArea)

    def test_editor_menu_order_and_save_on_close(self):
        from simuo.ui.main_window import SimuOMainWindow

        # Keep this integration check independent of an available OpenGL driver.
        with patch("simuo.ui.main_window.OpenGLViewport", FakeViewport), patch(
            "simuo.ui.docking.QSettings", return_value=self.settings
        ):
            window = SimuOMainWindow()
        self.addCleanup(window.close)
        window.show()
        self.app.processEvents()
        self.assertEqual(
            [action.text() for action in window.menuBar().actions()],
            ["File", "Edit", "View", "Window", "Help"],
        )
        self.assertEqual(
            [action.text() for action in window.viewMenu.actions() if not action.isSeparator()],
            ["Viewport Tools", "Frame Selected", "Frame Scene", "Show Selected in Hierarchy", "Isolate Selected",
             "Object Hierarchy", "Properties", "Reset Layout"],
        )
        window.panel_manager.docks["properties"].close()
        window.close()
        self.assertIsInstance(self.settings.value("workspace/state"), QByteArray)
        self.assertIsInstance(self.settings.value("workspace/geometry"), QByteArray)


if __name__ == "__main__":
    unittest.main()
