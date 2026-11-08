"""Discoverable controls in the production part-editor menus."""
import unittest
from unittest.mock import patch

from PySide6.QtWidgets import QApplication, QToolBar, QScrollArea
from PySide6.QtGui import QResizeEvent
from PySide6.QtCore import QSize
from simuo.ui.parts.part_editor import PartEditor


class PartMenuTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        self.editor = PartEditor()
        self.addCleanup(self.close)

    def close(self):
        self.editor.dirty = False
        self.editor.close()

    def test_help_view_and_native_save_export_are_easy_to_find(self):
        menus = {a.text(): a.menu() for a in self.editor.menuBar().actions()}
        self.assertTrue({'File','Edit','View','Help'}.issubset(menus))
        file_labels = [a.text() for a in menus['File'].actions()]
        self.assertIn('Save SimuO Part', file_labels)
        self.assertIn('Export', file_labels)
        self.assertEqual(menus['View'].actions()[0].shortcut().toString(), 'F')
        with patch('simuo.ui.parts.part_editor.QMessageBox.information') as message:
            menus['Help'].actions()[0].trigger()
        message.assert_called_once()
        self.assertIn('millimeters', message.call_args.args[2])

    def test_selection_tool_leaves_drawing_without_changing_document(self):
        self.assertTrue(self.editor.canvas.drawing)
        self.editor.select_action.trigger()
        self.assertFalse(self.editor.canvas.drawing)
        self.assertFalse(self.editor.dirty)
        self.editor.line_action.trigger()
        self.assertTrue(self.editor.canvas.drawing)

    def test_toolbar_actions_have_clear_names_and_guidance(self):
        toolbar = self.editor.findChild(QToolBar)
        actions = {a.text(): a for a in toolbar.actions() if not a.isSeparator()}
        self.assertTrue({'Draw lines','Select line','Close outline','Add dimension…','Frame sketch'}.issubset(actions))
        self.assertTrue(all(action.toolTip() for action in actions.values()))

    def test_properties_panel_is_scrollable_and_recovers_after_narrow_layout(self):
        self.assertIsInstance(self.editor.propertiesDock.widget(), QScrollArea)
        self.editor.propertiesDock.show()
        self.editor.resizeEvent(QResizeEvent(QSize(600, 600), QSize(1150, 760)))
        self.assertTrue(self.editor.propertiesDock.isHidden())
        self.editor.resizeEvent(QResizeEvent(QSize(1150, 760), QSize(600, 600)))
        self.assertFalse(self.editor.propertiesDock.isHidden())

if __name__ == '__main__':
    unittest.main()
