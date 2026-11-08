"""Viewport-local tool modes and their context options."""

from PySide6.QtCore import QSize, Qt
from PySide6.QtGui import QAction, QActionGroup, QColor, QIcon, QPainter, QPen, QPixmap
from PySide6.QtWidgets import QFrame, QLayout, QSizePolicy, QToolButton, QVBoxLayout

from simuo.ui.theme import load_stylesheet
from simuo.ui.viewport_options import ToolOptionsBar, TOOL_TITLES


def tool_icon(kind):
    pixmap = QPixmap(40, 40)
    pixmap.fill(Qt.GlobalColor.transparent)
    painter = QPainter(pixmap)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing)
    painter.scale(2, 2)
    painter.setPen(QPen(QColor("#c1cbd7"), 1.4, Qt.PenStyle.SolidLine,
                        Qt.PenCapStyle.RoundCap, Qt.PenJoinStyle.RoundJoin))
    if kind == "select":
        painter.drawRect(3, 3, 14, 14)
        painter.drawLine(6, 6, 12, 14)
        painter.drawLine(6, 6, 7, 13)
        painter.drawLine(6, 6, 13, 9)
    elif kind == "move":
        painter.drawLine(2, 10, 18, 10)
        painter.drawLine(10, 2, 10, 18)
        for a, b in (((2, 10), (5, 7)), ((2, 10), (5, 13)),
                     ((18, 10), (15, 7)), ((18, 10), (15, 13)),
                     ((10, 2), (7, 5)), ((10, 2), (13, 5)),
                     ((10, 18), (7, 15)), ((10, 18), (13, 15))):
            painter.drawLine(*a, *b)
    elif kind == "rotate":
        painter.drawArc(3, 3, 14, 14, 50 * 16, 285 * 16)
        painter.drawLine(14, 2, 17, 5)
        painter.drawLine(17, 5, 13, 7)
    elif kind == "scale":
        painter.drawRect(3, 10, 7, 7)
        painter.drawLine(8, 12, 17, 3)
        painter.drawLine(12, 3, 17, 3)
        painter.drawLine(17, 3, 17, 8)
    painter.end()
    pixmap.setDevicePixelRatio(2)
    return QIcon(pixmap)


class ViewportToolRail(QFrame):
    """A viewport child that cannot be adopted by QMainWindow.restoreState.

    QToolBar participates in the main window's saved layout even when it was
    created as a child of the viewport. Ordinary tool buttons avoid that layout
    ownership conflict and keep expansion independent of dock restoration.
    """

    def __init__(self, viewport):
        super().__init__(viewport)
        self.setObjectName("viewportToolRail")
        self.setAttribute(Qt.WidgetAttribute.WA_NoMousePropagation)
        self.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Fixed)
        self._layout = QVBoxLayout(self)
        self._layout.setContentsMargins(5, 5, 5, 5)
        self._layout.setSpacing(3)
        self._layout.setSizeConstraint(QLayout.SizeConstraint.SetFixedSize)
        self.buttons = {}

    def add_tool(self, action, *, toggle=False):
        self.addAction(action)
        button = QToolButton(self)
        button.setDefaultAction(action)
        button.setIconSize(QSize(20, 20))
        button.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonIconOnly)
        button.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        button.setAccessibleName(action.text())
        button.setFixedSize(34, 28 if toggle else 34)
        if toggle:
            button.setObjectName("toolLabelsToggle")
        self._layout.addWidget(button)
        self.buttons[action] = button
        return button

    def add_separator(self):
        separator = QFrame(self)
        separator.setObjectName("toolDivider")
        separator.setFixedHeight(1)
        self._layout.addWidget(separator)

    def set_expanded(self, expanded):
        for button in self.buttons.values():
            button.ensurePolished()
            button.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextBesideIcon if expanded
                                      else Qt.ToolButtonStyle.ToolButtonIconOnly)
        # Use the longest tool label rather than a wide, arbitrary expanded size.
        width = max(button.sizeHint().width() for button in self.buttons.values()) + 4 if expanded else 34
        for button in self.buttons.values():
            button.setFixedWidth(width)
        self._layout.activate()
        self.adjustSize()


def create_viewport_tools(viewport, state, visibility_action):
    toolbar = ViewportToolRail(viewport)
    style = load_stylesheet("viewport_tools")
    toolbar.setStyleSheet(style)
    group = QActionGroup(toolbar)
    actions = {}
    descriptions = {
        "select": "Click an object to select it, or drag a rectangle to select several.\nShift-drag adds to selection. Command/Ctrl toggles objects. Select through includes objects behind others.",
        "move": "Select one object and drag a colored arrow along a scene axis.\nEscape or right-click cancels the drag.",
        "rotate": "Viewport rotation is unavailable. Use Rotation in Properties.",
        "scale": "Viewport scaling is unavailable. Use Scale in Properties.",
    }
    for tool, title in TOOL_TITLES.items():
        action = QAction(tool_icon(tool), title, group)
        action.setCheckable(True)
        action.setToolTip(descriptions[tool])
        action.setEnabled(tool in ("select", "move"))
        action.toggled.connect(lambda checked, tool=tool: state.set_tool(tool) if checked else None)
        toolbar.add_tool(action)
        actions[tool] = action
    toolbar.add_separator()
    expand = QAction("Expand tool labels", toolbar)
    expand.setCheckable(True)
    expand.setText("»")
    expand.setToolTip("Expand tool labels")
    expand_button = toolbar.add_tool(expand, toggle=True)
    expand_button.setAccessibleName("Expand tool labels")

    def expand_labels(checked):
        toolbar.set_expanded(checked)
        expand.setText("«" if checked else "»")
        expand.setToolTip("Collapse tool labels" if checked else "Expand tool labels")
        expand_button.setAccessibleName(expand.toolTip())
        viewport.layout_tools()
    expand.toggled.connect(expand_labels)

    context = ToolOptionsBar(viewport, state, style)

    def sync_tool(tool):
        actions[tool].setChecked(True)
        context.title.setToolTip(actions[tool].toolTip())
        viewport.layout_tools()

    state.tool_changed.connect(sync_tool)
    state.tool_options_changed.connect(lambda options: viewport.layout_tools())

    def visibility(visible):
        toolbar.setVisible(visible)
    visibility_action.toggled.connect(visibility)
    viewport.tools_visibility_requested.connect(visibility_action.toggle)
    viewport.tool_sidebar, viewport.tool_context = toolbar, context
    # Expose controls for accessibility and UI regression checks.
    toolbar.orientation_input, toolbar.pivot_input = context.orientation_input, context.pivot_input
    toolbar.snap_button, toolbar.xray_button, toolbar.expand_action = context.snap_button, context.xray_button, expand
    sync_tool(state.active_tool)
    visibility(visibility_action.isChecked())
    return toolbar, actions
