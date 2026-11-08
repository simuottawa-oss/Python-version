"""Orbitable 3D part view with depth-correct triangle picking and flat faces."""
import math

import numpy as np
from PySide6.QtCore import Qt, QPointF, Signal
from PySide6.QtGui import QColor, QPainter, QPainterPath, QPen
from PySide6.QtWidgets import QWidget

from simuo.parts.feature_geometry import PLANES, support_frame, to_world
from simuo.parts.sketch_geometry import Sketch


def unit(v):
    """Normalize a direction vector, using positive Z when its length is zero.

    Args:
        v (array-like): Direction vector to normalize.

    Returns:
        numpy.ndarray: Unit vector, or [0, 0, 1] for zero length.
    """
    length = np.linalg.norm(v)
    return np.asarray(v)/length if length else np.array([0.,0,1])


def sketch_world_points(feature):
    """Tessellate already validated sketch geometry and place it in its supporting plane.

    Args:
        feature (dict): Validated feature containing sketch geometry and its supporting
            frame.

    Returns:
        numpy.ndarray: Shape (N, 3) world points in metres.
    """
    data = feature["sketch"]
    sketch = Sketch(data["points"],data["closed"],data["dimensions"],data["thickness"],data.get("arcs",[]))
    return to_world(sketch.outline_points,support_frame(feature["support"]))


class PartViewport(QWidget):
    face_selected = Signal(int)
    plane_selected = Signal(str)

    def __init__(self,parent=None):
        """Initialize an orbitable Qt-painted part preview with default Front support and
        empty model/selection.

        Args:
            parent (widget, optional): Owning Qt or Tk widget; None creates an
                independent Qt widget.

        Returns:
            None.
        """
        super().__init__(parent)
        self.model = None
        self.support = {"type":"plane","name":"Front"}
        self.selected_face = -1
        self.active_id = None
        self.yaw,self.pitch = .6,.4
        self.target = np.zeros(3)
        self.distance = .5
        self.pan = np.zeros(2)
        self.drag = None
        self.drag_start = None
        self.setMinimumSize(200,240)
        self.setFocusPolicy(Qt.StrongFocus)

    def fit(self):
        """Fit built solid and draft sketch points, reset panning, and repaint.

        Returns:
            None. Updates target and camera distance without changing geometry.
        """
        points = []
        if self.model is not None:
            if self.model.has_solid:
                points.extend(self.model.vertices.reshape(-1,6)[:,:3])
            for feature in self.model.features:
                points.extend(sketch_world_points(feature))
        if len(points):
            points = np.asarray(points)
            low,high = points.min(axis=0),points.max(axis=0)
            self.target = (low+high)/2
            self.distance = max(.02,float(np.linalg.norm(high-low))*2.2)
        else:
            self.target,self.distance = np.zeros(3),.5
        self.pan[:] = 0
        self.update()

    def basis(self):
        """Calculate the orbit camera position and orthonormal viewing axes.

        Returns:
            tuple: NumPy vectors (eye, forward, right, up).
        """
        offset = np.array([math.cos(self.pitch)*math.sin(self.yaw),math.sin(self.pitch),math.cos(self.pitch)*math.cos(self.yaw)])
        eye = self.target+offset*self.distance
        forward = unit(self.target-eye)
        right = unit(np.cross(forward,[0,1,0]))
        up = np.cross(right,forward)
        return eye,forward,right,up

    def project(self,point):
        """Perspective-project a 3D point into widget coordinates, rejecting points too
        close to or behind the camera.

        Args:
            point (array-like): World XYZ point in metres.

        Returns:
            tuple or None: (QPointF pixels, camera depth in metres), or None when
            clipped.
        """
        eye,forward,right,up = self.basis()
        delta = np.asarray(point)-eye
        depth = float(np.dot(delta,forward))
        if depth<=self.distance*1e-5:
            return None
        focal = min(self.width(),self.height())*1.25
        return QPointF(self.width()/2+self.pan[0]+np.dot(delta,right)*focal/depth,
                       self.height()/2+self.pan[1]-np.dot(delta,up)*focal/depth),depth

    def ray(self,position):
        """Construct a world-space picking ray through a widget position.

        Args:
            position (QPointF): Widget-local pointer location in logical pixels.

        Returns:
            tuple: Camera origin and normalized 3D ray direction.
        """
        eye,forward,right,up = self.basis()
        focal = min(self.width(),self.height())*1.25
        x = (position.x()-self.width()/2-self.pan[0])/focal
        y = -(position.y()-self.height()/2-self.pan[1])/focal
        return eye,unit(forward+x*right+y*up)

    def pick(self,position):
        """Find the nearest solid face intersected by the pointer's ray using triangle
        tests.

        Args:
            position (QPointF): Widget-local pointer location in logical pixels.

        Returns:
            int: Face index, or -1 if no face is hit.
        """
        if self.model is None:
            return -1
        origin,direction = self.ray(position)
        best,nearest = -1,float("inf")
        for index,face in enumerate(self.model.faces):
            for a,b,c in face["triangles"]:
                ab,ac = b-a,c-a
                h = np.cross(direction,ac)
                det = np.dot(ab,h)
                if abs(det)<1e-12:
                    continue
                delta = origin-a
                u = np.dot(delta,h)/det
                if not 0<=u<=1:
                    continue
                q = np.cross(delta,ab)
                v = np.dot(direction,q)/det
                distance = np.dot(ac,q)/det
                if v>=0 and u+v<=1 and 0<distance<nearest:
                    best,nearest = index,distance
        return best

    @property
    def plane_extent(self):
        """Scale visible reference-plane patches to the current camera distance.

        Returns:
            float: Plane patch half-extent in metres.
        """
        return max(1e-6,self.distance*.22)

    def visible_planes(self):
        """Select reference-plane frames to display according to solid and support state.

        Returns:
            list: (plane name, frame) pairs; empty when a solid has only a face support
            selected.
        """
        if self.model is None or not self.model.has_solid:
            return list(PLANES.items())
        if self.support is not None and self.support.get("type")=="plane":
            return [(self.support["name"],support_frame(self.support))]
        return []

    def pick_plane(self,position):
        """Ray-test visible finite plane patches and choose the nearest hit.

        Args:
            position (QPointF): Widget-local pointer location in logical pixels.

        Returns:
            str or None: Reference-plane name, or None if no patch is hit.
        """
        origin,direction = self.ray(position)
        best,nearest = None,float("inf")
        extent = self.plane_extent
        for name,frame in self.visible_planes():
            normal = np.cross(frame["u"],frame["v"])
            denominator = float(np.dot(direction,normal))
            if abs(denominator)<1e-10:
                continue
            distance = float(np.dot(np.asarray(frame["origin"])-origin,normal))/denominator
            if not 0<distance<nearest:
                continue
            delta = origin+direction*distance-np.asarray(frame["origin"])
            if max(abs(float(np.dot(delta,frame[axis]))) for axis in ("u","v"))<=extent:
                best,nearest = name,distance
        return best

    def mousePressEvent(self,event):
        """Capture focus and record the initial pointer position for orbit, pan, or click
        selection.

        Args:
            event (Qt event): Input, paint, resize, focus, or close event delivered by
                the framework.

        Returns:
            None. Initializes drag state.
        """
        self.setFocus()
        self.drag,self.drag_start = event.position(),event.position()

    def mouseMoveEvent(self,event):
        """Pan on middle-drag or orbit on left/right-drag, clamping camera pitch.

        Args:
            event (Qt event): Input, paint, resize, focus, or close event delivered by
                the framework.

        Returns:
            None. Updates camera state and repaints.
        """
        if self.drag is None:
            return
        delta = event.position()-self.drag
        self.drag = event.position()
        if event.buttons() & Qt.MiddleButton:
            self.pan += [delta.x(),delta.y()]
        elif event.buttons() & (Qt.LeftButton|Qt.RightButton):
            self.yaw -= delta.x()*.008
            self.pitch = max(-1.45,min(1.45,self.pitch+delta.y()*.008))
        self.update()

    def mouseReleaseEvent(self,event):
        """Treat a short left click as face/plane selection, emit the selection signal, and
        finish dragging.

        Args:
            event (Qt event): Input, paint, resize, focus, or close event delivered by
                the framework.

        Returns:
            None. Updates highlight/support and clears drag state.
        """
        if event.button()==Qt.LeftButton and self.drag_start is not None and (event.position()-self.drag_start).manhattanLength()<5:
            index = self.pick(event.position())
            self.selected_face = index
            if index>=0:
                self.face_selected.emit(index)
            else:
                plane = self.pick_plane(event.position())
                if plane is not None:
                    self.support = {"type":"plane","name":plane}
                    self.plane_selected.emit(plane)
        self.drag,self.drag_start = None,None
        self.update()

    def wheelEvent(self,event):
        """Adjust orbit distance within limits according to wheel direction.

        Args:
            event (Qt event): Input, paint, resize, focus, or close event delivered by
                the framework.

        Returns:
            None. Schedules a repaint.
        """
        self.distance = max(1e-5,min(1e6,self.distance*(.85 if event.angleDelta().y()>0 else 1/.85)))
        self.update()

    def keyPressEvent(self,event):
        """Orbit with horizontal arrow keys or fit the view with F; delegate other keys.

        Args:
            event (Qt event): Input, paint, resize, focus, or close event delivered by
                the framework.

        Returns:
            None. Updates view state for handled shortcuts.
        """
        if event.key() in (Qt.Key_Left,Qt.Key_Right):
            self.yaw += .08 if event.key()==Qt.Key_Right else -.08
            self.update()
        elif event.key()==Qt.Key_F:
            self.fit()
        else:
            super().keyPressEvent(event)

    def _path(self,points):
        """Project a polygon into a closed painter path with average depth for draw
        ordering.

        Args:
            points (iterable): Polygon vertices in world XYZ metres.

        Returns:
            tuple or None: (QPainterPath, mean depth), or None for empty/clipped points.
        """
        projected = [self.project(p) for p in points]
        if not projected or any(p is None for p in projected):
            return None
        path = QPainterPath(projected[0][0])
        for point,_ in projected[1:]:
            path.lineTo(point)
        path.closeSubpath()
        return path,sum(depth for _,depth in projected)/len(projected)

    def paintEvent(self,event):
        """Paint reference planes, depth-sorted shaded triangles, visible face boundaries,
        sketches, and the orientation triad.

        Args:
            event (Qt event): Input, paint, resize, focus, or close event delivered by
                the framework.

        Returns:
            None. Draws into the widget using QPainter, without an OpenGL context.
        """
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        painter.fillRect(self.rect(),QColor("#2e2e33"))
        extent = self.plane_extent
        frames = self.visible_planes()
        if not frames and self.support is not None:
            frames = [(self.support.get("name",self.support.get("label","Selected face")),support_frame(self.support))]
        for name,frame in frames:
            corners = to_world([[-extent,-extent],[extent,-extent],[extent,extent],[-extent,extent]],frame)
            path = self._path(corners)
            if path:
                selected = self.support is not None and self.support.get("name",self.support.get("label"))==name
                painter.fillPath(path[0],QColor(247,180,80,45) if selected else QColor(94,145,183,22))
                painter.setPen(QPen(QColor("#ffc078" if selected else "#7c9ab2"),2 if selected else 1,Qt.DashLine))
                painter.drawPath(path[0])
                p = self.project(corners[2])
                if p:
                    painter.drawText(p[0],name+" Plane" if name in PLANES else name)
        drawing = []
        light = unit([-.4,.8,1])
        if self.model is not None:
            for index,face in enumerate(self.model.faces):
                brightness = .3+.7*max(0,float(np.dot(face["normal"],light)))
                base = [247,180,80] if index==self.selected_face else [71,185,213]
                color = QColor(*(round(v*brightness) for v in base))
                for triangle in face["triangles"]:
                    path = self._path(triangle)
                    if path:
                        drawing.append((path[1],path[0],color))
            painter.setPen(Qt.NoPen)
            for _,path,color in sorted(drawing,key=lambda item:-item[0]):
                painter.fillPath(path,color)
            # Only exposed front-facing planar boundaries, not triangulation edges.
            eye,_,_,_ = self.basis()
            for index,face in enumerate(self.model.faces):
                if np.dot(face["normal"],eye-np.asarray(face["frame"]["origin"]))<=0:
                    continue
                painter.setPen(QPen(QColor("#ffd08c" if index==self.selected_face else "#9ed6df"),2 if index==self.selected_face else 1))
                for a,b in face["edges"]:
                    pa,pb = self.project(a),self.project(b)
                    if pa and pb:
                        painter.drawLine(pa[0],pb[0])
            for feature in self.model.features:
                if feature["depth"] is not None and feature["id"]!=self.active_id:
                    continue
                points = sketch_world_points(feature)
                painter.setPen(QPen(QColor("#ffc078"),2))
                for i in range(len(points) if feature["sketch"]["closed"] else max(0,len(points)-1)):
                    a,b = self.project(points[i]),self.project(points[(i+1)%len(points)])
                    if a and b:
                        painter.drawLine(a[0],b[0])
        # View triad stays readable regardless of world scale.
        _,_,right,up = self.basis()
        origin = QPointF(42,self.height()-48)
        for axis,color,label in (([1,0,0],"#ec8c89","X"),([0,1,0],"#93d7a0","Y"),([0,0,1],"#8db5f2","Z")):
            end = origin+QPointF(float(np.dot(axis,right))*28,-float(np.dot(axis,up))*28)
            painter.setPen(QPen(QColor(color),2))
            painter.drawLine(origin,end)
            painter.drawText(end+QPointF(3,-3),label)
        painter.setPen(QColor("#c4d3df"))
        painter.drawText(14,24,"3D Model · click a plane or face to select · drag to orbit · scroll to zoom")
