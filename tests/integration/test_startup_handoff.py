"""Keep the macOS editor separate from the Tk startup chooser."""

from pathlib import Path
import sys
import unittest
from unittest.mock import patch

from simuo import app


class StartupHandoffTests(unittest.TestCase):
    def test_macos_passes_each_menu_choice_to_a_fresh_editor_process(self):
        choices = (
            (("new", None), ["--new"]),
            (("import", Path("my scene.simuO")), ["--", "my scene.simuO"]),
            (("new_part", None), ["--part-editor"]),
            (("open_part", Path("my part.simuOPart")), ["--part-editor", "--", "my part.simuOPart"]),
        )
        with patch.object(sys, "platform", "darwin"), patch.object(sys, "argv", ["src/main.py"]):
            for frozen in (False, True):
                for choice, arguments in choices:
                    with (
                        self.subTest(choice=choice, frozen=frozen),
                        patch.object(sys, "frozen", frozen, create=True),
                        patch.object(app, "startup_menu", return_value=choice),
                        patch.object(app.subprocess, "run") as launch,
                    ):
                        launch.return_value.returncode = 7
                        self.assertEqual(app.main(), 7)
                        entry = [] if frozen else ["src/main.py"]
                        launch.assert_called_once_with([sys.executable, *entry, *arguments], check=False)

    def test_cancelling_menu_does_not_launch_an_editor(self):
        with (
            patch.object(sys, "platform", "darwin"),
            patch.object(sys, "argv", ["src/main.py"]),
            patch.object(app, "startup_menu", return_value=(None, None)),
            patch.object(app.subprocess, "run") as launch,
        ):
            self.assertIsNone(app.main())
            launch.assert_not_called()
