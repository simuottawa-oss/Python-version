"""Recent-file persistence, optional preview caching, and startup routing."""

import json
import os
from datetime import datetime
from pathlib import Path
import tempfile
import unittest
from unittest.mock import Mock, patch

from tests import ROOT
from PySide6.QtCore import QSettings
from PySide6.QtWidgets import QApplication, QLabel, QToolButton, QWidget, QMessageBox
from simuo.ui import recent_projects as recent
from simuo.ui.startup import SimuOStartMenu


class RecentProjectsTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        folder = tempfile.TemporaryDirectory()
        self.addCleanup(folder.cleanup)
        self.folder = Path(folder.name)
        settings = QSettings(str(self.folder / "preferences.ini"), QSettings.Format.IniFormat)
        patcher = patch.object(recent, "QSettings", return_value=settings)
        patcher.start()
        self.addCleanup(patcher.stop)

    def document(self, name, data):
        path = self.folder / name
        path.write_text(json.dumps(data), encoding="utf-8")
        saved_at = datetime(2026, 11, 12, 12).timestamp()
        os.utime(path, (saved_at, saved_at))
        return path

    def test_recent_order_duplicates_missing_files_and_metadata(self):
        scene = self.document("demo.simuO", {"objects": [{}, {}]})
        part = self.document("demo.simuOPart", {"name": "Wheel", "description": "Drive wheel"})
        recent.remember_project(scene)
        recent.remember_project(part)
        recent.remember_project(scene)
        self.assertEqual(recent.recent_projects(), [str(scene), str(part)])
        self.assertEqual(recent.project_summary(scene), ("demo", "Modified Nov 12, 2026", "Scene"))
        self.assertEqual(recent.project_summary(part), ("Wheel", "Modified Nov 12, 2026", "Part"))
        part.unlink()
        self.assertEqual(recent.recent_projects(), [str(scene)])

    def test_capture_creates_preview_and_failure_preserves_previous_preview(self):
        scene = self.document("saved.simuO", {"objects": []})
        target = self.folder / "cache" / "preview.png"
        viewport = QWidget()
        self.addCleanup(viewport.close)
        viewport.resize(800, 500)
        viewport.show()
        self.app.processEvents()
        with patch.object(recent, "thumbnail_path", return_value=target):
            recent.record_saved_project(scene, viewport)
            self.assertTrue(target.is_file())
            before = target.read_bytes()
            with patch.object(viewport, "grab", side_effect=RuntimeError("unavailable")):
                recent.record_saved_project(scene, viewport)
            self.assertEqual(target.read_bytes(), before)
        self.assertEqual(recent.recent_projects(), [str(scene)])

    def test_cards_display_save_date_and_route_parts_to_part_editor(self):
        scene = self.document("demo.simuO", {"objects": []})
        part = self.document("wheel.simuOPart", {"description": "Drive wheel"})
        recent.remember_project(scene)
        recent.remember_project(part)
        on_scene, on_part = Mock(), Mock()
        menu = SimuOStartMenu(on_import=on_scene, on_open_part=on_part)
        self.addCleanup(menu.close)
        menu.show()
        self.app.processEvents()
        cards = menu.findChildren(QToolButton, "recentProjectCard")
        self.assertEqual(len(cards), 2)
        self.assertEqual(cards[0].findChild(QLabel, "recentProjectDescription").text(), "Modified Nov 12, 2026")
        cards[0].click()
        on_part.assert_called_once_with(str(part))
        on_scene.assert_not_called()

    def test_structural_projects_have_their_own_recent_label(self):
        structural = self.document("design.simuO", {"format": ".simuO", "version": 2, "project_type": "structural", "setup": {}})
        self.assertEqual(recent.project_summary(structural)[2], "Structural")
        recent.remember_project(structural)
        menu = SimuOStartMenu()
        self.addCleanup(menu.close)
        self.assertEqual(menu.findChild(QLabel, "recentProjectKind").text(), "STRUCTURAL ANALYSIS")

    def test_thumbnail_keys_do_not_collide_for_same_named_projects(self):
        a = recent.thumbnail_path(self.folder / "first" / "scene.simuO")
        b = recent.thumbnail_path(self.folder / "second" / "scene.simuO")
        self.assertNotEqual(a, b)

    def test_recent_list_is_limited_to_ten(self):
        for index in range(12):
            recent.remember_project(self.document(f"scene{index}.simuO", {}))
        paths = recent.recent_projects()
        self.assertEqual(len(paths), 10)
        self.assertEqual(Path(paths[0]).name, "scene11.simuO")

    def test_deletion_cancel_failure_and_success(self):
        scene = self.document("demo.simuO", {})
        recent.remember_project(scene)
        menu = SimuOStartMenu()
        self.addCleanup(menu.close)
        card = menu.findChild(QToolButton, "recentProjectCard")
        with patch("simuo.ui.startup.QFile.moveToTrash") as trash, patch(
            "simuo.ui.startup.QMessageBox.question", return_value=QMessageBox.Cancel
        ):
            menu._delete_recent_project(str(scene), card)
            trash.assert_not_called()
        with patch("simuo.ui.startup.QFile.moveToTrash", return_value=(False, "")), patch(
            "simuo.ui.startup.QMessageBox.question", return_value=QMessageBox.Yes
        ), patch("simuo.ui.startup.QMessageBox.warning") as warning:
            menu._delete_recent_project(str(scene), card)
            warning.assert_called_once()
            self.assertEqual(recent.recent_projects(), [str(scene)])
        with patch("simuo.ui.startup.QFile.moveToTrash", return_value=(True, "trash/path")) as trash, patch(
            "simuo.ui.startup.QMessageBox.question", return_value=QMessageBox.Yes
        ):
            menu._delete_recent_project(str(scene), card)
            trash.assert_called_once_with(str(scene))
            self.assertEqual(recent.recent_projects(), [])
            self.assertTrue(card.isHidden())
        # All filesystem deletion was mocked; the test's actual fixture stays intact.
        self.assertTrue(scene.exists())


if __name__ == "__main__":
    unittest.main()
