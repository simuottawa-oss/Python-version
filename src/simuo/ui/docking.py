"""Reusable editor panels and local workspace layout preferences."""

from collections import defaultdict
from dataclasses import dataclass
from typing import Callable

from PySide6.QtCore import QByteArray, QSettings, Qt, QTimer
from PySide6.QtWidgets import QDockWidget, QMainWindow, QWidget


@dataclass(frozen=True)
class PanelSpec:
    """A stable layout ID and a content factory for one editor panel."""

    identifier: str
    title: str
    create_content: Callable[[], QWidget]
    default_area: Qt.DockWidgetArea = Qt.DockWidgetArea.RightDockWidgetArea
    default_width: int = 280
    default_height: int = 300


class PanelManager:
    """Own dock containers, View actions, and application-local layout storage.

    Register all panels before restoring a layout. Keep their identifiers stable
    so saved workspaces continue to recognize them as content is added later.
    """

    LAYOUT_VERSION = 1

    def __init__(self, window, view_menu, settings=None):
        self.window = window
        self.view_menu = view_menu
        self.settings = settings if settings is not None else QSettings("SimuOttawa", "SimuO")
        self.docks = {}
        self._specs = {}

        window.setDockOptions(
            QMainWindow.DockOption.AllowNestedDocks
            | QMainWindow.DockOption.AllowTabbedDocks
        )
        # Avoid continuous animated resizing of the OpenGL viewport while docking.
        window.setAnimated(False)
        self._menu_separator = view_menu.addSeparator()
        self.reset_action = view_menu.addAction("Reset Layout")
        self.reset_action.triggered.connect(self.reset_layout)

    def register_panel(self, spec):
        """Add one panel and its synchronized show/hide action to View."""
        if spec.identifier in self.docks:
            raise ValueError(f"Panel already registered: {spec.identifier}")

        dock = QDockWidget(spec.title, self.window)
        dock.setObjectName(f"panel.{spec.identifier}")
        dock.setAllowedAreas(Qt.DockWidgetArea.AllDockWidgetAreas)
        dock.setFeatures(
            QDockWidget.DockWidgetFeature.DockWidgetClosable
            | QDockWidget.DockWidgetFeature.DockWidgetMovable
            | QDockWidget.DockWidgetFeature.DockWidgetFloatable
        )
        dock.setWidget(spec.create_content())
        self.window.addDockWidget(spec.default_area, dock)
        self.view_menu.insertAction(self._menu_separator, dock.toggleViewAction())
        self.docks[spec.identifier] = dock
        self._specs[spec.identifier] = spec
        return dock

    def reset_layout(self):
        """Reopen every panel in its default dock area and size."""
        groups = defaultdict(list)
        for identifier, dock in self.docks.items():
            self.window.removeDockWidget(dock)
            spec = self._specs[identifier]
            groups[spec.default_area].append((dock, spec))

        for area, panels in groups.items():
            vertical = area in (
                Qt.DockWidgetArea.LeftDockWidgetArea,
                Qt.DockWidgetArea.RightDockWidgetArea,
            )
            orientation = Qt.Orientation.Vertical if vertical else Qt.Orientation.Horizontal
            previous = None
            for dock, spec in panels:
                self.window.addDockWidget(area, dock)
                dock.setFloating(False)
                if previous is not None:
                    self.window.splitDockWidget(previous, dock, orientation)
                dock.show()
                previous = dock

            docks = [dock for dock, _ in panels]
            self.window.resizeDocks(
                docks, [spec.default_width for _, spec in panels], Qt.Orientation.Horizontal
            )
            self.window.resizeDocks(
                docks, [spec.default_height for _, spec in panels], Qt.Orientation.Vertical
            )

    def restore_layout(self):
        """Start with defaults, then restore this application's saved workspace."""
        self.reset_layout()
        geometry = self.settings.value("workspace/geometry")
        state = self.settings.value("workspace/state")
        if isinstance(geometry, QByteArray):
            self.window.restoreGeometry(geometry)
        if isinstance(state, QByteArray):
            if not self.window.restoreState(state, self.LAYOUT_VERSION):
                self.reset_layout()
        # Native macOS windows can lose a hidden floating dock's size during
        # restoreState. Reapply geometry after the initial native resize events.
        for identifier, dock in self.docks.items():
            geometry = self.settings.value(f"workspace/floating/{identifier}")
            if dock.isFloating() and isinstance(geometry, QByteArray):
                dock.restoreGeometry(geometry)
                QTimer.singleShot(
                    0, dock, lambda d=dock, g=geometry: d.restoreGeometry(g) if d.isFloating() else None
                )

    def save_layout(self):
        """Save user interface preferences independently of scene files."""
        self.settings.setValue("workspace/geometry", self.window.saveGeometry())
        self.settings.setValue("workspace/state", self.window.saveState(self.LAYOUT_VERSION))
        for identifier, dock in self.docks.items():
            key = f"workspace/floating/{identifier}"
            if dock.isFloating():
                self.settings.setValue(key, dock.saveGeometry())
            else:
                self.settings.remove(key)
        self.settings.sync()
