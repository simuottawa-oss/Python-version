"""Shared fixtures for tests that open real scene windows."""

from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch
from uuid import uuid4

from PySide6.QtCore import QSettings

from simuo.ui.scene_window import SimuOMainWindow


_layout_dir = TemporaryDirectory(prefix="simuo-test-layouts-")


def create_scene_window(*args, **kwargs):
    """Give each test window its own workspace settings."""
    path = Path(_layout_dir.name) / f"{uuid4()}.ini"
    settings = QSettings(str(path), QSettings.Format.IniFormat)
    with patch("simuo.ui.docking.QSettings", return_value=settings):
        return SimuOMainWindow(*args, **kwargs)
