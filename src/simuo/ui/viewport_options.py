"""Clear viewport option labels, consistent dropdowns, and hover explanations."""

from PySide6.QtCore import QPoint, QPointF, QRectF, QSize, Qt, QSignalBlocker
from PySide6.QtGui import QColor, QPainter, QPen
from PySide6.QtWidgets import (
    QComboBox, QFrame, QHBoxLayout, QLabel, QSizePolicy,
    QStyleFactory, QToolButton, QVBoxLayout,
)

TOOL_TITLES = {'select': 'Select', 'move': 'Move', 'rotate': 'Rotate', 'scale': 'Scale'}


class ToolOptionCombo(QComboBox):
    """Reserve separate text/arrow space and avoid macOS popup bezels.

    Keep Qt's combo box keyboard and accessibility behavior. Fusion supplies a
    regular popup list, positioned explicitly below the control. Painting the
    closed control once avoids mixing native and stylesheet arrows.
    """

    def __init__(self, parent=None):
        super().__init__(parent)
        self._popup_style = QStyleFactory.create('Fusion')
        self._popup_style.setParent(self)
        self.setStyle(self._popup_style)
        self.setAttribute(Qt.WidgetAttribute.WA_Hover)
        self.setFixedHeight(26)
        self.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Fixed)

    def sizeHint(self):
        text_width = max((self.fontMetrics().horizontalAdvance(self.itemText(index))
                          for index in range(self.count())), default=0)
        return QSize(text_width + 40, 26)

    def minimumSizeHint(self):
        return self.sizeHint()

    def showPopup(self):
        super().showPopup()
        popup = self.view().window()
        available = self.screen().availableGeometry()
        anchor = self.mapToGlobal(QPoint(0, self.height()+3))
        x = max(available.left(), min(anchor.x(), available.right()-popup.width()+1))
        y = anchor.y()
        if y + popup.height() > available.bottom()+1:
            y = max(available.top(), self.mapToGlobal(QPoint(0, 0)).y()-popup.height()-3)
        popup.move(x, y)

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        enabled = self.isEnabled()
        border = '#81add7' if enabled and (self.hasFocus() or self.underMouse()) else '#4b5867'
        painter.setPen(QPen(QColor(border), 1))
        painter.setBrush(QColor('#343c47' if enabled else '#2b323c'))
        painter.drawRoundedRect(QRectF(self.rect()).adjusted(.5, .5, -.5, -.5), 3, 3)
        color = QColor('#d5dde7' if enabled else '#95a2b3')
        painter.setPen(color)
        text_rect = self.rect().adjusted(8, 1, -28, -1)
        text = self.fontMetrics().elidedText(self.currentText(), Qt.TextElideMode.ElideRight, text_rect.width())
        painter.drawText(text_rect, Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter, text)
        painter.setPen(QPen(color, 1.5, Qt.PenStyle.SolidLine,
                            Qt.PenCapStyle.RoundCap, Qt.PenJoinStyle.RoundJoin))
        x, y = self.width()-15, self.height()/2
        painter.drawLine(QPointF(x-4, y-2), QPointF(x, y+2))
        painter.drawLine(QPointF(x, y+2), QPointF(x+4, y-2))
        painter.end()


class ToolOptionsBar(QFrame):
    def __init__(self, viewport, state, stylesheet):
        super().__init__(viewport)
        self.setObjectName('toolContext')
        self.setAttribute(Qt.WidgetAttribute.WA_NoMousePropagation)
        self.setStyleSheet(stylesheet)
        self._state = state
        layout = QVBoxLayout(self)
        layout.setContentsMargins(8, 2, 6, 2)
        layout.setSpacing(4)
        self._controls = []
        self._grouping = None
        self.title = QLabel('Select', self)
        self.title.setObjectName('activeToolLabel')
        self._controls.append(self.title)
        self.orientation_input = orientation = ToolOptionCombo(self)
        orientation.setAccessibleName('Handle directions')
        orientation.addItem('Scene axes', 'world')
        orientation.addItem('Object axes', 'local')
        orientation.setToolTip('Move currently uses scene axes.')
        orientation.setEnabled(False)
        self._controls.append(orientation)
        self.pivot_input = pivot = ToolOptionCombo(self)
        pivot.setAccessibleName('Center for rotation and scaling')
        pivot.addItem('Selection center', 'median')
        pivot.addItem('Last selected', 'active')
        pivot.setToolTip('Pivot options are unavailable.')
        pivot.setEnabled(False)
        self._controls.append(pivot)
        self.snap_button = snap = QToolButton(self)
        snap.setText('Snap')
        snap.setCheckable(True)
        snap.setFixedHeight(26)
        snap.setToolTip('Viewport transform snapping is unavailable.')
        snap.setEnabled(False)
        self._controls.append(snap)
        self.xray_button = through = QToolButton(self)
        through.setText('Select through')
        through.setCheckable(True)
        through.setFixedHeight(26)
        through.setToolTip('Select through objects (X-Ray)\nOn: a selection rectangle includes objects behind other surfaces.\nOff: only visible surfaces count. Hidden and locked objects stay excluded.')
        through.toggled.connect(lambda checked: state.set_tool_options(xray=checked))
        self._controls.append(through)
        state.tool_changed.connect(self.sync)
        state.tool_options_changed.connect(self.sync)
        self.sync()

    def fit_to_width(self, width):
        # Wrap whole controls instead of clipping their text in narrow viewports.
        groups, row, used = [], [], 0
        available = max(1, width-16)
        for control in self._controls:
            if control.isHidden():
                continue
            control.ensurePolished()
            if isinstance(control, ToolOptionCombo):
                # Native layout-item margins must not shrink the painted text area.
                control.setFixedWidth(control.sizeHint().width())
            needed = control.width() if control.minimumWidth() == control.maximumWidth() else control.sizeHint().width()
            if row and used + 6 + needed > available:
                groups.append(tuple(row))
                row, used = [], 0
            used += needed + (6 if row else 0)
            row.append(control)
        if row:
            groups.append(tuple(row))
        grouping = tuple(groups)
        if grouping != self._grouping:
            while self.layout().count():
                old_row = self.layout().takeAt(0).layout()
                while old_row.count():
                    old_row.takeAt(0)
                old_row.setParent(None)
            for controls in grouping:
                line = QHBoxLayout()
                line.setSpacing(6)
                line.setContentsMargins(0, 0, 0, 0)
                for control in controls:
                    line.addWidget(control, 0, Qt.AlignmentFlag.AlignVCenter)
                line.addStretch()
                self.layout().addLayout(line)
            self._grouping = grouping
        self.layout().invalidate()
        self.layout().activate()
        hint = self.sizeHint()
        self.setGeometry(8, 8, min(hint.width(), width), hint.height())

    def sync(self, *args):
        tool, options = self._state.active_tool, self._state.tool_options
        orientation, pivot, snap, through = self.orientation_input, self.pivot_input, self.snap_button, self.xray_button
        with QSignalBlocker(through):
            through.setChecked(options['xray'])
        self.title.setText(TOOL_TITLES[tool])
        for control in (orientation, pivot, snap):
            control.setVisible(tool == 'move')
        through.setVisible(tool == 'select')
