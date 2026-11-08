"""Scene outliner filtering, selection, navigation, and drag/drop coordination.

Rows use ordinary widgets rather than Qt's synthetic table accessibility cells,
which have an ownership defect on macOS in Qt 6.11.2 (QTBUG-149612).
"""

import json

from PySide6.QtCore import QEvent, QMimeData, QSignalBlocker, QSize, Qt
from PySide6.QtGui import QActionGroup, QDrag
from PySide6.QtWidgets import (
    QHBoxLayout, QLabel, QLineEdit, QMenu, QPushButton, QScrollArea,
    QSizePolicy, QStackedWidget, QToolButton, QVBoxLayout, QWidget,
)

from simuo.ui.panels.hierarchy.icons import outliner_icon
from simuo.ui.panels.hierarchy.rows import ObjectRow, GroupRow
from simuo.ui.panels.hierarchy.widgets import SceneHeaderButton, DropSurface
from simuo.ui.theme import load_stylesheet


class HierarchyPanel(QWidget):
    def __init__(self, state):
        super().__init__()
        self.state = state
        self.rows = {}
        self.group_rows = {}
        self._cursor_key = None
        self._group_selecting = False
        self._selecting_rows = False
        self._drop_widget = None
        self.selected_id = None
        self._anchor_id = None
        self._filter_active = False
        self._expanded_before_filter = True
        self.visibility_filter = "all"
        self.lock_filter = "all"
        self.setObjectName("hierarchyPanel")
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self.setMinimumSize(220, 120)
        self.setStyleSheet(load_stylesheet("hierarchy"))
        self.icons = {"mesh": outliner_icon("mesh"), "scene": outliner_icon("scene"),
                      "visible": outliner_icon("eye"), "hidden": outliner_icon("eye", False),
                      "locked": outliner_icon("lock"), "unlocked": outliner_icon("lock", False)}
        layout = QVBoxLayout(self)
        layout.setContentsMargins(6, 6, 6, 3)
        layout.setSpacing(5)
        self.search = QLineEdit()
        self.search.setPlaceholderText("Search objects…")
        self.search.setAccessibleName("Search objects")
        self.search.setClearButtonEnabled(True)
        self.search.setFixedHeight(28)
        tools = QHBoxLayout()
        tools.setSpacing(4)
        tools.addWidget(self.search, 1)
        self.filter_button = self.action_button("filter", "Filter objects")
        self.filter_button.setObjectName("hierarchyFilters")
        self.filter_button.setPopupMode(QToolButton.ToolButtonPopupMode.InstantPopup)
        self.filter_menu = QMenu(self.filter_button)
        self.filter_actions = {}
        for attribute, title, options in (
            ("visibility_filter", "Visibility", (("all", "All Objects"), ("visible", "Visible"), ("hidden", "Hidden"))),
            ("lock_filter", "Selection Lock", (("all", "All Objects"), ("locked", "Locked"), ("unlocked", "Unlocked"))),
        ):
            submenu = self.filter_menu.addMenu(title)
            actions = QActionGroup(submenu)
            actions.setExclusive(True)
            self.filter_actions[attribute] = {}
            for value, label in options:
                action = submenu.addAction(label)
                action.setCheckable(True)
                action.setChecked(value == "all")
                actions.addAction(action)
                action.triggered.connect(lambda checked=False, a=attribute, v=value: self.set_filter(a, v))
                self.filter_actions[attribute][value] = action
        self.filter_menu.addSeparator()
        self.filter_menu.addAction("Reset Filters", self.clear_filters)
        self.filter_button.setMenu(self.filter_menu)
        tools.addWidget(self.filter_button)
        self.new_group = self.action_button("group_add", "New group")
        self.new_group.setToolTip("New group from selection (or an empty group)")
        self.new_group.setAccessibleName("New group")
        self.new_group.clicked.connect(self.create_group)
        self.reveal_button = self.action_button("reveal", "Show Selected")
        self.reveal_button.setToolTip("Show selected objects in the hierarchy. Clear search and filters and expand their groups.")
        self.reveal_button.setAccessibleName("Show Selected")
        self.reveal_button.clicked.connect(self.show_selected)
        layout.addLayout(tools)
        self.filter_summary_row = QWidget()
        filter_summary_layout = QHBoxLayout(self.filter_summary_row)
        filter_summary_layout.setContentsMargins(1, 0, 0, 0)
        self.filter_summary = QLabel()
        self.filter_summary.setObjectName("filterSummary")
        filter_summary_layout.addWidget(self.filter_summary, 1)
        self.clear_filters_button = QPushButton("Clear")
        self.clear_filters_button.setObjectName("clearHierarchyFilters")
        self.clear_filters_button.setAccessibleName("Clear object filters")
        self.clear_filters_button.clicked.connect(self.clear_filters)
        filter_summary_layout.addWidget(self.clear_filters_button)
        layout.addWidget(self.filter_summary_row)
        self.scene_toggle = SceneHeaderButton()
        self.scene_toggle.setObjectName("sceneToggle")
        self.scene_toggle.setIcon(self.icons["scene"])
        self.scene_toggle.setIconSize(QSize(16, 16))
        self.scene_toggle.setFixedHeight(26)
        self.scene_toggle.setMinimumWidth(0)
        self.scene_toggle.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Fixed)
        self.scene_toggle.setCheckable(True)
        self.scene_toggle.setChecked(True)
        scene_header = QHBoxLayout()
        scene_header.setSpacing(2)
        scene_header.addWidget(self.scene_toggle, 1)
        scene_header.addWidget(self.new_group)
        scene_header.addWidget(self.reveal_button)
        self.isolation_button = self.action_button("isolate", "Isolate Selected")
        self.isolation_button.setCheckable(True)
        self.isolation_button.toggled.connect(self.set_isolation)
        scene_header.addWidget(self.isolation_button)
        layout.addLayout(scene_header)
        self.stack = QStackedWidget()
        for text in ("No objects in this scene.\nUse File → Import to add a model.",
                     "No matching objects.\nClear search or reset the filters."):
            label = QLabel(text)
            label.setObjectName("hierarchyEmpty")
            label.setWordWrap(True)
            label.setAlignment(Qt.AlignmentFlag.AlignCenter)
            label.installEventFilter(self)
            self.stack.addWidget(label)
        self.scroll = QScrollArea()
        self.scroll.setWidgetResizable(True)
        self.scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        contents = DropSurface(self)
        contents.installEventFilter(self)
        self.scroll.viewport().installEventFilter(self)
        contents.setObjectName("hierarchyContents")
        self.rows_layout = QVBoxLayout(contents)
        self.rows_layout.setContentsMargins(0, 0, 0, 0)
        self.rows_layout.setSpacing(0)
        self.rows_layout.addStretch()
        self.scroll.setWidget(contents)
        self.stack.addWidget(self.scroll)
        self.stack.installEventFilter(self)
        layout.addWidget(self.stack, 1)
        self.status = QLabel()
        self.status.setObjectName("hierarchyStatus")
        self.status.setWordWrap(True)
        layout.addWidget(self.status)
        for widget in (contents, self.scroll.viewport(), self.scene_toggle):
            widget.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
            widget.customContextMenuRequested.connect(lambda point, widget=widget: self.open_background_menu(widget, point))
        self.scene_toggle.toggled.connect(self._set_expanded)
        self.search.textChanged.connect(self._filter)
        state.objects_changed.connect(self.refresh)
        state.selection_changed.connect(self._sync_selection)
        state.object_changed.connect(self._sync_object)
        state.scene_name_changed.connect(self._scene_name)
        state.view_changed.connect(self._sync_view)
        self._scene_name(state.scene_name)
        self.refresh()

    def sizeHint(self):
        return QSize(340, 240)

    def action_button(self, kind, label):
        button = QToolButton()
        button.setProperty("outlinerAction", True)
        button.setFixedSize(26, 26)
        button.setIconSize(QSize(16, 16))
        button.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonIconOnly)
        button.setIcon(outliner_icon(kind))
        button.setText(label)
        button.setAccessibleName(label)
        button.setToolTip(label)
        return button

    def keyPressEvent(self, event):
        if self.navigate(event, self._cursor_key):
            return
        if event.key() == Qt.Key.Key_Escape and self.state.isolated_ids is not None:
            self.state.exit_isolation()
            event.accept()
            return
        if event.key() == Qt.Key.Key_F and event.modifiers() == Qt.KeyboardModifier.NoModifier:
            self.state.frame_selected()
            event.accept()
        elif event.key() == Qt.Key.Key_F and event.modifiers() == Qt.KeyboardModifier.ShiftModifier:
            self.state.frame_scene()
            event.accept()
        else:
            super().keyPressEvent(event)

    def eventFilter(self, watched, event):
        if event.type() == QEvent.Type.MouseButtonPress and event.button() == Qt.MouseButton.LeftButton:
            self.clear_selection()
        return super().eventFilter(watched, event)

    def mousePressEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            self.clear_selection()
            event.accept()
        else:
            super().mousePressEvent(event)

    def clear_selection(self):
        # Finish edits on the previous selection before updating the inspector.
        self.setFocus()
        self.state.select(None)
        self._cursor_key = None
        self._anchor_id = None

    def select_row(self, identifier, modifiers=Qt.KeyboardModifier.NoModifier):
        self._cursor_key = identifier
        matching = self.visible_object_ids()
        toggle = bool(modifiers & (Qt.KeyboardModifier.ControlModifier | Qt.KeyboardModifier.MetaModifier))
        self._selecting_rows = True
        try:
            if modifiers & Qt.KeyboardModifier.ShiftModifier and self._anchor_id in matching and identifier in matching:
                start, end = sorted((matching.index(self._anchor_id), matching.index(identifier)))
                selection = matching[start:end + 1]
                # The clicked endpoint is active, including upward ranges.
                selection = [key for key in selection if key != identifier] + [identifier]
                existing = [key for key in self.state.selected_ids if key != identifier]
                self.state.select_many((*existing, *selection) if toggle else selection)
            elif toggle:
                self.state.toggle_selection(identifier)
                self._anchor_id = identifier
            else:
                self.state.select(identifier)
                self._anchor_id = identifier
        finally:
            self._selecting_rows = False

    def refresh(self):
        identifiers = {obj.identifier for obj in self.state.scene.objects}
        for identifier in list(self.rows):
            if identifier not in identifiers:
                row = self.rows.pop(identifier)
                self.rows_layout.removeWidget(row)
                row.hide()
                row.deleteLater()
        for obj in self.state.scene.objects:
            if obj.identifier not in self.rows:
                self.rows[obj.identifier] = ObjectRow(self, obj)
            self.rows[obj.identifier].obj = obj
            self.rows[obj.identifier].update_object()
            group = self.state.group_for_object(obj.identifier)
            self.rows[obj.identifier].layout().setContentsMargins(36 if group else 20, 0, 3, 0)
        group_ids = {group.identifier for group in self.state.scene.groups}
        for key in list(self.group_rows):
            if key not in group_ids:
                row = self.group_rows.pop(key)
                self.rows_layout.removeWidget(row)
                row.hide()
                row.deleteLater()
        for group in self.state.scene.groups:
            if group.identifier not in self.group_rows:
                self.group_rows[group.identifier] = GroupRow(self, group)
            self.group_rows[group.identifier].obj = group
            self.group_rows[group.identifier].update_object()
        index = 0
        for key in self.state.scene.root_order:
            group = self.state.find_group(key)
            for child in (key, *group.members) if group else (key,):
                row = self.group_rows.get(child) or self.rows.get(child)
                if row is not None:
                    self.rows_layout.insertWidget(index, row)
                    index += 1
        self._apply_filter()
        self._sync_selection(self.state.selected_object, reveal=False)

    def _scene_name(self, name):
        self.scene_toggle.set_scene_name(name)

    def _set_expanded(self, expanded):
        self.stack.setVisible(expanded)
        self._scene_name(self.state.scene_name)

    def _filter(self, text):
        self._filters_changed()

    def has_state_filters(self):
        return self.visibility_filter != "all" or self.lock_filter != "all"

    def has_active_filters(self):
        return bool(self.search.text().strip()) or self.has_state_filters()

    def set_filter(self, attribute, value):
        if attribute not in self.filter_actions or value not in self.filter_actions[attribute]:
            raise ValueError("Unknown hierarchy filter")
        setattr(self, attribute, value)
        self.filter_actions[attribute][value].setChecked(True)
        self._filters_changed()

    def clear_filters(self, *, include_search=False):
        self.visibility_filter = self.lock_filter = "all"
        for actions in self.filter_actions.values():
            actions["all"].setChecked(True)
        if include_search:
            with QSignalBlocker(self.search):
                self.search.clear()
        self._filters_changed()

    def _filters_changed(self):
        active = self.has_active_filters()
        if active and not self._filter_active:
            self._expanded_before_filter = self.scene_toggle.isChecked()
        if active:
            self.scene_toggle.setChecked(True)
        elif self._filter_active:
            self.scene_toggle.setChecked(self._expanded_before_filter)
        self._filter_active = active
        self._apply_filter()

    def _matches_state(self, obj):
        if self.visibility_filter != "all" and obj.viewport_visible != (self.visibility_filter == "visible"):
            return False
        if self.lock_filter != "all" and obj.viewport_locked != (self.lock_filter == "locked"):
            return False
        return True

    def matching_ids(self):
        query = self.search.text().strip().casefold()
        result = []
        for key in self.state.ordered_object_ids():
            obj = self.state.find_object(key)
            group = self.state.group_for_object(key)
            if obj is not None and self._matches_state(obj) and (query in obj.name.casefold() or group is not None and query in group.name.casefold()):
                result.append(key)
        return result

    def visible_object_ids(self):
        active = self.has_active_filters()
        return [key for key in self.matching_ids() if active or self.state.group_for_object(key) is None
                or self.state.group_for_object(key).expanded]

    def _apply_filter(self):
        matching = set(self.visible_object_ids())
        for identifier, row in self.rows.items():
            row.setVisible(identifier in matching)
        query = self.search.text().strip().casefold()
        shown_groups = 0
        for key, row in self.group_rows.items():
            row.update_object()
            shown = (not self.has_active_filters() or any(child in matching for child in row.obj.members)
                     or not self.has_state_filters() and query in row.obj.name.casefold())
            row.setVisible(shown)
            shown_groups += shown
        self.stack.setCurrentIndex(0 if not self.rows and not self.group_rows else 1 if not matching and not shown_groups else 2)
        self._update_status()

    def _update_status(self):
        count, total = len(self.matching_ids()), len(self.rows)
        text = f"{count} of {total} objects" if self.has_active_filters() else f"{total} object{'s' if total != 1 else ''}"
        if self.group_rows:
            text += f" · {len(self.group_rows)} group{'s' if len(self.group_rows) != 1 else ''}"
        selected = self.state.selected_ids
        if selected:
            text += f" · {len(selected)} selected"
            if any(key not in self.matching_ids() for key in selected):
                text += " (filtered)"
        isolated = self.state.isolated_ids is not None
        if isolated:
            text += " · Isolated view"
        self.status.setText(text)
        labels = {"visible": "Visible", "hidden": "Hidden", "locked": "Locked", "unlocked": "Unlocked"}
        filters = [labels[value] for value in (self.visibility_filter, self.lock_filter) if value != "all"]
        self.filter_summary.setText(" · ".join(filters))
        self.filter_summary_row.setVisible(bool(filters))
        self.filter_button.setToolTip("Filter objects: " + (" · ".join(filters) if filters else "All objects")
                                      + "\nIncludes inherited group visibility/locks and temporary isolation.")
        if self.filter_button.property("filterActive") != bool(filters):
            self.filter_button.setProperty("filterActive", bool(filters))
            self.filter_button.style().unpolish(self.filter_button)
            self.filter_button.style().polish(self.filter_button)
        self.reveal_button.setEnabled(bool(selected))
        isolation_label = "Exit Isolation" if isolated else "Isolate Selected"
        self.isolation_button.setText(isolation_label)
        self.isolation_button.setAccessibleName(isolation_label)
        self.isolation_button.setToolTip("Exit isolation and restore the scene (Escape)" if isolated
                                         else "Isolate selected objects temporarily. Click again or press Escape to restore the scene.")
        with QSignalBlocker(self.isolation_button):
            self.isolation_button.setChecked(isolated)
        self.isolation_button.setEnabled(isolated or bool(selected))

    def _sync_selection(self, obj, reveal=True):
        self.selected_id = obj.identifier if obj is not None else None
        selected = set(self.state.selected_ids)
        for identifier, row in self.rows.items():
            if row.is_selected != (identifier in selected):
                row.set_selected(identifier in selected)
        for row in self.group_rows.values():
            row.set_selected(bool(row.obj.members) and all(key in selected for key in row.obj.members))
        if obj is not None and not self._group_selecting:
            self._cursor_key = obj.identifier
            if not self._selecting_rows:
                self._anchor_id = obj.identifier
        elif obj is None and not self._group_selecting and not self._selecting_rows:
            self._cursor_key = None
            self._anchor_id = None
        if obj is not None and obj.identifier in self.matching_ids() and reveal and not self._group_selecting:
            self.scene_toggle.setChecked(True)
            group = self.state.group_for_object(obj.identifier)
            if group is not None:
                group.expanded = True
                self._apply_filter()
            self.scroll.ensureWidgetVisible(self.rows[obj.identifier])
        self._update_status()

    def _sync_object(self, obj):
        row = self.rows.get(obj.identifier) or self.group_rows.get(obj.identifier)
        if row is not None:
            row.update_object()
            self._apply_filter()

    def context_menu(self, identifier):
        obj = self.state.find_object(identifier)
        menu = QMenu(self)
        if obj is None:
            return menu
        rename = menu.addAction("Rename\tF2")
        rename.setEnabled(len(self.state.selected_ids) <= 1)
        rename.triggered.connect(self.rows[identifier].begin_rename)
        frame = menu.addAction("Frame Selected\tF")
        frame.setEnabled(any(item.viewport_visible for item in self.state.selected_objects))
        frame.triggered.connect(self.state.frame_selected)
        menu.addSeparator()
        keys = self.state.selected_ids if identifier in self.state.selected_ids else (identifier,)
        objects = self.state._objects(keys)
        visible = any(item.editor_visible for item in objects)
        locked = all(item.selection_locked for item in objects)
        visibility = menu.addAction("Hide in Viewport" if visible else "Show in Viewport")
        visibility.triggered.connect(lambda: self.state.set_objects_visibility(keys, not visible))
        lock = menu.addAction("Unlock Viewport Selection" if locked else "Lock Viewport Selection")
        lock.triggered.connect(lambda: self.state.set_objects_locked(keys, not locked))
        menu.addSeparator()
        duplicate = menu.addAction("Duplicate")
        duplicate.triggered.connect(self.state.duplicate_selected)
        delete = menu.addAction("Delete")
        delete.triggered.connect(self.state.delete_selected)
        menu.addSeparator()
        group_action = menu.addAction("New Group from Selection")
        group_action.triggered.connect(self.create_group)
        move = menu.addMenu("Move to Group")
        root = move.addAction("Scene Root")
        root.triggered.connect(lambda: self.state.move_objects(keys))
        for group in self.state.scene.groups:
            action = move.addAction(group.name)
            action.triggered.connect(lambda checked=False, key=group.identifier: self.state.move_objects(keys, key))
        menu.addAction("Show Selected", self.show_selected)
        menu.addAction("Isolate Selected", self.state.isolate_selected)
        return menu

    def _sync_view(self):
        for row in self.rows.values():
            row.update_object()
        self._apply_filter()

    def create_group(self):
        group = self.state.create_group(identifiers=self.state.selected_ids)
        self.clear_filters(include_search=True)
        self.scene_toggle.setChecked(True)
        row = self.group_rows[group.identifier]
        self.scroll.ensureWidgetVisible(row)
        row.begin_rename()

    def toggle_group(self, identifier):
        group = self.state.find_group(identifier)
        if group is not None:
            group.expanded = not group.expanded
            self._apply_filter()

    def select_group(self, identifier, *, visible_only=False):
        group = self.state.find_group(identifier)
        if group is None:
            return
        self._cursor_key = identifier
        self._group_selecting = True
        try:
            keys = set(self.visible_object_ids()) if visible_only else set(group.members)
            self.state.select_many(key for key in group.members if key in keys)
        finally:
            self._group_selecting = False

    def show_selected(self):
        self.clear_filters(include_search=True)
        self.scene_toggle.setChecked(True)
        for key in self.state.selected_ids:
            group = self.state.group_for_object(key)
            if group is not None:
                group.expanded = True
        self._apply_filter()
        obj = self.state.selected_object
        if obj is not None and obj.identifier in self.rows:
            self.scroll.ensureWidgetVisible(self.rows[obj.identifier])
            self.rows[obj.identifier].name_button.setFocus()
            self._cursor_key = obj.identifier

    def set_isolation(self, enabled):
        if enabled:
            self.state.isolate_selected()
        else:
            self.state.exit_isolation()

    def open_background_menu(self, widget, point):
        menu = QMenu(self)
        menu.addAction("New Group", self.create_group)
        reveal = menu.addAction("Show Selected", self.show_selected)
        reveal.setEnabled(bool(self.state.selected_ids))
        isolate = menu.addAction("Isolate Selected", self.state.isolate_selected)
        isolate.setEnabled(bool(self.state.selected_ids))
        if self.state.isolated_ids is not None:
            menu.addAction("Exit Isolation", self.state.exit_isolation)
        menu.exec(widget.mapToGlobal(point))
        menu.deleteLater()

    def group_context_menu(self, identifier):
        group = self.state.find_group(identifier)
        menu = QMenu(self)
        if group is None:
            return menu
        menu.addAction("Rename Group\tF2", self.group_rows[identifier].begin_rename)
        menu.addAction("Select Group Objects", lambda: self.select_group(identifier))
        frame = menu.addAction("Frame Group")
        frame.setEnabled(any(self.state.find_object(key).viewport_visible for key in group.members))
        frame.triggered.connect(lambda: (self.select_group(identifier), self.state.frame_selected()))
        menu.addSeparator()
        menu.addAction("Hide Group" if group.editor_visible else "Show Group",
                       lambda: self.state.set_group_visibility(identifier, not group.editor_visible))
        menu.addAction("Unlock Group" if group.selection_locked else "Lock Group",
                       lambda: self.state.set_group_locked(identifier, not group.selection_locked))
        menu.addSeparator()
        menu.addAction("Remove Group (Keep Objects)", lambda: self.state.remove_group(identifier))
        return menu

    def visible_entries(self):
        entries = []
        visible = set(self.visible_object_ids())
        for key in self.state.scene.root_order:
            group = self.state.find_group(key)
            if group is not None:
                row = self.group_rows.get(key)
                if row is not None and not row.isHidden():
                    entries.append(key)
                entries.extend(child for child in group.members if child in visible)
            elif key in visible:
                entries.append(key)
        return entries

    def navigate(self, event, current):
        key = event.key()
        arrows = (Qt.Key.Key_Up, Qt.Key.Key_Down, Qt.Key.Key_Home, Qt.Key.Key_End,
                  Qt.Key.Key_Left, Qt.Key.Key_Right)
        if key not in arrows:
            return False
        self.scene_toggle.setChecked(True)
        entries = self.visible_entries()
        if not entries:
            event.accept()
            return True
        current = current if current in entries else None
        group = self.state.find_group(current)
        target = current
        if key == Qt.Key.Key_Left:
            if group is not None:
                group.expanded = False
                self._apply_filter()
            else:
                parent = self.state.group_for_object(current)
                target = parent.identifier if parent is not None else current
        elif key == Qt.Key.Key_Right:
            if group is not None:
                if not group.expanded:
                    group.expanded = True
                    self._apply_filter()
                elif group.members:
                    target = next((child for child in group.members if child in self.visible_object_ids()), current)
        else:
            index = entries.index(current) if current is not None else (-1 if key != Qt.Key.Key_Up else len(entries))
            index = 0 if key == Qt.Key.Key_Home else len(entries) - 1 if key == Qt.Key.Key_End else max(0, min(len(entries) - 1, index + (-1 if key == Qt.Key.Key_Up else 1)))
            target = entries[index]
        if target is not None:
            row = self.group_rows.get(target) or self.rows.get(target)
            if row is not None:
                row.name_button.setFocus()
                self._cursor_key = target
                if key in (Qt.Key.Key_Up, Qt.Key.Key_Down, Qt.Key.Key_Home, Qt.Key.Key_End) or target != current:
                    modifiers = event.modifiers()
                    focus_only = bool(modifiers & (Qt.KeyboardModifier.ControlModifier | Qt.KeyboardModifier.MetaModifier)) and not modifiers & Qt.KeyboardModifier.ShiftModifier
                    if not focus_only:
                        if self.state.find_group(target) is not None:
                            if not modifiers & Qt.KeyboardModifier.ShiftModifier:
                                self.select_group(target, visible_only=True)
                        else:
                            self.select_row(target, modifiers)
                self.scroll.ensureWidgetVisible(row)
        event.accept()
        return True

    DRAG_MIME = "application/x-simuo-hierarchy"

    def drag_mime(self, kind, identifiers):
        mime = QMimeData()
        mime.setData(self.DRAG_MIME, json.dumps({"scene": self.state.drag_token, "kind": kind,
                                               "ids": list(identifiers)}).encode("utf-8"))
        return mime

    def decode_drag(self, mime):
        if self.has_active_filters() or not mime.hasFormat(self.DRAG_MIME):
            return None
        try:
            data = json.loads(bytes(mime.data(self.DRAG_MIME)))
            if not isinstance(data, dict) or data.get("scene") != self.state.drag_token:
                return None
            keys, kind = data.get("ids"), data.get("kind")
            if not isinstance(keys, list) or not keys or not all(isinstance(key, str) for key in keys):
                return None
            valid = (kind == "object" and all(self.state.find_object(key) is not None for key in keys)
                     or kind == "group" and len(keys) == 1 and self.state.find_group(keys[0]) is not None)
            return (kind, keys) if valid else None
        except (ValueError, TypeError, UnicodeDecodeError):
            return None

    def start_drag(self, row):
        if self.has_active_filters():
            self.status.setText("Clear search and filters to drag and reorder objects.")
            return
        row.name_button.setFocus()
        key = row.obj.identifier
        if isinstance(row, GroupRow):
            kind, keys = "group", (key,)
        else:
            if key not in self.state.selected_ids:
                self.select_row(key)
            kind, keys = "object", self.state.selected_ids
        drag = QDrag(row)
        drag.setMimeData(self.drag_mime(kind, keys))
        drag.setPixmap(row.grab())
        try:
            drag.exec(Qt.DropAction.MoveAction)
        finally:
            self.clear_drop_indicator()
            drag.deleteLater()

    def drop_location(self, surface, y):
        if not isinstance(surface, ObjectRow):
            return None, None, "inside"
        key = surface.obj.identifier
        group = self.state.find_group(key)
        if group is not None and 5 <= y < surface.height() - 5:
            return key, None, "inside"
        parent = self.state.group_for_object(key) if group is None else None
        group_id = parent.identifier if parent is not None else None
        position = "before" if y < surface.height() / 2 else "after"
        before = key
        if position == "after":
            siblings = parent.members if parent is not None else self.state.scene.root_order
            index = siblings.index(key)
            before = siblings[index + 1] if index + 1 < len(siblings) else None
        return group_id, before, position

    def drop_surface_at(self, surface, point):
        if isinstance(surface, ObjectRow):
            return surface, point
        child = surface.childAt(point.toPoint())
        while child is not None and child is not surface:
            if isinstance(child, ObjectRow):
                return child, child.mapFrom(surface, point)
            child = child.parentWidget()
        return surface, point

    def clear_drop_indicator(self):
        if self._drop_widget is not None:
            self._drop_widget.setProperty("dropPosition", "")
            self._drop_widget.style().unpolish(self._drop_widget)
            self._drop_widget.style().polish(self._drop_widget)
            self._drop_widget.update()
            self._drop_widget = None

    def drag_over(self, surface, event):
        decoded = self.decode_drag(event.mimeData())
        self.clear_drop_indicator()
        if decoded is None:
            event.ignore()
            return
        surface, point = self.drop_surface_at(surface, event.position())
        group_id, before, position = self.drop_location(surface, point.y())
        kind, keys = decoded
        if (kind == "group" and group_id is not None) or before in keys or group_id in keys:
            event.ignore()
            return
        self._drop_widget = surface
        surface.setProperty("dropPosition", position)
        surface.style().unpolish(surface)
        surface.style().polish(surface)
        surface.update()
        point = self.scroll.viewport().mapFromGlobal(surface.mapToGlobal(point.toPoint()))
        bar = self.scroll.verticalScrollBar()
        if point.y() < 24:
            bar.setValue(bar.value() - 12)
        elif point.y() > self.scroll.viewport().height() - 24:
            bar.setValue(bar.value() + 12)
        event.setDropAction(Qt.DropAction.MoveAction)
        event.accept()

    def drop_on(self, surface, event):
        decoded = self.decode_drag(event.mimeData())
        self.clear_drop_indicator()
        if decoded is None:
            event.ignore()
            return
        surface, point = self.drop_surface_at(surface, event.position())
        group_id, before, position = self.drop_location(surface, point.y())
        kind, keys = decoded
        moved = (self.state.move_group(keys[0], before) if kind == "group" and group_id is None
                 else self.state.move_objects(keys, group_id, before) if kind == "object" else False)
        if moved:
            group = self.state.find_group(group_id)
            if group is not None:
                group.expanded = True
            self._apply_filter()
            event.setDropAction(Qt.DropAction.MoveAction)
            event.accept()
        else:
            event.ignore()
