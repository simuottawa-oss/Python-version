"""View-menu debug dock behavior in the part editor."""
import unittest

from PySide6.QtWidgets import QApplication, QWidget

from simuo.ui.parts.part_editor import PartEditor


class PartEditorDebugMenuTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        self.editor = PartEditor()
        self.addCleanup(self.close)

    def close(self):
        self.editor.dirty = False
        self.editor.close()

    def test_view_debug_menu_toggles_a_blank_dock(self):
        view_menu = next(
            action.menu()
            for action in self.editor.menuBar().actions()
            if action.text() == "View"
        )
        action = self.editor.debugDock.toggleViewAction()

        self.assertIn(action, view_menu.actions())
        self.assertEqual(action.text(), "Debug Menu")
        self.assertTrue(self.editor.debugDock.isHidden())
        self.assertIsNone(self.editor.debugDock.widget().layout())
        self.assertEqual(self.editor.debugDock.widget().findChildren(QWidget), [])

        action.trigger()
        self.assertFalse(self.editor.debugDock.isHidden())
        self.assertTrue(action.isChecked())

        action.trigger()
        self.assertTrue(self.editor.debugDock.isHidden())
        self.assertFalse(action.isChecked())


if __name__ == "__main__":
    unittest.main()
