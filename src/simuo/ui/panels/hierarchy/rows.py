"""Stable native object/group rows with inline naming and row controls."""

from PySide6.QtCore import QEvent, QSignalBlocker, QSize, Qt
from PySide6.QtWidgets import QHBoxLayout, QLabel, QLineEdit, QPushButton, QStackedWidget

from simuo.ui.panels.hierarchy.widgets import ObjectNameButton, DropSurface


class ObjectRow(DropSurface):
    def __init__(self, panel, obj):
        super().__init__()
        self.panel, self.obj = panel, obj
        self.is_selected = False
        self.setObjectName("objectRow")
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground)
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self.setFixedHeight(24)
        layout = QHBoxLayout(self)
        layout.setContentsMargins(20, 0, 3, 0)
        layout.setSpacing(3)
        icon = QLabel()
        icon.setPixmap(panel.icons["mesh"].pixmap(16, 16))
        icon.setFixedWidth(18)
        layout.addWidget(icon)
        self.name_stack = QStackedWidget()
        self.name_stack.setMinimumWidth(0)
        self.name_button = ObjectNameButton()
        self.name_button.drag_requested.connect(lambda: panel.start_drag(self))
        self.name_button.installEventFilter(self)
        self.name_button.clicked.connect(lambda: panel.select_row(self.obj.identifier, self.name_button.click_modifiers))
        self.name_button.rename_requested.connect(self.begin_rename)
        self.name_button.context_requested.connect(
            lambda point: self.open_context_menu(self.mapFromGlobal(self.name_button.mapToGlobal(point)))
        )
        self.name_button.setContextMenuPolicy(Qt.ContextMenuPolicy.PreventContextMenu)
        self.name_edit = QLineEdit()
        self.name_edit.setObjectName("rowNameEditor")
        self.name_edit.setAccessibleName("Rename object")
        self.name_edit.setFixedHeight(22)
        self.name_edit.editingFinished.connect(self.finish_rename)
        self.name_edit.installEventFilter(self)
        self.name_stack.addWidget(self.name_button)
        self.name_stack.addWidget(self.name_edit)
        layout.addWidget(self.name_stack, 1)
        self.visibility = QPushButton()
        self.lock = QPushButton()
        for button in (self.visibility, self.lock):
            button.setObjectName("rowControl")
            button.setFixedSize(24, 22)
            button.setIconSize(QSize(16, 16))
            button.installEventFilter(self)
            layout.addWidget(button)
        self.visibility.clicked.connect(lambda: panel.state.set_visibility(self.obj.identifier, not self.obj.editor_visible))
        self.lock.clicked.connect(lambda: panel.state.set_selection_locked(self.obj.identifier, not self.obj.selection_locked))
        self.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.customContextMenuRequested.connect(self.open_context_menu)
        for control in (self.visibility, self.lock):
            control.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
            control.customContextMenuRequested.connect(
                lambda point, widget=control: self.open_context_menu(self.mapFromGlobal(widget.mapToGlobal(point)))
            )
        self.update_object()

    def update_object(self):
        obj = self.obj
        self.name_button.set_name(obj.name)
        if self.name_stack.currentIndex() == 0:
            self.name_edit.setText(obj.name)
        visible = getattr(obj, "viewport_visible", obj.editor_visible)
        locked = getattr(obj, "viewport_locked", obj.selection_locked)
        self.visibility.setIcon(self.panel.icons["visible" if visible else "hidden"])
        self.lock.setIcon(self.panel.icons["locked" if locked else "unlocked"])
        for button, text in ((self.visibility, "Hide in viewport" if obj.editor_visible else "Show in viewport"),
                             (self.lock, "Unlock viewport selection" if obj.selection_locked else "Lock viewport selection")):
            button.setToolTip(text)
            button.setAccessibleName(f"{text}: {obj.name}")
        group = self.panel.state.group_for_object(obj.identifier)
        if group is not None:
            if not group.editor_visible:
                self.visibility.setToolTip(f"Hidden by group: {group.name}. Individual visibility is {'on' if obj.editor_visible else 'off'}.")
            if group.selection_locked:
                self.lock.setToolTip(f"Viewport selection locked by group: {group.name}")
        if getattr(obj, "_isolated_out", False):
            self.visibility.setToolTip("Outside isolated selection. Exit Isolation to restore the view.")
        self.name_button.setStyleSheet("color: " + ("#e4e9ef" if visible else "#7d858f") + ";")

    def set_selected(self, selected):
        self.is_selected = selected
        self.setProperty("selected", selected)
        self.style().unpolish(self)
        self.style().polish(self)
        self.update()

    def begin_rename(self):
        self.panel.state.select(self.obj.identifier)
        self.name_edit.setText(self.obj.name)
        self.name_stack.setCurrentIndex(1)
        self.name_edit.setFocus()
        self.name_edit.selectAll()

    def eventFilter(self, watched, event):
        if watched is not getattr(self, "name_edit", None) and event.type() == QEvent.Type.KeyPress:
            if self.panel.navigate(event, self.obj.identifier):
                return True
        if watched is getattr(self, "name_edit", None) and event.type() == QEvent.Type.KeyPress and event.key() == Qt.Key.Key_Escape:
            with QSignalBlocker(self.name_edit):
                self.name_edit.setText(self.obj.name)
                self.name_stack.setCurrentIndex(0)
            self.name_button.setFocus()
            return True
        return super().eventFilter(watched, event)

    def finish_rename(self):
        if self.name_stack.currentIndex() != 1:
            return
        self.panel.state.rename_object(self.obj.identifier, self.name_edit.text())
        self.name_stack.setCurrentIndex(0)
        self.name_button.set_name(self.obj.name)

    def keyPressEvent(self, event):
        if self.panel.navigate(event, self.obj.identifier):
            return
        if event.key() == Qt.Key.Key_F2:
            self.begin_rename()
            event.accept()
        else:
            super().keyPressEvent(event)

    def mousePressEvent(self, event):
        if event.button() == Qt.MouseButton.RightButton:
            self.open_context_menu(event.position().toPoint())
            event.accept()
            return
        if event.button() == Qt.MouseButton.LeftButton:
            self.setFocus()
            self.panel.select_row(self.obj.identifier, event.modifiers())
            event.accept()
            return
        super().mousePressEvent(event)

    def open_context_menu(self, position):
        self.name_button.setFocus()
        if self.obj.identifier not in self.panel.state.selected_ids:
            self.panel.state.select(self.obj.identifier)
        menu = self.panel.context_menu(self.obj.identifier)
        menu.exec(self.mapToGlobal(position))
        menu.deleteLater()


class GroupRow(ObjectRow):
    def __init__(self, panel, group):
        super().__init__(panel, group)
        self.setObjectName("groupRow")
        self.name_button.clicked.disconnect()
        self.name_button.clicked.connect(lambda: panel.select_group(self.obj.identifier))
        self.visibility.clicked.disconnect()
        self.visibility.clicked.connect(lambda: panel.state.set_group_visibility(self.obj.identifier, not self.obj.editor_visible))
        self.lock.clicked.disconnect()
        self.lock.clicked.connect(lambda: panel.state.set_group_locked(self.obj.identifier, not self.obj.selection_locked))
        self.toggle = QPushButton()
        self.toggle.setObjectName("rowControl")
        self.toggle.setFixedSize(16, 22)
        self.toggle.installEventFilter(self)
        self.toggle.clicked.connect(lambda: panel.toggle_group(self.obj.identifier))
        self.layout().setContentsMargins(3, 0, 3, 0)
        self.layout().insertWidget(0, self.toggle)
        self.layout().itemAt(1).widget().setPixmap(panel.icons["scene"].pixmap(16, 16))
        self.count = QLabel()
        self.count.setStyleSheet("color: #969fa9; font-size: 11px;")
        self.layout().insertWidget(3, self.count)
        self.update_object()

    def update_object(self):
        super().update_object()
        if hasattr(self, "toggle"):
            expanded = self.obj.expanded or self.panel.has_active_filters()
            self.toggle.setText("▾" if expanded else "▸")
            self.toggle.setAccessibleName(f"{'Collapse' if expanded else 'Expand'} group: {self.obj.name}")
            self.count.setText(str(len(self.obj.members)))
            count = len(self.obj.members)
            self.name_button.setToolTip(f"{self.obj.name} · {count} object{'s' if count != 1 else ''}. Drag objects here to move them into this group.")
            self.visibility.setAccessibleName(f"{'Hide' if self.obj.editor_visible else 'Show'} group: {self.obj.name}")
            self.lock.setAccessibleName(f"{'Unlock' if self.obj.selection_locked else 'Lock'} group: {self.obj.name}")

    def begin_rename(self):
        self.name_edit.setText(self.obj.name)
        self.name_stack.setCurrentIndex(1)
        self.name_edit.setFocus()
        self.name_edit.selectAll()

    def finish_rename(self):
        if self.name_stack.currentIndex() == 1:
            self.panel.state.rename_group(self.obj.identifier, self.name_edit.text())
            self.name_stack.setCurrentIndex(0)
            self.name_button.set_name(self.obj.name)

    def mousePressEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            self.setFocus()
            self.panel.select_group(self.obj.identifier)
            event.accept()
        else:
            super().mousePressEvent(event)

    def open_context_menu(self, position):
        self.name_button.setFocus()
        menu = self.panel.group_context_menu(self.obj.identifier)
        menu.exec(self.mapToGlobal(position))
        menu.deleteLater()
