"""Interactive results-only control for a selected structural load."""
import numpy as np
from PySide6.QtCore import Qt, QSignalBlocker
from PySide6.QtWidgets import QWidget, QFormLayout, QComboBox, QSlider, QPushButton, QLabel, QStyleOptionSlider, QStyle
from PySide6.QtGui import QPainter, QColor, QPen
from simuo.structural.load_preview import selected_load


class StrengthSlider(QSlider):
    """Normal theme slider with yield and UTS reference ticks."""
    def __init__(self):
        super().__init__(Qt.Horizontal)
        self.markers = ()
        self.setMinimumHeight(40)

    def paintEvent(self, event):
        super().paintEvent(event)
        option = QStyleOptionSlider()
        self.initStyleOption(option)
        groove = self.style().subControlRect(QStyle.CC_Slider,option,QStyle.SC_SliderGroove,self)
        handle = self.style().subControlRect(QStyle.CC_Slider,option,QStyle.SC_SliderHandle,self)
        painter = QPainter(self)
        font = painter.font()
        font.setPointSize(8)
        painter.setFont(font)
        for fraction,label,color in self.markers:
            x = round(groove.left()+handle.width()/2+(groove.width()-handle.width())*fraction)
            painter.setPen(QPen(QColor(color),2))
            painter.drawLine(x,groove.center().y()-6,x,groove.center().y()+8)
            width=painter.fontMetrics().horizontalAdvance(label)
            painter.drawText(max(0,min(self.width()-width,x-width//2)),groove.center().y()-9,label)
        painter.end()


class LoadPreviewPanel(QWidget):
    def __init__(self, window):
        super().__init__()
        self.window = window
        self.response = self.current = None
        self.pending = False
        self.factor = 1.
        self.unit_scale = 1.
        self.cache = {}
        self.reference = None
        self._updating = False
        form = QFormLayout(self)
        form.setContentsMargins(0,8,0,8)
        form.addRow(QLabel('Load Preview — preview only'))
        self.loads = QComboBox()
        self.loads.setObjectName('inspectorCombo')
        self.loads.currentIndexChanged.connect(self.selection_changed)
        form.addRow('Selected load', self.loads)
        self.prepare_button = QPushButton('Prepare Preview')
        self.prepare_button.clicked.connect(self.prepare)
        form.addRow(self.prepare_button)
        self.slider = StrengthSlider()
        self.slider.setRange(0,10000)
        self.slider.setAccessibleName('Preview load magnitude')
        self.slider.valueChanged.connect(self.slide)
        form.addRow(self.slider)
        self.magnitude = window.numeric('Preview load magnitude',0.)
        self.magnitude.setDecimals(9)
        self.magnitude.setMaximum(1e100)
        self.magnitude.editingFinished.connect(self.number_changed)
        form.addRow('Magnitude',self.magnitude)
        self.maximum = window.numeric('Preview range maximum',1e-9)
        self.maximum.setMaximum(1e100)
        self.maximum.editingFinished.connect(self.range_changed)
        form.addRow('Range maximum',self.maximum)
        self.limits = QLabel('Run analysis, choose a nonzero load, then prepare its response.')
        self.limits.setWordWrap(True)
        form.addRow(self.limits)
        self.stats = QLabel()
        self.stats.setWordWrap(True)
        form.addRow(self.stats)
        self.reset_button = QPushButton('Reset Preview')
        self.reset_button.clicked.connect(self.reset)
        form.addRow(self.reset_button)
        self.refresh()

    @property
    def active(self):
        return self.current is not None

    def refresh(self):
        w = self.window
        if self.reference is not w.result:
            self.reset(clear_cache=True)
            self.reference = w.result
        key = self.loads.currentData()
        items = [(load.name or 'Load',load.identifier) for load in w.all_loads]
        if items != [(self.loads.itemText(i),self.loads.itemData(i)) for i in range(self.loads.count())]:
            with QSignalBlocker(self.loads):
                self.loads.clear()
                for text,identity in items:self.loads.addItem(text,identity)
                index=self.loads.findData(key)
                if index>=0:self.loads.setCurrentIndex(index)
        self.prepare_button.setEnabled(w.result is not None and not w.job.running and self.loads.currentData() is not None and not w._load_draft)
        self.loads.setEnabled(not w.job.running)
        for control in (self.slider,self.magnitude,self.maximum):control.setEnabled(self.active)
        self.reset_button.setEnabled(self.active or self.pending)
        if self.active:
            for action in w.tool_actions.values():action.setEnabled(False)
            w.deformation_action.setEnabled(False)
            w.deformed_shape.setEnabled(False)
            w.deformation_mode.model().item(w.deformation_mode.findData('auto')).setEnabled(False)

    def selection_changed(self):
        if not self._updating:self.reset()

    def prepare(self):
        w = self.window
        try:
            setup = w.setup()
            selected_load(setup,self.loads.currentData())
            if w.result is None or w.job.running:
                raise ValueError('Finish a successful analysis before preparing a preview')
            self.reset()
            self.reference=w.result
            key=(id(w.result),id(w.mesh),self.loads.currentData())
            if key in self.cache:
                self.accept(self.cache[key])
            else:
                self.pending=True
                w.start_job('preview',w.mesh,setup,w.result,self.loads.currentData())
                self.limits.setText('Preparing response; other loads and gravity remain fixed…')
                self.refresh()
        except ValueError as error:w.error(error)

    def accept(self,response):
        self.pending=False
        response.reference=self.window.result
        self.response=response
        key=(id(self.window.result),id(self.window.mesh),response.load_id)
        self.cache.pop(key,None)
        self.cache[key]=response
        while len(self.cache)>3:
            self.cache.pop(next(iter(self.cache)))
        self._updating=True
        try:
            pressure = self.load_kind()=='pressure'
            self.unit_scale = float(self.window.pressure_units.currentData()) if pressure else 1.
            self.magnitude.setSuffix(' '+self.window.pressure_units.currentText() if pressure else ' N')
            self.maximum.setSuffix(self.magnitude.suffix())
            limits=response.strength_limits
            finite=[v for v in limits.values() if v is not None and v>0]
            upper=max(2.,1.1*max(finite)) if finite else 2.
            self.maximum.setValue(min(upper*response.magnitude/self.unit_scale,1e100))
            self.magnitude.setMaximum(self.maximum.value())
            self.magnitude.setValue(response.magnitude/self.unit_scale)
            self.slider.setValue(round(10000*response.magnitude/self.unit_scale/self.maximum.value()))
            self.window.cancel_placement()
            self.window.view_mode.setCurrentText('Stress')
            self.window.deformation_mode.setCurrentIndex(self.window.deformation_mode.findData('true'))
            self.window.deformation_custom.setRange(.01,1000.)
            self.window.deformation_custom.setValue(1.)
        finally:self._updating=False
        self.apply(1.)

    def load_kind(self):
        return next((getattr(v,'kind','force') for v in self.window.all_loads if v.identifier==self.loads.currentData()),'force')

    def slide(self,value):
        if self._updating or not self.response:return
        magnitude=self.maximum.value()*value/10000
        with QSignalBlocker(self.magnitude):self.magnitude.setValue(magnitude)
        self.apply(magnitude*self.unit_scale/self.response.magnitude)

    def number_changed(self):
        if self._updating or not self.response:return
        with QSignalBlocker(self.slider):self.slider.setValue(round(10000*self.magnitude.value()/self.maximum.value()))
        self.apply(self.magnitude.value()*self.unit_scale/self.response.magnitude)

    def range_changed(self):
        if not self.active:return
        self.magnitude.setMaximum(self.maximum.value())
        self.number_changed()

    def apply(self,factor):
        if self._updating or not self.response:return
        w=self.window
        try:
            current=self.response.at(factor)
            scale=w.deformation_custom.value() if w.deformation_mode.currentData()=='custom' else 1.
            points=current.dof_points+scale*current.solution.reshape(-1,3)
            if not np.isfinite(points).all() or np.max(np.abs(w.viewport.normalized(points)))>1e30:
                raise ValueError('Deformation is too large to display; reduce the load or magnification')
        except (ValueError,FloatingPointError) as error:
            self.stats.setText(str(error))
            with QSignalBlocker(self.magnitude):self.magnitude.setValue(self.factor*self.response.magnitude/self.unit_scale)
            with QSignalBlocker(self.slider):self.slider.setValue(round(10000*self.magnitude.value()/self.maximum.value()))
            return
        self.factor=factor
        self.current=current
        w.viewport.load_preview=self.response
        w.viewport.preview_factor=factor
        with QSignalBlocker(w.deformation_action):
            w.viewport.set_data(w.geometry,w.patches,w.mesh,current)
            w.viewport.set_deformation(True)
        w.diagram.result=current
        w.diagram.update()
        limits=self.response.strength_limits
        # Strength edits do not require another elasticity solve.
        material=w.state.inputs.material
        strengths=(getattr(material,'yield_strength',None),getattr(material,'ultimate_tensile_strength',None))
        if strengths!=self.response.strengths:
            self.response.strength_limits=self.response.limits(material)
            self.response.strengths=strengths
            limits=self.response.strength_limits
        markers = tuple((value*self.response.magnitude/self.unit_scale/self.maximum.value(),label,color)
            for key,label,color in (('yield','Yield','#f6bf4f'),('uts','UTS','#ed667e'))
            if (value:=limits[key]) is not None and 0 <= value*self.response.magnitude/self.unit_scale/self.maximum.value() <= 1)
        if markers != self.slider.markers:
            self.slider.markers = markers
            self.slider.update()
        text=[]
        for key,title in (('yield','Estimated first yield'),('uts','UTS tensile reference')):
            value=limits[key]
            text.append(f'{title}: '+('unavailable / not reached' if value is None else
                'already reached by fixed background loads' if value==0 else f'{value*self.response.magnitude/self.unit_scale:.6g}{self.magnitude.suffix()} ({value:.5g}×)'))
        text.append('Point forces and fixed points can cause mesh-dependent local stress peaks.')
        self.limits.setText('\n'.join(text))
        note='Elastic preview; fracture is not simulated.'
        if limits['yield'] is not None and factor>=limits['yield']:note='Elastic extrapolation beyond yield; permanent bending is not simulated.'
        if limits['uts'] is not None and factor>=limits['uts']:note+=' UTS reference reached.'
        self.stats.setText(f'Preview only · {factor:.6g}× analyzed load\nPeak displacement: {np.linalg.norm(current.solution.reshape(-1,3),axis=1).max():.6g} m\n'
            f'Peak von Mises: {current.von_mises.max()/1e6:.6g} MPa\n{note}')
        w.update_report()
        w.update_deformation_controls()
        self.refresh()

    def reset(self,clear_cache=False):
        w=self.window
        was_active=self.active
        if self.pending and w.job.operation=='preview':w.job.invalidate()
        self.pending=False
        self.current=self.response=None
        if clear_cache:self.cache.clear()
        w.viewport.load_preview=None
        if was_active:
            w.viewport.set_data(w.geometry,w.patches,w.mesh,w.result)
            w.viewport.set_deformation(False)
            w.diagram.result=w.result
            w.diagram.update()
            for action in w.tool_actions.values():action.setEnabled(True)
            w.deformation_mode.model().item(w.deformation_mode.findData('auto')).setEnabled(True)
            w.deformation_custom.setRange(1e-9,1e12)
            w.update_deformation_controls()
            w.update_report()
        self.stats.clear()
        self.slider.markers = ()
        self.slider.update()
        for control in (self.slider,self.magnitude,self.maximum,self.reset_button):control.setEnabled(False)
        self.limits.setText('Preview cleared. Prepare a load to inspect its effect.')
