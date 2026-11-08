"""Register editor panels with stable identifiers and workspace defaults."""

from simuo.ui.docking import PanelSpec
from simuo.ui.panels.hierarchy.panel import HierarchyPanel
from simuo.ui.panels.properties import PropertiesPanel


def editor_panel_specs(state):
    """Register editor content without coupling the docking system to scenes."""
    return (
        PanelSpec("object_hierarchy", "Object Hierarchy", lambda: HierarchyPanel(state), default_width=340, default_height=240),
        PanelSpec("properties", "Properties", lambda: PropertiesPanel(state), default_width=340, default_height=400),
    )
