"""Locate shipped resources independently of the working directory."""

from pathlib import Path
import sys


def resource_path(*parts):
    """Locate an application resource relative to the checkout or PyInstaller extraction
    directory, independently of the current working directory.

    Args:
        *parts (str or Path): Variadic path components below the application resource
            root.

    Returns:
        pathlib.Path: Joined resource path; existence is not checked.
    """
    base = Path(sys._MEIPASS) if getattr(sys, "frozen", False) else Path(__file__).resolve().parents[3]
    return base.joinpath(*parts)
