"""Preview preparation uses a worker; slider changes never run or edit a design."""
from pathlib import Path
import tempfile,time
from unittest.mock import patch,Mock
import unittest
import numpy as np
from PySide6.QtWidgets import QApplication
from PySide6.QtCore import QSettings
from tests.structural_helpers import native_box,end_selection
from simuo.structural.geometry import load_geometry
from simuo.structural.models import *
from simuo.structural.meshing import generate_mesh
from simuo.structural.solver import solve_analysis
from simuo.materials import MaterialDefinition
from simuo.editor.structural_state import StructuralInputs
from simuo.ui.structural_window import StructuralWindow


class PreviewWorkflowTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):cls.app=QApplication.instance() or QApplication([])

    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        g=load_geometry(native_box(self.temp.name,(.2,.2,.2)))
        mesh=generate_mesh(g,MeshSettings(.09))
        a,b=[end_selection(g,0,x) for x in (-.1,.1)]
        material=MaterialDefinition('Test alloy',2e11,.3,7800.,yield_strength=1e5,ultimate_tensile_strength=2e5)
        load=SurfaceLoad(b,'force',(0,-100,0),name='Tip force')
        support=SupportCondition('fixed_face',a,name='Clamp')
        settings=QSettings(str(Path(self.temp.name)/'layout.ini'),QSettings.IniFormat)
        with patch('simuo.ui.structural_window.QSettings',return_value=settings):w=StructuralWindow()
        self.w=w;w.confirm_unsaved=Mock(return_value=True);w.error=Mock();self.addCleanup(w.close)
        w.geometry=g;w.patches=mesh.patches
        w.state.reset(StructuralInputs(material=material,support_conditions=(support,),loads=(load,),mesh_size=.09))
        w.mesh=mesh;w.result=solve_analysis(mesh,w.setup());w.refresh_view()

    def wait(self):
        deadline=time.monotonic()+30
        while self.w.job.running and time.monotonic()<deadline:
            self.app.processEvents();time.sleep(.01)
        self.assertFalse(self.w.job.running)
        self.w.error.assert_not_called()

    def test_slider_is_ephemeral_and_deformation_uses_quadratic_nodes(self):
        w=self.w;p=w.load_preview_panel
        original=w.result;snapshot=w.state.inputs;mesh=w.mesh;undo=w.state.undo_stack.count()
        p.prepare();self.wait()
        self.assertTrue(p.active)
        self.assertEqual(w.deformation_mode.currentData(),'true')
        self.assertTrue(w.viewport.deformation_enabled)
        self.assertIsNone(w.viewport.pick_surface(200,160))
        self.assertIsNotNone(w.viewport.pick_surface(w.viewport.width()/2,w.viewport.height()/2,inspection=True))
        self.assertFalse(w.tool_actions['force'].isEnabled())
        self.assertEqual({label for _,label,_ in p.slider.markers},{'Yield','UTS'})
        with patch.object(w.job,'start',wraps=w.job.start) as start:
            p.magnitude.setValue(200.);p.number_changed()
            self.assertAlmostEqual(p.factor,2.)
            start.assert_not_called()
        np.testing.assert_allclose(p.current.displacement,2*original.displacement,atol=1e-14)
        self.assertIs(w.result,original);self.assertIs(w.mesh,mesh)
        self.assertEqual(w.state.inputs,snapshot);self.assertEqual(w.state.undo_stack.count(),undo)
        self.assertEqual(len(w.viewport.display_points()),len(original.dof_points))
        w.deformation_mode.setCurrentIndex(w.deformation_mode.findData('custom'))
        w.deformation_custom.setValue(100.);w.deformation_scale_changed()
        np.testing.assert_allclose(w.viewport.display_points(),original.dof_points+100*p.current.solution.reshape(-1,3))
        w.cancel_placement()
        self.assertFalse(p.active);self.assertIs(w.viewport.result,original)
        self.assertFalse(w.viewport.deformation_enabled)
        self.assertTrue(w.tool_actions['force'].isEnabled())
        with patch.object(w.job,'start',wraps=w.job.start) as start:
            p.prepare();start.assert_not_called()
        self.assertTrue(p.active)

    def test_edit_cancels_preparation_and_discards_cache(self):
        w=self.w;p=w.load_preview_panel
        p.prepare()
        self.assertEqual(w.job.operation,'preview')
        w.state.edit('Change force',loads=(__import__('dataclasses').replace(w.loads[0],value=(0,-200,0)),))
        self.assertFalse(w.job.running);self.assertFalse(p.active);self.assertFalse(p.cache)
        self.assertIsNone(w.result)
