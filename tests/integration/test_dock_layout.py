import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from PySide6.QtCore import QByteArray, QSettings, Qt
from PySide6.QtWidgets import QApplication, QMainWindow, QWidget

from simuo.ui.docking import PanelManager, PanelSpec


class DockLayoutTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        folder = self.enterContext(TemporaryDirectory())
        self.settings_path = Path(folder) / "workspace.ini"

    def create_manager(self):
        window = QMainWindow()
        window.setCentralWidget(QWidget())
        settings = QSettings(str(self.settings_path), QSettings.Format.IniFormat)
        manager = PanelManager(window, window.menuBar().addMenu("View"), settings)
        manager.register_panel(PanelSpec("hierarchy", "Object Hierarchy", QWidget))
        manager.register_panel(PanelSpec("properties", "Properties", QWidget))
        self.addCleanup(window.close)
        return manager

    def test_restore_saved_dock_area_and_visibility(self):
        manager = self.create_manager()
        left = Qt.DockWidgetArea.LeftDockWidgetArea
        manager.window.addDockWidget(left, manager.docks["hierarchy"])
        manager.docks["properties"].hide()
        manager.save_layout()

        restored = self.create_manager()
        restored.restore_layout()

        self.assertEqual(restored.window.dockWidgetArea(restored.docks["hierarchy"]), left)
        self.assertTrue(restored.docks["properties"].isHidden())
        self.assertFalse(restored.docks["properties"].toggleViewAction().isChecked())

    def test_reset_docks_floating_panel_and_reopens_hidden_panel(self):
        manager = self.create_manager()
        manager.docks["hierarchy"].setFloating(True)
        manager.docks["properties"].hide()

        manager.reset_action.trigger()

        for dock in manager.docks.values():
            self.assertFalse(dock.isFloating())
            self.assertFalse(dock.isHidden())
            self.assertEqual(manager.window.dockWidgetArea(dock), Qt.DockWidgetArea.RightDockWidgetArea)

    def test_corrupt_state_keeps_default_layout(self):
        manager = self.create_manager()
        manager.settings.setValue("workspace/state", QByteArray(b"invalid state"))

        manager.restore_layout()

        for dock in manager.docks.values():
            self.assertFalse(dock.isHidden())
            self.assertEqual(manager.window.dockWidgetArea(dock), Qt.DockWidgetArea.RightDockWidgetArea)
