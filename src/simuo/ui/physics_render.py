"""Nonmodal physics playback window with a read-only scene viewport."""
import copy
import time

import numpy as np
from PySide6.QtCore import Qt, QTimer, QSize
from PySide6.QtGui import QAction, QColor, QIcon, QPainter
from PySide6.QtWidgets import (QMainWindow, QWidget, QVBoxLayout, QFormLayout,
                               QLabel, QDoubleSpinBox, QCheckBox, QDockWidget,
                               QToolBar, QStyle, QScrollArea, QFrame)

from simuo.parts.part_format import Part
from simuo.parts.part_assets import PartAsset, box_vertices
from simuo.physics.physics_world import PhysicsWorld, quaternion
from simuo.physics.viewport.renderer import OpenGLViewport
from simuo.project.scene import Scene, SceneObject
from simuo.ui.theme import load_stylesheet


class PhysicsRenderWindow(QMainWindow):
    def __init__(self, source_scene, parent=None):
        """Create a nonmodal playback window, independent physics snapshot, render
        viewport, controls, and running timer.

        Args:
            source_scene (Scene): Editor scene to snapshot; its transforms and motion
                are not modified.
            parent (widget, optional): Owning Qt or Tk widget; None creates an
                independent Qt widget.

        Returns:
            None.
        """
        super().__init__(parent, Qt.Window)
        self.setAttribute(Qt.WA_DeleteOnClose)
        self.setWindowTitle("SimuO — Physics Render")
        self.resize(1100,800)
        self.world = PhysicsWorld(source_scene)
        self.running = True
        self.accumulator = 0
        self.last_time = time.perf_counter()
        self.render_scene = Scene()
        self.render_scene.objects = list(self.world.scene.objects)
        self.ground = self._ground()
        self.render_scene.addObject(self.ground)
        self.setStyleSheet(load_stylesheet("main_window") + load_stylesheet("physics_render"))
        self.setMinimumSize(640, 480)
        self.viewport = OpenGLViewport(self, scene=self.render_scene, read_only=True)
        self.viewport.setMinimumSize(280, 240)
        self.setCentralWidget(self.viewport)
        self._create_toolbar()
        self._create_sidebar()
        self.playback_status = QLabel()
        self.statusBar().addWidget(self.playback_status)
        self.frame_scene()
        self._update_status()
        self.timer = QTimer(self)
        self.timer.timeout.connect(self.tick)
        self.timer.start(16)

    def _create_toolbar(self):
        toolbar = QToolBar("Playback", self)
        toolbar.setObjectName("renderToolbar")
        toolbar.setMovable(False)
        toolbar.setFloatable(False)
        toolbar.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextBesideIcon)
        toolbar.setIconSize(QSize(18, 18))
        self.addToolBar(Qt.ToolBarArea.BottomToolBarArea, toolbar)
        self.playback_toolbar = toolbar

        def control(title, icon, shortcut, callback, tip):
            action = QAction(self._control_icon(icon), title, self)
            action.setShortcut(shortcut)
            action.setToolTip(tip)
            if callback is not None:
                action.triggered.connect(callback)
            toolbar.addAction(action)
            return action, toolbar.widgetForAction(action)

        icons = QStyle.StandardPixmap
        self.back_action, self.back_button = control(
            "Step Back", icons.SP_MediaSkipBackward, "", self.step_back,
            "Pause and go back one physics step (1/240 second)")
        self.play_action, self.play = control(
            "Pause", icons.SP_MediaPause, "P", self.toggle, "Pause or resume playback (P)")
        self.step_action, self.step_button = control(
            "Step Forward", icons.SP_MediaSkipForward, "", self.single_step,
            "Pause and advance one physics step (1/240 second)")
        self.reset_action, self.reset_button = control(
            "Reset", icons.SP_MediaStop, "R", self.reset, "Restore the initial simulation state (R)")
        toolbar.addSeparator()
        self.frame_action, self.frame_button = control(
            "Frame Scene", icons.SP_TitleBarMaxButton, "F", self.frame_scene,
            "Fit the simulated scene in the view (F)")
        toolbar.addSeparator()
        self.settings_action, self.settings_button = control(
            "Settings", icons.SP_FileDialogDetailedView, "", None,
            "Show or hide scene settings and statistics")
        self.settings_action.setCheckable(True)

    def _control_icon(self, icon):
        """Keep system action icons legible against the editor's dark toolbar."""
        pixmap = self.style().standardIcon(icon).pixmap(36, 36)
        painter = QPainter(pixmap)
        painter.setCompositionMode(QPainter.CompositionMode.CompositionMode_SourceIn)
        painter.fillRect(pixmap.rect(), QColor("#c1cbd7"))
        painter.end()
        pixmap.setDevicePixelRatio(2)
        return QIcon(pixmap)

    def _create_sidebar(self):
        self.details_dock = QDockWidget("Simulation", self)
        self.details_dock.setObjectName("renderDetails")
        self.details_dock.setFeatures(QDockWidget.DockWidgetFeature.NoDockWidgetFeatures)
        self.details_dock.setMinimumWidth(240)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        panel = QWidget()
        panel.setObjectName("renderPanel")
        panel.setMinimumWidth(220)
        layout = QVBoxLayout(panel)
        layout.setContentsMargins(12, 12, 12, 12)
        layout.setSpacing(12)

        def heading(title):
            label = QLabel(title)
            label.setObjectName("renderSectionTitle")
            layout.addWidget(label)

        heading("Simulation settings")
        form = QFormLayout()
        form.setRowWrapPolicy(QFormLayout.RowWrapPolicy.WrapAllRows)
        self.gravity = QDoubleSpinBox()
        self.gravity.setRange(-100, 100)
        self.gravity.setDecimals(2)
        self.gravity.setSuffix(" m/s²")
        self.gravity.setValue(self.world.gravity)
        self.gravity.setToolTip("Vertical acceleration; changing it starts new rewind history")
        self.gravity.valueChanged.connect(self.change_gravity)
        form.addRow("Gravity Y", self.gravity)
        layout.addLayout(form)
        self.floor = QCheckBox("Floor at y = 0")
        self.floor.setChecked(True)
        self.floor.setToolTip("Toggle floor contact and reset playback")
        self.floor.toggled.connect(self.change_floor)
        layout.addWidget(self.floor)
        self.info = QLabel("Playback uses a copy of your scene. Use the scene editor to edit objects.")
        self.info.setObjectName("renderHint")
        self.info.setWordWrap(True)
        layout.addWidget(self.info)
        heading("Statistics")
        self.stats = QLabel()
        self.stats.setWordWrap(True)
        self.stats.setTextFormat(Qt.TextFormat.PlainText)
        self.stats.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        layout.addWidget(self.stats)
        layout.addStretch()
        scroll.setWidget(panel)
        self.details_dock.setWidget(scroll)
        self.addDockWidget(Qt.DockWidgetArea.RightDockWidgetArea, self.details_dock)
        self.settings_action.setChecked(True)
        self.settings_action.toggled.connect(self.details_dock.setVisible)
        self.details_dock.visibilityChanged.connect(self.settings_action.setChecked)
        self.resizeDocks([self.details_dock], [260], Qt.Orientation.Horizontal)

    def _ground(self):
        """Build a static visual floor patch sized around the initial simulation scene; the
        actual solver floor is a plane.

        Returns:
            SceneObject: Floor box with CPU mesh and top surface at y=0.
        """
        positions = [obj.position for obj in self.world.scene.objects]
        center = np.mean(positions,axis=0) if positions else [0,0,0]
        span = max([20.] + [abs(v) + max(obj.scale)*max(obj.part.size if obj.part else (1,1,1))
                            for obj in self.world.scene.objects for v in (obj.position[0]-center[0],obj.position[2]-center[2])])
        part = Part("simuo.floor","Floor",(span*4,0.04,span*4),"#424d58",1,1,1,
                    "static",1,(center[0],-0.02,center[2]),(0,0,0),{})
        obj = SceneObject("Floor")
        obj.asset = PartAsset(box_vertices(part),part)
        obj.part = part
        obj.position = list(part.position)
        return obj

    def frame_scene(self):
        """Frame rotated/scaled simulation objects and optional floor level, excluding the
        oversized floor patch from bounds.

        Returns:
            None. Updates the viewport camera.
        """
        points = []
        for obj in self.world.scene.objects:
            local = obj.asset.vertices.reshape(-1,6)[:,:3]*np.asarray(obj.scale)
            rotation = np.asarray(self.world.bullet.getMatrixFromQuaternion(quaternion(obj.rotation))).reshape(3,3)
            points.extend(local @ rotation.T + np.asarray(obj.position))
        if not points:
            return
        points = np.asarray(points)
        low, high = points.min(axis=0),points.max(axis=0)
        if self.world.floor:
            low[1] = min(0,low[1])
        # Bound the content, not the large visual floor patch.
        frame = copy.copy(self.world.scene.objects[0])
        frame.position,frame.rotation,frame.scale = [0,0,0],[0,0,0],[1,1,1]
        frame.asset = PartAsset(np.array([[*low,0,1,0],[*high,0,1,0]],dtype=np.float32).ravel())
        self.viewport.frameObject(frame)

    def set_running(self, running):
        """Set playback state, clear accumulated time, and update the play button.

        Args:
            running (bool): True to run playback; False to pause.

        Returns:
            None. Resets the wall-clock reference to avoid catching up paused time.
        """
        self.running = running
        self.accumulator = 0
        self.last_time = time.perf_counter()
        self.play_action.setText("Pause" if running else "Play")
        icon = QStyle.StandardPixmap.SP_MediaPause if running else QStyle.StandardPixmap.SP_MediaPlay
        self.play_action.setIcon(self._control_icon(icon))

    def toggle(self):
        """Switch between running and paused playback and update the status display.

        Returns:
            None.
        """
        self.set_running(not self.running)
        self._update_status()

    def reset(self):
        """Pause playback, rebuild the world's initial state, and refresh the viewport and
        status.

        Returns:
            None.
        """
        self.set_running(False)
        self.world.reset()
        self.viewport.update()
        self._update_status()

    def single_step(self):
        """Pause playback and simulate exactly one fixed timestep.

        Returns:
            None. Repaints the updated state and status.
        """
        self.set_running(False)
        self.world.step()
        self.viewport.update()
        self._update_status()

    def step_back(self):
        """Pause and restore the previous simulation step without moving the camera."""
        self.set_running(False)
        try:
            self.world.step_back()
        except Exception as error:
            self.statusBar().showMessage(f"Cannot step back: {error}")
        self.viewport.update()
        self._update_status()

    def change_gravity(self, value):
        self.world.set_gravity(value)
        self._update_status()

    def change_floor(self, enabled):
        """Enable or disable floor contact, reset playback, and rebuild the visible object
        uploads when the viewport is ready.

        Args:
            enabled (bool): Whether the optional floor is enabled.

        Returns:
            None. Updates both solver floor behavior and the visual floor patch.
        """
        self.world.floor = enabled
        self.reset()
        if enabled and self.ground not in self.render_scene.objects:
            self.render_scene.addObject(self.ground)
        elif not enabled and self.ground in self.render_scene.objects:
            self.render_scene.objects.remove(self.ground)
        if self.viewport.isValid():
            self.viewport.clearRenderObjects()
            for obj in self.render_scene.objects:
                self.viewport.addNewObject(obj)

    def tick(self):
        """Accumulate capped wall time, run whole fixed physics steps, and refresh the
        display. Solver errors pause playback and display the error.

        Returns:
            None. Updates the accumulator, simulated state, and UI.
        """
        now = time.perf_counter()
        elapsed = min(now-self.last_time,0.1)
        self.last_time = now
        if self.running:
            self.accumulator += elapsed
            steps = int(self.accumulator/self.world.dt)
            if steps:
                try:
                    self.world.step(steps)
                except Exception as error:
                    self.set_running(False)
                    self.info.setText(f"Simulation stopped: {error}")
                    return
                self.accumulator -= steps*self.world.dt
        self.viewport.update()
        self._update_status()

    def _update_status(self):
        """Display playback time, body counts, legacy-mesh guidance, and up to five dynamic
        object speeds.

        Returns:
            None. Replaces the status label text.
        """
        objects = self.world.scene.objects
        self.back_action.setEnabled(self.world.can_step_back)
        counts = " / ".join(f"{sum(obj.body_type == mode for obj in objects)} {mode}"
                            for mode in ("dynamic", "kinematic", "static"))
        self.playback_status.setText(
            f"{'Running' if self.running else 'Paused'} · {self.world.time:.3f} s")
        label = counts.replace(" / ", "\n")
        if self.world.legacy_count:
            label += f"\n\n{self.world.legacy_count} legacy meshes (moving bodies use convex hulls)"
        speeds = [f"{obj.name}\nHeight: {obj.position[1]:.3f} m · Speed: {np.linalg.norm(obj.velocity):.3f} m/s"
                  for obj in objects if obj.body_type != "static"]
        self.stats.setText(label + ("\n\n" + "\n\n".join(speeds[:5]) if speeds else ""))

    def closeEvent(self, event):
        """Stop both timers, release uploaded scene buffers, disconnect Bullet, and accept
        window closure.

        Args:
            event (Qt event): Input, paint, resize, focus, or close event delivered by
                the framework.

        Returns:
            None. Consumes the close event.
        """
        self.timer.stop()
        self.viewport.timer.stop()
        if self.viewport.isValid():
            self.viewport.clearRenderObjects()
        self.world.close()
        event.accept()
