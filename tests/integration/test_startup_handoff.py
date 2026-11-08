"""Verify the Qt chooser's buttons and file selection."""

import unittest
from unittest.mock import patch

from PySide6.QtWidgets import QApplication, QDialog, QPushButton

from simuo.ui.startup_dialog import StartupDialog


class StartupHandoffTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        self.dialog = StartupDialog()
        self.addCleanup(self.dialog.close)
        self.buttons = {button.text(): button for button in self.dialog.findChildren(QPushButton)}

    def test_new_scene_and_part_choose_the_matching_editor(self):
        for label, action in (("New Scene", "new"), ("New Part", "new_part")):
            with self.subTest(label=label):
                self.buttons[label].click()
                self.assertEqual(self.dialog.result(), QDialog.DialogCode.Accepted)
                self.assertEqual(self.dialog.choice, (action, None))

    def test_import_scene_and_open_part_preserve_the_selected_path(self):
        for label, action, path in (
            ("Import Scene", "import", "my scene.simuO"),
            ("Open Part…", "open_part", "my part.simuOPart"),
        ):
            with self.subTest(label=label), patch(
                "simuo.ui.startup_dialog.QFileDialog.getOpenFileName", return_value=(path, "")
            ):
                self.buttons[label].click()
                self.assertEqual(self.dialog.result(), QDialog.DialogCode.Accepted)
                self.assertEqual(self.dialog.choice, (action, path))

    def test_cancelling_file_picker_leaves_chooser_open(self):
        with patch("simuo.ui.startup_dialog.QFileDialog.getOpenFileName", return_value=("", "")):
            self.dialog.show()
            self.buttons["Import Scene"].click()
        self.assertTrue(self.dialog.isVisible())
        self.assertEqual(self.dialog.choice, (None, None))
