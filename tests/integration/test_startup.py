"""Qt startup chooser behavior and file-selection routing."""

import unittest
import tempfile
from pathlib import Path
from unittest.mock import Mock, patch

from PySide6.QtWidgets import QApplication, QDialog, QPushButton

from simuo.ui.startup import SimuOStartMenu


class StartupMenuTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def test_chooser_is_qt_and_exposes_all_startup_actions(self):
        menu = SimuOStartMenu(width=900, height=600)
        self.addCleanup(menu.close)

        self.assertIsInstance(menu, QDialog)
        self.assertTrue(menu.isModal())
        self.assertEqual(
            [button.text() for button in menu.findChildren(QPushButton)],
            ["New Scene", "Import Scene…", "New Part", "Open Part…"],
        )

    def test_scene_actions_report_the_selected_path(self):
        on_new = Mock()
        menu = SimuOStartMenu(on_new=on_new, width=900, height=600)
        menu._new_project()
        on_new.assert_called_once_with()
        self.assertEqual(menu.result(), QDialog.DialogCode.Accepted)

        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        scene = Path(temp.name)/"example.simuO"
        scene.write_text('{"version":1,"objects":[]}')
        on_import = Mock()
        menu = SimuOStartMenu(on_import=on_import, width=900, height=600)
        with patch(
            "simuo.ui.startup.QFileDialog.getOpenFileName",
            return_value=(str(scene), ""),
        ):
            menu._import_project()
        on_import.assert_called_once_with(str(scene))
        self.assertEqual(menu.result(), QDialog.DialogCode.Accepted)

    def test_part_actions_and_cancelled_picker(self):
        on_new_part = Mock()
        menu = SimuOStartMenu(on_new_part=on_new_part, width=900, height=600)
        menu._new_part()
        on_new_part.assert_called_once_with()

        on_open_part = Mock()
        menu = SimuOStartMenu(on_open_part=on_open_part, width=900, height=600)
        with patch(
            "simuo.ui.startup.QFileDialog.getOpenFileName",
            return_value=("example.simuOPart", ""),
        ):
            menu._open_part()
        on_open_part.assert_called_once_with("example.simuOPart")

        cancelled = SimuOStartMenu(on_open_part=on_open_part, width=900, height=600)
        with patch("simuo.ui.startup.QFileDialog.getOpenFileName", return_value=("", "")):
            cancelled._open_part()
        self.assertEqual(cancelled.result(), QDialog.DialogCode.Rejected)
        on_open_part.assert_called_once()


if __name__ == "__main__":
    unittest.main()
