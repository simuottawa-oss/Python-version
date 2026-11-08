"""Simple dimensioned line sketch editor for .simuOPart assets."""
import copy
import math
from pathlib import Path

from PySide6.QtCore import Qt, QPointF, QRectF, Signal, QItemSelectionModel
from PySide6.QtGui import QAction, QColor, QPainter, QPainterPath, QPen
from PySide6.QtWidgets import (QApplication, QMainWindow, QWidget, QHBoxLayout, QVBoxLayout,
    QFormLayout, QLabel, QPushButton, QDoubleSpinBox, QLineEdit, QTableWidget,
    QTableWidgetItem, QFileDialog, QMessageBox, QInputDialog, QAbstractItemView, QHeaderView,
    QDockWidget, QScrollArea, QListWidget, QListWidgetItem)

from simuo.parts.part_document import new_document, open_document, save_document
from simuo.parts.sketch_geometry import Sketch
from simuo.parts.part_export import export_sketch


class ConstraintList(QListWidget):
    delete_requested = Signal()

    def keyPressEvent(self,event):
        """Emit delete_requested for unmodified Delete/Backspace; delegate other keys to
        the list widget.

        Args:
            event (Qt event): Input, paint, resize, focus, or close event delivered by
                the framework.

        Returns:
            None. Accepts handled key events.
        """
        if event.key() in (Qt.Key_Delete,Qt.Key_Backspace) and event.modifiers()==Qt.NoModifier:
            self.delete_requested.emit()
            event.accept()
        else:
            super().keyPressEvent(event)


class SketchCanvas(QWidget):
    changed = Signal()
    selected = Signal(int)
    dimension_requested = Signal(int)
    error = Signal(str)

    def __init__(self,editor):
        """Create a sketch canvas with drawing, selection, snapping, drag, and pan state
        linked to its editor.

        Args:
            editor (PartEditor): Owner providing the working sketch, commit operations,
                and selection state.

        Returns:
            None.
        """
        super().__init__()
        self.editor = editor
        self.zoom = 1500.0
        self.origin = QPointF(250,350)
        self.drawing = True
        self.arc_mode = False
        self.arc_through = None
        self.circle_mode = False
        self.circle_center = None
        self.selection = -1
        self.cursor = None
        self.pan = None
        self.labels = []
        self.snap_target = None
        self._snap_lock = None
        self._snap_sketch = None
        self.drag_index = None
        self.drag_original = None
        self.drag_candidate = None
        self.setMinimumSize(200,240)
        self.setMouseTracking(True)
        self.setFocusPolicy(Qt.StrongFocus)

    def screen(self,p):
        """Convert sketch XY metres to canvas pixels using zoom and an inverted screen Y
        axis.

        Args:
            p (sequence): Sketch [x, y] position in metres.

        Returns:
            QPointF: Widget-local pixel coordinates.
        """
        return QPointF(self.origin.x()+p[0]*self.zoom,self.origin.y()-p[1]*self.zoom)

    def world(self,p):
        """Convert a screen position to sketch coordinates with endpoint/edge snapping, 1
        mm grid rounding, and drawing-axis hints.

        Args:
            p (QPointF): Widget-local pointer position in logical pixels.

        Returns:
            list: XY metres; also updates snap target and hysteresis lock state.
        """
        sketch = self.editor.sketch
        context_edges = (self.editor.sketch_context_geometry()[1]
                         if hasattr(self.editor, "sketch_context_geometry") else [])
        targets = [([0.,0.],"Origin",18)] + [(point,"Endpoint",14) for point in sketch.points]
        targets.extend((point, "Face corner", 14) for edge in context_edges for point in edge)
        if self._snap_sketch is not sketch:
            self._snap_lock = None
            self._snap_sketch = sketch
        # Resolve exact geometry before rounding to the grid. Pixel radii keep
        # snapping usable at every zoom; a wider release radius prevents jitter.
        if self._snap_lock is not None:
            point,label = self._snap_lock
            screen = self.screen(point)
            distance = math.hypot(p.x()-screen.x(),p.y()-screen.y())
            # Keep the lock stable, but let a point directly under the cursor
            # win when several endpoints are close together on screen.
            stronger_target = any(
                math.hypot(p.x()-self.screen(other).x(),p.y()-self.screen(other).y())<min(5,distance-6)
                for other, _, _ in targets
            )
            if distance<=22 and not stronger_target:
                self.snap_target = (point,label)
                return list(point)
        self._snap_lock = None
        self.snap_target = None
        nearby = []
        for point,label,radius in targets:
            screen = self.screen(point)
            distance = math.hypot(p.x()-screen.x(),p.y()-screen.y())
            if distance<=radius:
                nearby.append((distance,point,label))
        if nearby:
            _,point,label = min(nearby,key=lambda target:target[0])
            self._snap_lock = self.snap_target = (tuple(point),label)
            return list(point)
        raw_x,raw_y = (p.x()-self.origin.x())/self.zoom,(self.origin.y()-p.y())/self.zoom
        # Project onto finite edges before applying grid/axis rounding. Unlike
        # corner locks, edge snaps slide along the edge as the cursor moves.
        lines = [(sketch.points[a], sketch.points[b], "Sketch line")
                 for i, (a, b) in enumerate(sketch.edges) if not sketch.is_arc(i)]
        lines.extend((a, b, "Face edge") for a, b in context_edges)
        nearby_edges = []
        for a, b, label in lines:
            dx, dy = b[0]-a[0], b[1]-a[1]
            length_squared = dx*dx+dy*dy
            if length_squared <= 1e-24:
                continue
            t = max(0., min(1., ((raw_x-a[0])*dx+(raw_y-a[1])*dy)/length_squared))
            point = [float(a[0]+t*dx), float(a[1]+t*dy)]
            distance = math.hypot(raw_x-point[0], raw_y-point[1])*self.zoom
            if distance <= 10:
                nearby_edges.append((distance, point, label))
        if nearby_edges:
            _, point, label = min(nearby_edges, key=lambda target: target[0])
            self.snap_target = (tuple(point), label)
            return point
        x,y = round(raw_x/.001)*.001,round(raw_y/.001)*.001
        if sketch.points and not sketch.closed and not self.arc_mode and not self.circle_mode:
            last = sketch.points[-1]
            axis_x = min((0.,last[0]),key=lambda value:abs(raw_x-value))
            axis_y = min((0.,last[1]),key=lambda value:abs(raw_y-value))
            if abs(raw_x-axis_x)*self.zoom<8:
                x = axis_x
            if abs(raw_y-axis_y)*self.zoom<8:
                y = axis_y
        return [x,y]

    def center_origin(self):
        """Center the sketch origin in the widget and clear snapping locks.

        Returns:
            None. Schedules a repaint without moving geometry.
        """
        self.origin = QPointF(self.width()/2,self.height()/2)
        self._snap_lock = self.snap_target = None
        self.update()

    def hit(self,p):
        """Hit-test dimension labels, straight segments, and analytic arcs within screen-
        space tolerances.

        Args:
            p (QPointF): Widget-local pointer position in logical pixels.

        Returns:
            int: Nearest segment index, or -1 if nothing is close enough.
        """
        for i,label in self.labels:
            if math.hypot(p.x()-label.x(),p.y()-label.y())<30:
                return i
        closest,distance = -1,12
        for i in range(len(self.editor.sketch.edges)):
            sketch = self.editor.sketch
            if sketch.is_arc(i):
                center,radius,sweep = sketch.arc_parameters(i)
                point = [(p.x()-self.origin.x())/self.zoom,(self.origin.y()-p.y())/self.zoom]
                a,b = (sketch.points[j] for j in sketch.edges[i])
                first = math.atan2(a[1]-center[1],a[0]-center[0])
                angle = math.atan2(point[1]-center[1],point[0]-center[0])
                delta = (angle-first) % math.tau if sweep>0 else (first-angle) % math.tau
                d = abs(math.dist(point,center)-radius)*self.zoom if delta<=abs(sweep)+1e-10 else min(math.dist(point,a),math.dist(point,b))*self.zoom
                if d<distance:
                    closest,distance = i,d
                continue
            points = [self.screen(point) for point in self.editor.sketch.segment_points(i)]
            for a,b in zip(points,points[1:]):
                dx,dy = b.x()-a.x(),b.y()-a.y()
                if dx*dx+dy*dy == 0:
                    continue
                t = max(0,min(1,((p.x()-a.x())*dx+(p.y()-a.y())*dy)/(dx*dx+dy*dy)))
                d = math.hypot(p.x()-a.x()-t*dx,p.y()-a.y()-t*dy)
                if d<distance:
                    closest,distance = i,d
        return closest

    def segment_path(self,index):
        """Construct a screen-space painter path for a straight segment or analytic
        circular arc.

        Args:
            index (int): Zero-based sketch edge index; -1 represents no selection in
                selection callbacks.

        Returns:
            QPainterPath: Segment path using current pan and zoom.
        """
        sketch = self.editor.sketch
        a,b = (sketch.points[i] for i in sketch.edges[index])
        path = QPainterPath(self.screen(a))
        if sketch.is_arc(index):
            center,radius,sweep = sketch.arc_parameters(index)
            pixel = self.screen(center)
            size = radius*self.zoom
            start = math.degrees(math.atan2(a[1]-center[1],a[0]-center[0]))
            path.arcTo(QRectF(pixel.x()-size,pixel.y()-size,2*size,2*size),start,math.degrees(sweep))
        else:
            path.lineTo(self.screen(b))
        return path

    def mousePressEvent(self,event):
        """Start panning/endpoint dragging, select segments, or add line/arc/circle
        geometry according to the active tool.

        Args:
            event (Qt event): Input, paint, resize, focus, or close event delivered by
                the framework.

        Returns:
            None. Commits valid candidates through the editor and emits selection/error
            signals as needed.
        """
        self.setFocus()
        if event.button()==Qt.MiddleButton:
            self.pan = event.position()
            return
        if event.button()!=Qt.LeftButton:
            return
        sketch = self.editor.sketch
        if self.drawing and self.circle_mode:
            try:
                if sketch.points:
                    raise ValueError("A circle needs an empty sketch. Create a new sketch or part first.")
                point = self.world(event.position())
                self.cursor = point
                if self.circle_center is None:
                    self.circle_center = point
                    self.editor.statusBar().showMessage("Circle: click the edge to set its radius. Esc cancels.")
                else:
                    candidate = Sketch.circle(self.circle_center, math.dist(self.circle_center, point), sketch.thickness)
                    self.editor.commit(candidate)
                self.update()
            except ValueError as error:
                self.error.emit(str(error))
            return
        if not self.drawing or sketch.closed:
            if not event.modifiers() & Qt.ControlModifier:
                nearby = [(math.hypot(event.position().x()-self.screen(p).x(), event.position().y()-self.screen(p).y()), i)
                          for i, p in enumerate(sketch.points)]
                if nearby and min(nearby)[0] <= 9:
                    self.drag_index = min(nearby)[1]
                    self.drag_original = copy.deepcopy(sketch)
                    self.drag_candidate = None
                    self.arc_through = None
                    self._snap_lock = self.snap_target = None
                    self.editor.statusBar().showMessage("Drag point · explicit constraints are preserved · Esc cancels")
                    self.update()
                    return
            self.selection = self.hit(event.position())
            if event.modifiers() & Qt.ControlModifier and self.selection>=0:
                self.editor.toggle_segment_selection(self.selection)
            else:
                self.selected.emit(self.selection)
            self.update()
            return
        try:
            candidate = copy.deepcopy(sketch)
            point = self.world(event.position())
            self.cursor = point
            near_start = len(sketch.points)>=2 and point==list(sketch.points[0])
            if sketch.points and point==list(sketch.points[-1]):
                self.editor.statusBar().showMessage("Point locked to the current endpoint. Choose another point to extend the sketch.",4000)
                return
            if self.arc_mode and sketch.points:
                if self.arc_through is None:
                    self.arc_through = point
                    self.editor.statusBar().showMessage("Arc: click its end point, or the first sketch point to close the outline. Esc cancels.")
                    self.update()
                    return
                candidate.add_arc(self.arc_through, sketch.points[0] if near_start else point, close=near_start)
                self.arc_through = None
            elif near_start and (len(sketch.points)>=3 or any(sketch.arcs)):
                candidate.close()
            else:
                candidate.add_point(point)
            self.editor.commit(candidate)
        except ValueError as error:
            self.error.emit(str(error))

    def mouseDoubleClickEvent(self,event):
        """Request a dimension editor for a hit segment when drawing is inactive or the
        outline is closed.

        Args:
            event (Qt event): Input, paint, resize, focus, or close event delivered by
                the framework.

        Returns:
            None. Emits dimension_requested with the segment index when applicable.
        """
        index = self.hit(event.position())
        if index>=0 and (not self.drawing or self.editor.sketch.closed):
            self.dimension_requested.emit(index)

    def mouseMoveEvent(self,event):
        """Preview a constrained endpoint drag or update panning, snapped cursor position,
        and drawing preview.

        Args:
            event (Qt event): Input, paint, resize, focus, or close event delivered by
                the framework.

        Returns:
            None. Repaints; drag previews are committed only on mouse release.
        """
        if self.drag_index is not None:
            position = [(event.position().x()-self.origin.x())/self.zoom,
                        (self.origin.y()-event.position().y())/self.zoom]
            candidate = copy.deepcopy(self.drag_original)
            try:
                candidate.move_point(self.drag_index, position)
                self.drag_candidate = candidate
                self.editor.sketch = candidate
            except ValueError as error:
                self.editor.statusBar().showMessage(str(error), 3000)
            self.update()
            return
        if self.pan is not None:
            self.origin += event.position()-self.pan
            self.pan = event.position()
        self.cursor = self.world(event.position())
        self.update()

    def mouseReleaseEvent(self,event):
        """Commit one valid endpoint-drag edit on left release, or finish middle-button
        panning.

        Args:
            event (Qt event): Input, paint, resize, focus, or close event delivered by
                the framework.

        Returns:
            None. Restores the original before committing so the drag produces one undo
            step.
        """
        if event.button()==Qt.LeftButton and self.drag_index is not None:
            original, candidate = self.drag_original, self.drag_candidate
            self.editor.sketch = original
            self.drag_index = self.drag_original = self.drag_candidate = None
            try:
                if candidate is not None and candidate.geometry() != original.geometry():
                    self.editor.commit(candidate)
                    self.editor.statusBar().showMessage("Point moved · Ctrl+Z to undo", 5000)
            except (ValueError, RuntimeError) as error:
                self.editor.statusBar().showMessage(f"Cannot move point: {error}", 7000)
            self.update()
            return
        if event.button()==Qt.MiddleButton:
            self.pan = None

    def leaveEvent(self,event):
        """Clear cursor/snapping preview when the pointer leaves the canvas and delegate
        the event.

        Args:
            event (Qt event): Input, paint, resize, focus, or close event delivered by
                the framework.

        Returns:
            None. Schedules a repaint.
        """
        self.cursor = None
        self._snap_lock = self.snap_target = None
        self.update()
        super().leaveEvent(event)

    def wheelEvent(self,event):
        """Zoom around the pointer while keeping the underlying screen location stable.

        Args:
            event (Qt event): Input, paint, resize, focus, or close event delivered by
                the framework.

        Returns:
            None. Updates zoom/origin within supported limits and repaints.
        """
        old = self.zoom
        self.zoom = max(10,min(1e7,self.zoom*(1.2 if event.angleDelta().y()>0 else 1/1.2)))
        point = event.position()
        self.origin = point+(self.origin-point)*(self.zoom/old)
        self.update()

    def keyPressEvent(self,event):
        """Cancel an endpoint drag or leave drawing mode on Escape; delegate other keys.

        Args:
            event (Qt event): Input, paint, resize, focus, or close event delivered by
                the framework.

        Returns:
            None. Restores uncommitted drag geometry when cancelled.
        """
        if event.key()==Qt.Key_Escape:
            if self.drag_index is not None:
                self.editor.sketch = self.drag_original
                self.drag_index = self.drag_original = self.drag_candidate = None
                self.update()
                self.editor.statusBar().showMessage("Point move canceled", 3000)
                return
            self.editor.select_mode()
        else:
            super().keyPressEvent(event)

    def fit(self):
        """Fit the outline and optional projected solid context into the canvas with a
        margin.

        Returns:
            None. Updates zoom and origin, then repaints.
        """
        points = list(self.editor.sketch.outline_points)
        if hasattr(self.editor, "sketch_context_points"):
            points.extend(self.editor.sketch_context_points())
        if not points:
            self.origin = QPointF(self.width()/2,self.height()/2)
        else:
            xs,ys = zip(*points)
            self.zoom = max(10,min((self.width()-140)/max(.01,max(xs)-min(xs)),(self.height()-140)/max(.01,max(ys)-min(ys)),1e7))
            self.origin = QPointF(self.width()/2-(min(xs)+max(xs))/2*self.zoom,
                                  self.height()/2+(min(ys)+max(ys))/2*self.zoom)
        self.update()

    def paintEvent(self,event):
        """Draw grid, context, outline, dimensions, relations, endpoints, snapping markers,
        and tool previews.

        Args:
            event (Qt event): Input, paint, resize, focus, or close event delivered by
                the framework.

        Returns:
            None. Paints the canvas and refreshes dimension-label hit-test positions.
        """
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        painter.fillRect(self.rect(),QColor("#2e2e33"))
        step = 10**math.ceil(math.log10(24/self.zoom))
        pixels = step*self.zoom
        painter.setPen(QPen(QColor("#404044"),1))
        for x in range(int(self.origin.x()%pixels),self.width(),max(1,int(pixels))):
            painter.drawLine(x,0,x,self.height())
        for y in range(int(self.origin.y()%pixels),self.height(),max(1,int(pixels))):
            painter.drawLine(0,y,self.width(),y)
        painter.setPen(QPen(QColor("#777777"),1))
        painter.drawLine(QPointF(0,self.origin.y()),QPointF(self.width(),self.origin.y()))
        painter.drawLine(QPointF(self.origin.x(),0),QPointF(self.origin.x(),self.height()))
        if hasattr(self.editor,"paint_sketch_context"):
            self.editor.paint_sketch_context(painter,self)
        painter.setBrush(Qt.NoBrush)
        sketch = self.editor.sketch
        if sketch.closed:
            path = QPainterPath(self.screen(sketch.points[0]))
            for i in range(len(sketch.edges)):
                path.connectPath(self.segment_path(i))
            path.closeSubpath()
            painter.fillPath(path,QColor(71,185,213,65))
        self.labels = []
        selected_segments = set(self.editor.selected_segments())
        for i,(a,b) in enumerate(sketch.edges):
            selected = i in selected_segments
            painter.setPen(QPen(QColor("#ffc078" if selected else "#79d6e9"),3 if selected else 2))
            points = sketch.segment_points(i)
            painter.drawPath(self.segment_path(i))
            if sketch.dimensions[i] is None:
                continue
            a,b = self.screen(sketch.points[a]),self.screen(sketch.points[b])
            painter.setPen(QPen(QColor("#f4bf73"),1))
            if sketch.is_arc(i):
                center = self.screen(sketch.arc_parameters(i)[0])
                midpoint = self.screen(points[len(points)//2])
                painter.drawLine(center,midpoint)
                painter.drawEllipse(center,2,2)
                label = (center+midpoint)*.5 + QPointF(0,-12)
            else:
                dx,dy = b.x()-a.x(),b.y()-a.y()
                length = math.hypot(dx,dy)
                normal = QPointF(-dy/length*24,dx/length*24)
                da,db = a+normal,b+normal
                painter.drawLine(da,db)
                painter.drawLine(a,da+normal*.2)
                painter.drawLine(b,db+normal*.2)
                label = (da+db)*.5
            self.labels.append((i,label))
            text = ("R " if sketch.is_arc(i) else "") + f"{sketch.dimensions[i]*1000:.3f}".rstrip("0").rstrip(".")+" mm"
            painter.fillRect(int(label.x()-48),int(label.y()-11),96,20,QColor("#2e2e33"))
            painter.drawText(int(label.x()-45),int(label.y()+4),text)
        relation_marks = {}
        for number,relation in enumerate(sketch.constraints,1):
            mark = {"horizontal":"H","vertical":"V","equal":f"={number}"}[relation["type"]]
            for index in relation["segments"]:
                relation_marks.setdefault(index,[]).append(mark)
        painter.setPen(QColor("#a8d5ad"))
        for index,marks in relation_marks.items():
            a,b = (self.screen(sketch.points[v]) for v in sketch.edges[index])
            painter.drawText((a+b)*.5+QPointF(6,-10)," · ".join(marks))
        for i,point in enumerate(sketch.points):
            painter.setBrush(QColor("#ffc078" if i==self.drag_index or (i==0 and not sketch.closed) else "#e5f2fa"))
            painter.setPen(Qt.NoPen)
            painter.drawEllipse(self.screen(point),6 if i==self.drag_index else 4,6 if i==self.drag_index else 4)
        # Vertex dots use a solid brush. Never let it fill an open arc preview:
        # QPainter otherwise closes the path with a chord and paints a wedge.
        painter.setBrush(Qt.NoBrush)
        if self.drawing and self.circle_mode and self.circle_center is not None and self.cursor is not None:
            painter.setPen(QPen(QColor("#b3d6e7"),1,Qt.DashLine))
            center = self.screen(self.circle_center)
            radius = math.dist(self.circle_center,self.cursor)*self.zoom
            painter.drawEllipse(center,radius,radius)
            painter.drawLine(center,self.screen(self.cursor))
            painter.drawText(center+QPointF(12,-12),f"R {radius/self.zoom*1000:.3f} mm")
        if self.drawing and not self.circle_mode and not sketch.closed and sketch.points and self.cursor:
            painter.setPen(QPen(QColor("#b3d6e7"),1,Qt.DashLine))
            points = [sketch.points[-1],self.cursor]
            if self.arc_mode and self.arc_through is not None:
                try:
                    preview = Sketch([sketch.points[-1]])
                    preview.add_arc(self.arc_through,self.cursor)
                    points = preview.segment_points(0)
                except ValueError:
                    points = [sketch.points[-1],self.arc_through,self.cursor]
            path = QPainterPath(self.screen(points[0]))
            for point in points[1:]:
                path.lineTo(self.screen(point))
            painter.drawPath(path)
        painter.setBrush(Qt.NoBrush)
        painter.setPen(QPen(QColor("#e2a86d"),2))
        painter.drawEllipse(self.origin,6,6)
        painter.drawLine(self.origin+QPointF(-10,0),self.origin+QPointF(10,0))
        painter.drawLine(self.origin+QPointF(0,-10),self.origin+QPointF(0,10))
        painter.setPen(QColor("#c5b6a8"))
        painter.drawText(self.origin+QPointF(12,-10),"Origin (0, 0)")
        if self.drawing and not sketch.closed and self.snap_target is not None and self.cursor is not None:
            point,label = self.snap_target
            marker = self.screen(point)
            painter.setPen(QPen(QColor("#ffd078"),2))
            painter.drawRect(QRectF(marker.x()-7,marker.y()-7,14,14))
            painter.drawText(marker+QPointF(12,20),label+" · locked")
        painter.setPen(QColor("#b1c5d8"))
        hint = "Arc: start → point on curve → end" if self.arc_mode else "XY sketch · millimeters · click the first point to enclose a face"
        if self.circle_mode:
            hint = "Circle: click center → click edge · Esc cancels"
        painter.drawText(14,24,hint if self.circle_mode else getattr(self.editor,"sketch_plane_label",hint))



class PartEditor(QMainWindow):
    def __init__(self,path=None):
        """Build the sketch editor, default draft, property controls, actions, and undo
        stacks; optionally load a document.

        Args:
            path (str or Path): Source or destination file path used by this operation.

        Returns:
            None.
        """
        super().__init__()
        self.sceneWindows = []
        self.resize(1150,760)
        self.setStyleSheet("""
            QMainWindow, QWidget { background-color: #2b2b2b; color: #e8e8e8; }
            QLineEdit, QDoubleSpinBox, QTableWidget { background-color: #222; color: #eee; border: 1px solid #555; }
            QMenuBar, QMenu, QToolBar, QHeaderView::section { background-color: #242424; color: #eee; }
            QMenu::item:selected, QToolButton:checked { background-color: #4a4a4a; }
            QToolBar { spacing: 6px; padding: 6px; border: none; }
            QToolButton { padding: 8px; background-color: #343434; border: 1px solid #555; border-radius: 3px; }
            QToolButton:hover { background-color: #484848; }
            QPushButton { padding: 6px; background-color: #3a3a3a; border: 1px solid #666; }
            QPushButton:hover { background-color: #505050; }
        """)
        self.data = new_document()
        self.sketch = Sketch()
        self.path = None
        self.dirty = False
        self.history,self.future = [],[]
        self.canvas = SketchCanvas(self)
        self.canvas.selected.connect(self.select_line)
        self.canvas.dimension_requested.connect(self.dimension_dialog)
        self.canvas.error.connect(lambda text: self.statusBar().showMessage(text,8000))
        center = QWidget()
        layout = QHBoxLayout(center)
        layout.addWidget(self.canvas,1)
        side = QVBoxLayout()
        side.addWidget(QLabel("Part properties"))
        side.addWidget(QLabel("Part name:"))
        self.name = QLineEdit(self.data["name"])
        self.name.textEdited.connect(self.change_name)
        side.addWidget(self.name)
        hint = QLabel("Draw lines or three-point arcs. Click the first point or Close outline.\n\nIn Select line mode, drag an endpoint to move it within its constraints. Esc cancels the drag.\n\nDimensions are manual: select a segment and click Add dimension. Lines measure length; arcs measure radius (R).")
        hint.setWordWrap(True)
        side.addWidget(hint)
        self.lines = QTableWidget(0,2)
        self.lines.setHorizontalHeaderLabels(["Segment","Dimension (mm)"])
        self.lines.horizontalHeader().setSectionResizeMode(QHeaderView.Stretch)
        self.lines.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.lines.setSelectionMode(QAbstractItemView.ExtendedSelection)
        self.lines.setMaximumHeight(220)
        self.lines.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.lines.itemSelectionChanged.connect(self.on_segment_selection_changed)
        side.addWidget(self.lines)
        self.length = QDoubleSpinBox()
        self.length.setRange(.001,1e9)
        self.length.setDecimals(4)
        self.length.setSuffix(" mm")
        self.length.setToolTip("Length of the selected line in millimeters")
        self.dimension_label = QLabel("Selected line length:")
        side.addWidget(self.dimension_label)
        side.addWidget(self.length)
        self.dimension_button = QPushButton("Add dimension")
        self.dimension_button.clicked.connect(self.apply_dimension)
        side.addWidget(self.dimension_button)
        self.remove_dimension_button = QPushButton("Remove dimension")
        self.remove_dimension_button.clicked.connect(self.clear_dimension)
        side.addWidget(self.remove_dimension_button)
        side.addWidget(QLabel("Constraints"))
        relation_hint = QLabel("Select a line for Horizontal/Vertical. Ctrl-click two or more straight lines for Equal.")
        relation_hint.setWordWrap(True)
        side.addWidget(relation_hint)
        relation_buttons = QHBoxLayout()
        for title,kind in (("Horizontal","horizontal"),("Vertical","vertical"),("Equal","equal")):
            button = QPushButton(title)
            button.clicked.connect(lambda checked=False,k=kind:self.apply_geometric_constraint(k))
            relation_buttons.addWidget(button)
        side.addLayout(relation_buttons)
        self.constraint_list = ConstraintList()
        self.constraint_list.setObjectName("sketchConstraints")
        self.constraint_list.setMinimumHeight(90)
        self.constraint_list.setMaximumHeight(160)
        self.constraint_list.currentItemChanged.connect(self.select_constraint)
        self.constraint_list.delete_requested.connect(self.delete_selected_constraint)
        side.addWidget(self.constraint_list)
        self.delete_constraint_button = QPushButton("Delete selected constraint")
        self.delete_constraint_button.setEnabled(False)
        self.delete_constraint_button.clicked.connect(self.delete_selected_constraint)
        side.addWidget(self.delete_constraint_button)
        delete_relation = QAction("Delete selected constraint",self)
        delete_relation.triggered.connect(self.delete_selected_constraint)
        self.constraint_list.addAction(delete_relation)
        self.constraint_list.setContextMenuPolicy(Qt.ActionsContextMenu)
        form = QFormLayout()
        self.thickness = QDoubleSpinBox()
        self.thickness.setRange(.001,1e9)
        self.thickness.setDecimals(3)
        self.thickness.setSuffix(" mm")
        self.thickness.setValue(10)
        self.thickness.valueChanged.connect(self.change_thickness)
        form.addRow("Thickness:",self.thickness)
        side.addLayout(form)
        self.summary = QLabel()
        self.summary.setWordWrap(True)
        side.addWidget(self.summary)
        side.addStretch()
        sidebar = QWidget()
        sidebar.setLayout(side)
        sidebar.setMinimumWidth(220)
        self.propertiesDock = QDockWidget("Part properties", self)
        self.propertiesDock.setAllowedAreas(Qt.LeftDockWidgetArea | Qt.RightDockWidgetArea)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setWidget(sidebar)
        self.propertiesDock.setWidget(scroll)
        self.addDockWidget(Qt.RightDockWidgetArea, self.propertiesDock)
        self._propertiesAutoHidden = False
        self.setCentralWidget(center)
        self.make_actions()
        self.refresh()
        if path:
            self.open_path(path)

    def make_actions(self):
        """Create file/edit/view/help menus, sketch tools, constraint actions, and keyboard
        shortcuts.

        Returns:
            None. Connects UI actions to editor callbacks.
        """
        file_menu = self.menuBar().addMenu("File")
        new_menu = file_menu.addMenu("New")
        new_scene = QAction("Scene", self)
        new_scene.triggered.connect(self.new_scene)
        new_menu.addAction(new_scene)
        new_part = QAction("Part", self)
        new_part.setShortcut("Ctrl+N")
        new_part.triggered.connect(self.new_part)
        new_menu.addAction(new_part)
        edit_menu = self.menuBar().addMenu("Edit")
        toolbar = self.addToolBar("Sketch")
        toolbar.setMovable(False)
        self.addToolBar(Qt.LeftToolBarArea, toolbar)
        for name,shortcut,callback in [("Open Part…","Ctrl+O",self.open_part),
                                       ("Save SimuO Part","Ctrl+S",self.save),("Save SimuO Part As…","Ctrl+Shift+S",self.save_as)]:
            action = QAction(name,self)
            action.setShortcut(shortcut)
            action.triggered.connect(callback)
            action.setToolTip(name)
            action.setStatusTip(name)
            file_menu.addAction(action)
        export_menu = file_menu.addMenu("Export")
        for label, kind in (("OBJ…", "obj"), ("STL…", "stl")):
            action = QAction(label, self)
            action.triggered.connect(lambda checked=False, kind=kind: self.export_mesh(kind))
            export_menu.addAction(action)
        for name,shortcut,callback in [("Undo","Ctrl+Z",self.undo),("Redo","Ctrl+Shift+Z",self.redo)]:
            action = QAction(name,self)
            action.setShortcut(shortcut)
            action.triggered.connect(callback)
            edit_menu.addAction(action)
        delete_line = QAction("Delete selected line / arc", self)
        delete_line.setShortcuts(["Backspace", "Delete"])
        delete_line.setShortcutContext(Qt.WidgetShortcut)
        delete_line.setAutoRepeat(False)
        delete_line.triggered.connect(self.delete_selected_segment)
        edit_menu.addAction(delete_line)
        self.canvas.addAction(delete_line)
        self.lines.addAction(delete_line)
        self.line_action = QAction("Draw lines",self)
        self.line_action.setToolTip("Click to place connected points. Click the first point to close the outline. Esc switches to selection.")
        self.line_action.setCheckable(True)
        self.line_action.setChecked(True)
        self.line_action.toggled.connect(self.set_drawing)
        toolbar.addAction(self.line_action)
        self.arc_action = QAction("Draw arcs",self)
        self.arc_action.setCheckable(True)
        self.arc_action.setToolTip("Three-point arc: click the start, a point on the curve, and the end. Connected arcs reuse the last endpoint.")
        self.arc_action.toggled.connect(self.set_arcs)
        toolbar.addAction(self.arc_action)
        self.circle_action = QAction("Draw circle",self)
        self.circle_action.setCheckable(True)
        self.circle_action.setToolTip("Click the center, then the edge to create a closed circle. Esc cancels. Add a dimension to set its radius.")
        self.circle_action.toggled.connect(self.set_circles)
        toolbar.addAction(self.circle_action)
        self.select_action = QAction("Select line", self)
        self.select_action.setToolTip("Select a line or dimension label, or drag an endpoint to move it within its constraints")
        self.select_action.triggered.connect(self.select_mode)
        toolbar.addAction(self.select_action)
        for name,callback,hint in [
            ("Close outline",self.close_face,"Connect the last point to the first to create a face"),
            ("Add dimension…",lambda: self.dimension_dialog(self.canvas.selection),"Add or edit a line length or arc radius in millimeters"),
            ("Frame sketch",self.canvas.fit,"Fit the entire sketch in the viewport (F)"),
        ]:
            action = QAction(name,self)
            action.setToolTip(hint)
            action.setStatusTip(hint)
            action.triggered.connect(callback)
            toolbar.addAction(action)
            if name == "Frame sketch":
                action.setShortcut("F")
                frame_action = action
        view_menu = self.menuBar().addMenu("View")
        view_menu.addAction(frame_action)
        self.origin_action = QAction("Center sketch origin",self)
        self.origin_action.setShortcut("O")
        self.origin_action.setToolTip("Center the sketch plane's (0, 0) point without changing geometry")
        self.origin_action.triggered.connect(self.canvas.center_origin)
        view_menu.addAction(self.origin_action)
        view_menu.addAction(self.propertiesDock.toggleViewAction())
        help_menu = self.menuBar().addMenu("Help")
        controls = QAction("Controls and workflow", self)
        controls.setShortcut("F1")
        controls.triggered.connect(self.show_controls)
        help_menu.addAction(controls)
        relations_menu = self.menuBar().addMenu("Constraints")
        for title,kind in (("Make horizontal","horizontal"),("Make vertical","vertical"),("Make equal","equal")):
            action = QAction(title,self)
            action.setToolTip("Select straight lines first; Ctrl-click to select several")
            action.triggered.connect(lambda checked=False,k=kind:self.apply_geometric_constraint(k))
            relations_menu.addAction(action)
        relations_menu.addSeparator()
        remove = QAction("Delete selected constraint",self)
        remove.triggered.connect(self.delete_selected_constraint)
        relations_menu.addAction(remove)

    def resizeEvent(self, event):
        """Hide properties automatically below 800 pixels and restore them when space
        returns.

        Args:
            event (Qt event): Input, paint, resize, focus, or close event delivered by
                the framework.

        Returns:
            None. Delegates resize handling and tracks whether hiding was automatic.
        """
        super().resizeEvent(event)
        if not hasattr(self, "propertiesDock"):
            return
        if event.size().width() < 800 and not self.propertiesDock.isHidden():
            self.propertiesDock.hide()
            self._propertiesAutoHidden = True
        elif event.size().width() >= 800 and self._propertiesAutoHidden:
            self.propertiesDock.show()
            self._propertiesAutoHidden = False

    def show_controls(self):
        """Display the sketch editor's drawing, dimensioning, constraints, export, and
        navigation help.

        Returns:
            None. Opens an informational dialog.
        """
        QMessageBox.information(
            self, "SimuO Part Editor — Controls",
            "1. Draw lines: click to place connected points. Click the first point or Close outline to create a face.\n\n"
            "Draw arcs: click the start, a point on the curve, then the end. Connected arcs reuse the previous endpoint. Esc cancels a pending arc. Arc dimensions measure radius (R), not curve length.\n\n"
            "Draw circle: in an empty sketch, click the center then the edge. A preview shows the radius. Esc cancels. Add a radius dimension to resize the circle. The closed circle is ready to extrude.\n\n"
            "Constraints: select a straight line for Horizontal or Vertical. Ctrl-click two or more lines for Equal. Select a relation or dimension in the Constraints list, then Delete to remove that rule without deleting geometry.\n\n"
            "2. Dimensions are manual: choose Select line, click an edge or table row, enter a length and click Add dimension. You can also use Add dimension in the toolbar or double-click a line. Only dimensioned lines show labels. Use Update dimension to edit a dimension and Remove dimension to remove it.\n\n"
            "3. Set the thickness, then use File → Save SimuO Part to keep an editable part. File → Export writes an OBJ or STL mesh from a closed outline.\n\n"
            "Backspace/Delete removes a selected line or arc. Ctrl+Z undoes deletion.\n\n"
            "In Select line mode, drag an endpoint to move it. Explicit constraints limit movement; other endpoints stay fixed. Esc cancels the drag and Ctrl+Z undoes it.\n\n"
            "Middle-drag: pan · Scroll: zoom · F: frame sketch · Esc: select mode\n"
            "Ctrl+S: save · Ctrl+Z: undo · Ctrl+Shift+Z: redo\n\n"
            "All sketch lengths and thickness are shown in millimeters.",
        )

    def set_drawing(self,value):
        """Toggle straight-line drawing and clear incompatible arc/circle modes and
        previews.

        Args:
            value (bool): Enable the requested drawing mode when True; disable it when
                False.

        Returns:
            None. Updates canvas state and schedules a repaint.
        """
        if value and hasattr(self,"arc_action"):
            self.arc_action.setChecked(False)
        if value and hasattr(self,"circle_action"):
            self.circle_action.setChecked(False)
        self.canvas.circle_mode = False
        self.canvas.circle_center = None
        self.canvas.arc_mode = False
        self.canvas.arc_through = None
        self.canvas.drawing = value
        self.canvas.update()

    def set_arcs(self,value):
        """Toggle three-point arc drawing and clear incompatible modes and pending curve
        points.

        Args:
            value (bool): Enable the requested drawing mode when True; disable it when
                False.

        Returns:
            None. Updates action checks and canvas state.
        """
        if value:
            self.line_action.setChecked(False)
            self.circle_action.setChecked(False)
        self.canvas.circle_mode = False
        self.canvas.circle_center = None
        self.canvas.arc_mode = value
        self.canvas.arc_through = None
        self.canvas.drawing = value
        self.canvas.update()

    def set_circles(self,value):
        """Toggle circle drawing and clear incompatible modes and previews.

        Args:
            value (bool): Enable the requested drawing mode when True; disable it when
                False.

        Returns:
            None. Updates actions, canvas state, and enabled-tool guidance.
        """
        if value:
            self.line_action.setChecked(False)
            self.arc_action.setChecked(False)
        self.canvas.circle_mode = value
        self.canvas.circle_center = None
        self.canvas.arc_mode = False
        self.canvas.arc_through = None
        self.canvas.drawing = value
        self.canvas.update()
        if value:
            self.statusBar().showMessage("Circle: click the center, then the edge. Esc cancels.")

    def select_mode(self):
        """Disable all drawing tools and discard pending curve preview points.

        Returns:
            None. Leaves geometry unchanged and schedules a repaint.
        """
        self.line_action.setChecked(False)
        self.arc_action.setChecked(False)
        self.circle_action.setChecked(False)
        self.canvas.circle_center = None
        self.canvas.arc_through = None
        self.canvas.drawing = False
        self.canvas.update()

    def commit(self,candidate):
        """Validate a sketch candidate before replacing the working sketch and recording
        undo history.

        Args:
            candidate (Sketch): Independently edited outline to validate and commit.

        Returns:
            None. Clears redo, marks dirty, and refreshes controls; invalid candidates
            raise ValueError.
        """
        candidate.validate()
        self.history.append(copy.deepcopy(self.sketch))
        self.future.clear()
        self.sketch = candidate
        self.dirty = True
        if candidate.closed:
            self.select_mode()
        self.refresh()

    def undo(self):
        """Restore the previous sketch and move the current one to redo history.

        Returns:
            None. Updates drawing mode and dirty state if undo history exists.
        """
        if self.history:
            self.future.append(copy.deepcopy(self.sketch))
            self.sketch = self.history.pop()
            self.dirty = True
            self.select_mode()
            self.line_action.setChecked(not self.sketch.closed)
            self.refresh()

    def redo(self):
        """Restore a redo sketch and preserve the current one in undo history.

        Returns:
            None. Updates drawing mode and dirty state if redo history exists.
        """
        if self.future:
            self.history.append(copy.deepcopy(self.sketch))
            self.sketch = self.future.pop()
            self.dirty = True
            self.select_mode()
            self.line_action.setChecked(not self.sketch.closed)
            self.refresh()

    def refresh(self):
        """Synchronize title, segment table, dimensions, thickness, constraints, summary,
        and canvas with the current sketch.

        Returns:
            None. Blocks control signals while populating values to avoid recursive
            edits.
        """
        self.setWindowTitle(f"{'*' if self.dirty else ''}{self.data['name']} — SimuO Part Editor")
        self.lines.blockSignals(True)
        self.lines.setRowCount(len(self.sketch.edges))
        for i,_ in enumerate(self.sketch.edges):
            arc = self.sketch.is_arc(i)
            self.lines.setItem(i,0,QTableWidgetItem(f"{'Arc' if arc else 'Line'} {i+1}"))
            dimension = self.sketch.dimensions[i]
            self.lines.setItem(i,1,QTableWidgetItem("—" if dimension is None else ("R " if arc else "")+f"{dimension*1000:.4f}"))
        self.lines.blockSignals(False)
        self.thickness.blockSignals(True)
        self.thickness.setValue(self.sketch.thickness*1000)
        self.thickness.blockSignals(False)
        self.canvas.selection = min(self.canvas.selection,len(self.sketch.edges)-1)
        self.canvas.labels = []
        self.select_line(self.canvas.selection,sync_table=False)
        self.refresh_constraints()
        area = abs(self.sketch.signed_area)
        self.summary.setText(f"{'FACE CREATED' if self.sketch.closed else 'OPEN SKETCH'}\n{len(self.sketch.edges)} segments\nArea: {area*1e6:.3f} mm²\nClosed faces save as extruded solids. Open sketches save as editable drafts.")
        self.statusBar().showMessage("Draw lines / Draw arcs / Draw circle / Select line · Curves dimension by radius · F1: controls")
        self.canvas.update()

    def select_line(self,index,sync_table=True):
        """Select an edge and configure its line-length or arc-radius controls, optionally
        synchronizing the table row.

        Args:
            index (int): Zero-based sketch edge index; -1 represents no selection in
                selection callbacks.
            sync_table (bool): Also select the matching table row when True.

        Returns:
            None. Invalid indices clear the canvas selection and disable dimension
            controls.
        """
        if not 0<=index<len(self.sketch.edges):
            self.canvas.selection = -1
            self.dimension_button.setEnabled(False)
            self.remove_dimension_button.setEnabled(False)
            self.length.setEnabled(False)
            self.canvas.update()
            return
        self.canvas.selection = index
        self.dimension_button.setEnabled(True)
        dimension = self.sketch.dimensions[index]
        arc = self.sketch.is_arc(index)
        self.dimension_label.setText("Arc radius:" if arc else "Selected line length:")
        self.length.setToolTip("Radius of the selected arc in millimeters" if arc else "Length of the selected line in millimeters")
        self.dimension_button.setText("Add dimension" if dimension is None else "Update dimension")
        self.remove_dimension_button.setEnabled(dimension is not None)
        self.length.setEnabled(True)
        self.length.setValue((self.sketch.dimension_value(index) if dimension is None else dimension)*1000)
        self.lines.blockSignals(True)
        if sync_table:
            self.lines.selectRow(index)
        self.lines.blockSignals(False)
        self.canvas.update()

    def selected_segments(self):
        """Collect selected table rows, falling back to the canvas selection.

        Returns:
            list: Sorted valid segment indices, or an empty list.
        """
        if not hasattr(self,"lines"):
            return []
        rows = sorted({index.row() for index in self.lines.selectionModel().selectedRows()
                       if index.row()<len(self.sketch.edges)})
        if not rows and 0<=self.canvas.selection<len(self.sketch.edges):
            rows = [self.canvas.selection]
        return rows

    def on_segment_selection_changed(self):
        """Synchronize the active canvas edge and dimension controls with table selection.

        Returns:
            None. Keeps multiple selected rows intact.
        """
        rows = sorted({index.row() for index in self.lines.selectionModel().selectedRows()})
        current = self.lines.currentRow()
        self.select_line(current if current in rows else rows[0] if rows else -1,sync_table=False)

    def select_segments(self,indices):
        """Replace table/canvas selection with the supplied valid edge indices.

        Args:
            indices (iterable): Zero-based sketch edge indices to select; invalid
                indices are ignored.

        Returns:
            None. Selects rows while blocking recursive selection signals.
        """
        indices = sorted({i for i in indices if 0<=i<len(self.sketch.edges)})
        self.lines.blockSignals(True)
        self.lines.clearSelection()
        for index in indices:
            self.lines.selectionModel().select(self.lines.model().index(index,0),QItemSelectionModel.Select|QItemSelectionModel.Rows)
        if indices:
            self.lines.setCurrentCell(indices[-1],0,QItemSelectionModel.NoUpdate)
        self.lines.blockSignals(False)
        self.select_line(indices[-1] if indices else -1,sync_table=False)
        self.canvas.update()

    def toggle_segment_selection(self,index):
        """Toggle one edge in the current table multi-selection.

        Args:
            index (int): Zero-based sketch edge index; -1 represents no selection in
                selection callbacks.

        Returns:
            None. Updates the table and canvas through select_segments.
        """
        rows = self.lines.selectionModel().selectedRows()
        indices = {row.row() for row in rows}
        indices.symmetric_difference_update({index})
        self.select_segments(indices)

    def apply_geometric_constraint(self,kind):
        """Add a relation to selected edges on a copy, then commit a solved sketch.

        Args:
            kind (str): Relation kind: horizontal, vertical, or equal.

        Returns:
            None. Displays duplicate guidance or a warning on conflicts without
            committing invalid geometry.
        """
        try:
            candidate = copy.deepcopy(self.sketch)
            if candidate.add_constraint(kind,self.selected_segments()):
                self.commit(candidate)
            else:
                self.statusBar().showMessage("That constraint is already applied.",5000)
        except (ValueError,RuntimeError) as error:
            QMessageBox.warning(self,"Cannot Apply Constraint",str(error))

    def refresh_constraints(self):
        """Rebuild the constraints list from geometric relations and driving dimensions,
        preserving a matching selection.

        Returns:
            None. Updates list contents and deletion-button availability.
        """
        item = self.constraint_list.currentItem()
        selected = item.data(Qt.UserRole) if item is not None else None
        self.constraint_list.blockSignals(True)
        self.constraint_list.clear()
        for index,relation in enumerate(self.sketch.constraints):
            names = ", ".join(str(i+1) for i in relation["segments"])
            item = QListWidgetItem(f"{relation['type'].title()} — Line{'s' if len(relation['segments'])>1 else ''} {names}")
            item.setData(Qt.UserRole,("relation",index))
            self.constraint_list.addItem(item)
        for index,value in enumerate(self.sketch.dimensions):
            if value is not None:
                arc = self.sketch.is_arc(index)
                item = QListWidgetItem(f"{'Radius — Arc' if arc else 'Length — Line'} {index+1}: {value*1000:g} mm")
                item.setData(Qt.UserRole,("dimension",index))
                self.constraint_list.addItem(item)
        for row in range(self.constraint_list.count()):
            if self.constraint_list.item(row).data(Qt.UserRole)==selected:
                self.constraint_list.setCurrentRow(row)
                break
        self.constraint_list.blockSignals(False)
        self.delete_constraint_button.setEnabled(self.constraint_list.currentItem() is not None)

    def select_constraint(self,item,previous=None):
        """Highlight the segments affected by the selected relation or dimension entry.

        Args:
            item (QListWidgetItem or None): Constraint entry storing relation/dimension
                kind and index.
            previous (QListWidgetItem, optional): Previously selected constraint entry;
                currently unused.

        Returns:
            None. Enables deletion when a constraint item exists.
        """
        self.delete_constraint_button.setEnabled(item is not None)
        if item is None:
            return
        kind,index = item.data(Qt.UserRole)
        indices = self.sketch.constraints[index]["segments"] if kind=="relation" else [index]
        self.select_segments(indices)

    def delete_selected_constraint(self):
        """Remove the selected relation or driving dimension on a copy without deleting
        geometry.

        Returns:
            None. Commits a valid sketch or displays an error/guidance.
        """
        item = self.constraint_list.currentItem()
        if item is None:
            self.statusBar().showMessage("Select a constraint or dimension from the Constraints list first.",5000)
            return
        kind,index = item.data(Qt.UserRole)
        candidate = copy.deepcopy(self.sketch)
        if kind=="relation":
            candidate.remove_constraint(index)
        else:
            candidate.dimensions[index] = None
        try:
            self.commit(candidate)
        except (ValueError,RuntimeError) as error:
            QMessageBox.warning(self,"Cannot Delete Constraint",str(error))

    def apply_dimension(self):
        """Convert the selected dimension control from millimetres to metres and apply it
        through a candidate sketch.

        Returns:
            None. Commits valid geometry or displays a dimension error.
        """
        try:
            candidate = copy.deepcopy(self.sketch)
            candidate.set_dimension(self.canvas.selection,self.length.value()/1000)
            self.commit(candidate)
        except ValueError as error:
            QMessageBox.warning(self,"Cannot Apply Dimension",str(error))

    def dimension_dialog(self,index):
        """Prompt for a selected segment's line length or arc radius in millimetres and
        apply an accepted value.

        Args:
            index (int): Zero-based sketch edge index; -1 represents no selection in
                selection callbacks.

        Returns:
            None. Cancelling leaves the geometry unchanged.
        """
        if not 0<=index<len(self.sketch.edges):
            self.statusBar().showMessage("Select a line or its dimension label first.",5000)
            return
        self.select_line(index)
        arc = self.sketch.is_arc(index)
        label = f"Arc {index+1} radius (mm):" if arc else f"Line {index+1} length (mm):"
        value,ok = QInputDialog.getDouble(self,"Add / Edit Radius" if arc else "Add / Edit Dimension",label,self.length.value(),.001,1e9,4)
        if ok:
            self.length.setValue(value)
            self.apply_dimension()

    def clear_dimension(self):
        """Remove the selected edge's driving dimension while preserving its current
        geometry.

        Returns:
            None. Commits only when a dimension exists.
        """
        if 0<=self.canvas.selection<len(self.sketch.edges) and self.sketch.dimensions[self.canvas.selection] is not None:
            candidate = copy.deepcopy(self.sketch)
            candidate.dimensions[self.canvas.selection] = None
            self.commit(candidate)

    def delete_selected_segment(self):
        """Remove the selected edge while retaining one outline; reject edits that split
        into multiple sketches in this base editor.

        Returns:
            None. Commits the deletion or displays guidance; the feature editor supports
            split outlines.
        """
        try:
            remaining = self.sketch.without_segment(self.canvas.selection)
            if len(remaining) > 1:
                raise ValueError("Deleting this middle segment splits the outline. Use the 3D Part Editor to keep both sections as separate sketches.")
            self.commit(remaining[0])
            self.canvas.selection = -1
            self.select_mode()
            self.refresh()
        except ValueError as error:
            self.statusBar().showMessage(str(error), 8000)

    def close_face(self):
        """Validate and close the current outline through a sketch candidate.

        Returns:
            None. Commits valid closure or displays an error.
        """
        try:
            candidate = copy.deepcopy(self.sketch)
            candidate.close()
            self.commit(candidate)
        except ValueError as error:
            QMessageBox.warning(self,"Cannot Close Face",str(error))

    def change_name(self,value):
        """Update the document's name, mark it dirty, and refresh the window title.

        Args:
            value (str): Edited part name to store in document data.

        Returns:
            None. Does not validate the name until saving.
        """
        self.data["name"] = value
        self.dirty = True
        self.setWindowTitle(f"*{value} — SimuO Part Editor")

    def change_thickness(self,value):
        """Convert the thickness control's millimetres to metres and commit an edited
        sketch.

        Args:
            value (float): Thickness/next-extrusion control value in millimetres,
                converted to metres.

        Returns:
            None. Updates history and dirty state through commit.
        """
        candidate = copy.deepcopy(self.sketch)
        candidate.thickness = value/1000
        self.commit(candidate)

    def confirm_changes(self):
        """Protect dirty documents with Save/Discard/Cancel before replacing or closing
        them.

        Returns:
            bool: True if clean, discarded, or successfully saved; False on
            cancellation/save failure.
        """
        if not self.dirty:
            return True
        answer = QMessageBox.question(self,"Unsaved Part","Save changes to this part?",QMessageBox.Save|QMessageBox.Discard|QMessageBox.Cancel,QMessageBox.Save)
        return self.save() if answer==QMessageBox.Save else answer==QMessageBox.Discard

    def new_scene(self):
        """Open an independent empty scene editor and retain a reference to its window.

        Returns:
            None. Leaves the current part open.
        """
        from simuo.ui.scene_window import SimuOMainWindow

        window = SimuOMainWindow()
        self.sceneWindows.append(window)
        window.show()

    def new_part(self):
        """Protect unsaved changes, then reset the base editor to a new empty sketch
        document.

        Returns:
            None. Clears path, history, selection, and dirty state after confirmation.
        """
        if self.confirm_changes():
            self.data,self.sketch,self.path = new_document(),Sketch(),None
            self.history.clear()
            self.future.clear()
            self.name.setText(self.data["name"])
            self.dirty = False
            self.select_mode()
            self.line_action.setChecked(True)
            self.canvas.selection = -1
            self.refresh()

    def open_part(self):
        """Prompt for a part file and open it after protecting unsaved changes.

        Returns:
            None. Cancellation preserves the current document.
        """
        path,_ = QFileDialog.getOpenFileName(self,"Open SimuO Part","","SimuO Parts (*.simuOPart)")
        if path and self.confirm_changes():
            self.open_path(path)

    def open_path(self,path):
        """Load an editable document before replacing sketch/editor state and framing its
        geometry.

        Args:
            path (str or Path): Source or destination file path used by this operation.

        Returns:
            bool: True when loaded; False after a warning if loading fails.
        """
        try:
            data,sketch = open_document(path)
        except (OSError,ValueError,TypeError,OverflowError) as error:
            QMessageBox.warning(self,"Cannot Open Part",f"{error}\n\nThis editor supports JSON boxes and editable sketch parts. Legacy OBJ meshes do not contain an editable sketch.")
            return False
        self.data,self.sketch,self.path = data,sketch,Path(path)
        self.history.clear()
        self.future.clear()
        self.dirty = False
        self.name.setText(data["name"])
        self.select_mode()
        self.line_action.setChecked(not sketch.closed)
        self.canvas.selection = -1
        self.refresh()
        self.canvas.fit()
        return True

    def save(self):
        """Save to the current path, or prompt for a path when the document has never been
        saved.

        Returns:
            bool: True on successful save; False on cancellation or failure.
        """
        return self._save_to(self.path) if self.path else self.save_as()

    def export_mesh(self, kind):
        """Prompt for an OBJ/STL destination and export a closed sketch without changing
        the editable document's path or dirty state.

        Args:
            kind (str): Mesh format, obj or stl.

        Returns:
            bool: True when exported; False for an open sketch, cancellation, or
            reported failure.
        """
        if not self.sketch.closed:
            QMessageBox.warning(self, "Cannot Export Part", "Close the sketch outline before exporting OBJ or STL. Use Save SimuO Part to keep an unfinished sketch.")
            return False
        path, _ = QFileDialog.getSaveFileName(
            self, f"Export {kind.upper()}",
            str((self.path or Path("part.simuOPart")).with_suffix("."+kind)),
            f"{kind.upper()} Mesh (*.{kind})",
        )
        if not path:
            return False
        destination = Path(path)
        if destination.suffix.lower() != "."+kind:
            destination = destination.with_suffix("."+kind)
            if destination.exists() and QMessageBox.question(
                self, "Replace Export", f"Replace {destination.name}?", QMessageBox.Yes|QMessageBox.Cancel,
            ) != QMessageBox.Yes:
                return False
        try:
            export_sketch(destination, self.sketch, kind)
        except (OSError, ValueError, OverflowError) as error:
            QMessageBox.warning(self, "Cannot Export Part", str(error))
            return False
        self.statusBar().showMessage(f"Exported {destination} · geometry in metres", 8000)
        return True

    def save_as(self):
        """Prompt for a .simuOPart destination, confirm extension-adjusted overwrites, and
        save.

        Returns:
            bool: True when saved; False on cancellation or failure.
        """
        path,_ = QFileDialog.getSaveFileName(self,"Save SimuO Part",str(self.path or Path(self.data["name"]+".simuOPart")),"SimuO Parts (*.simuOPart)")
        if not path:
            return False
        path = Path(path)
        if path.suffix.lower()!=".simuopart":
            path = path.with_suffix(".simuOPart")
            if path.exists() and QMessageBox.question(self,"Replace Part",f"Replace {path.name}?",QMessageBox.Yes|QMessageBox.Cancel)!=QMessageBox.Yes:
                return False
        return self._save_to(path)

    def _save_to(self,path):
        """Write a validated sketch document and only then update the editor's path and
        clean state.

        Args:
            path (str or Path): Source or destination file path used by this operation.

        Returns:
            bool: True on success; False after displaying a save error.
        """
        try:
            data = save_document(path,self.data,self.sketch)
        except (OSError,ValueError,OverflowError) as error:
            QMessageBox.warning(self,"Cannot Save Part",str(error))
            return False
        self.path,self.data,self.dirty = Path(path),data,False
        self.refresh()
        self.statusBar().showMessage(f"Saved {path}",6000)
        return True

    def closeEvent(self,event):
        """Protect unsaved work before accepting or ignoring the window-close event.

        Args:
            event (Qt event): Input, paint, resize, focus, or close event delivered by
                the framework.

        Returns:
            None. Controls closure through the event object.
        """
        event.accept() if self.confirm_changes() else event.ignore()


def run_part_editor(path=None):
    """Create/show the current feature-based editor, reuse or create QApplication, and
    enter the Qt event loop.

    Args:
        path (str or Path): Source or destination file path used by this operation.

    Returns:
        int: Qt event-loop exit code after the editor application finishes.
    """
    from simuo.ui.parts.feature_editor import FeaturePartEditor
    from simuo.rendering.context import configure_opengl
    app = QApplication.instance()
    if app is None:
        configure_opengl()
        app = QApplication([])
    window = FeaturePartEditor(path)
    window.show()
    return app.exec()
