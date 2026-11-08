"""Nonmodal physics playback window using the main OpenGL renderer."""
import copy
import time

import numpy as np
from PySide6.QtCore import Qt, QTimer
from PySide6.QtGui import QAction
from PySide6.QtWidgets import (QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
                               QPushButton, QLabel, QDoubleSpinBox, QCheckBox)

from simuo.parts.part_format import Part
from simuo.parts.part_assets import PartAsset, box_vertices
from simuo.physics.physics_world import PhysicsWorld, quaternion
from simuo.physics.viewport.renderer import OpenGLViewport
from simuo.project.scene import Scene, SceneObject


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
        panel = QWidget(self)
        layout = QVBoxLayout(panel)
        controls = QHBoxLayout()
        self.play = QPushButton("Pause")
        self.play.clicked.connect(self.toggle)
        self.reset_button = QPushButton("Reset")
        self.reset_button.clicked.connect(self.reset)
        self.step_button = QPushButton("Step")
        self.step_button.clicked.connect(self.single_step)
        self.frame_button = QPushButton("Frame scene")
        self.frame_button.clicked.connect(self.frame_scene)
        for button in (self.play,self.reset_button,self.step_button,self.frame_button):
            controls.addWidget(button)
        controls.addWidget(QLabel("Gravity Y"))
        self.gravity = QDoubleSpinBox()
        self.gravity.setRange(-100,100)
        self.gravity.setDecimals(2)
        self.gravity.setSuffix(" m/s²")
        self.gravity.setValue(self.world.gravity)
        self.gravity.valueChanged.connect(self.world.set_gravity)
        controls.addWidget(self.gravity)
        self.floor = QCheckBox("Floor at y=0")
        self.floor.setChecked(True)
        self.floor.toggled.connect(self.change_floor)
        controls.addWidget(self.floor)
        controls.addStretch()
        layout.addLayout(controls)
        self.info = QLabel("Live rigid-body physics · scene copy · drag with right mouse / WASD to move the camera")
        self.info.setWordWrap(True)
        layout.addWidget(self.info)
        self.viewport = OpenGLViewport(self,scene=self.render_scene)
        layout.addWidget(self.viewport,1)
        self.stats = QLabel()
        self.stats.setWordWrap(True)
        layout.addWidget(self.stats)
        self.setCentralWidget(panel)
        self.frame_scene()
        self._update_status()
        self.timer = QTimer(self)
        self.timer.timeout.connect(self.tick)
        self.timer.start(16)
        for key, callback in (("P",self.toggle),("R",self.reset),("F",self.frame_scene)):
            action = QAction(self)
            action.setShortcut(key)
            action.triggered.connect(callback)
            self.addAction(action)

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
        self.play.setText("Pause" if running else "Play")

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
        dynamic = sum(mass > 0 for mass in self.world.masses)
        label = f"{'RUNNING' if self.running else 'PAUSED'} · {self.world.time:.3f} s · {dynamic} dynamic / {len(self.world.bodies)-dynamic} static bodies"
        if self.world.legacy_count:
            label += f" · {self.world.legacy_count} legacy meshes (dynamic uses a convex hull, 1 kg)"
        speeds = [f"{obj.name}: y={obj.position[1]:.3f} m, speed={np.linalg.norm(obj.velocity):.3f} m/s"
                  for obj,mass in zip(self.world.scene.objects,self.world.masses) if mass]
        self.stats.setText(label + ("\n"+" | ".join(speeds[:5]) if speeds else ""))

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
