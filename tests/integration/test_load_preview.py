"""Selected-load superposition versus independent solves, including fixed loads."""
from dataclasses import replace
from types import SimpleNamespace
from pathlib import Path
import tempfile
import unittest
import numpy as np
from tests.structural_helpers import native_box, end_selection
from tests.integration.test_point_loads import anchor
from simuo.structural.geometry import load_geometry
from simuo.structural.meshing import generate_mesh
from simuo.structural.models import AnalysisSetup, Material, MeshSettings, SurfaceLoad, AreaLoad, BeamConfiguration
from simuo.structural.solver import solve_analysis
from simuo.structural.load_preview import prepare_preview, scaled_setup, PreviewResponse, selected_load


class LoadPreviewTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        self.g=load_geometry(native_box(self.temp.name,(.2,.2,.2)))
        self.clamp,self.tip=[end_selection(self.g,0,x) for x in (-.1,.1)]

    def test_response_matches_solve_for_each_load_type_and_preserves_reference(self):
        g=self.g
        point=anchor(g,(.1,0,0),(0,-100,0))
        for load,field in ((SurfaceLoad(self.tip,'force',(0,-100,0)),'loads'),(point,'point_loads'),
            (SurfaceLoad(self.tip,'pressure',(-1000.,)),'loads'),
            (AreaLoad(self.tip,point.source_triangle,point.barycentric,.04,'force',(0,-100,0)),'area_loads'),
            (AreaLoad(self.tip,point.source_triangle,point.barycentric,.04,'pressure',(1000.,)),'area_loads')):
            with self.subTest(field=field,kind=getattr(load,'kind','point')):
                mesh=generate_mesh(g,MeshSettings(.09),(point,))
                setup=AnalysisSetup(g.path,g.fingerprint,'m',Material(2e11,.3,7800.,yield_strength=1e5,ultimate_tensile_strength=2e5),
                    mesh.settings,(self.clamp,),gravity=(0,-9.8,0),beam=BeamConfiguration(self.clamp,self.tip),
                    **{field:(load,)})
                # Add an independent background force so tensor combination is
                # tested rather than uniformly multiplying the original solution.
                setup=replace(setup,loads=(*setup.loads,SurfaceLoad(self.tip,'force',(200,0,0))))
                reference=solve_analysis(mesh,setup)
                saved=reference.solution.copy();coordinates=mesh.points.copy()
                response=prepare_preview(mesh,setup,reference,load.identifier)
                for factor in (0.,1.,2.):
                    preview=response.at(factor)
                    exact=solve_analysis(mesh,scaled_setup(setup,load.identifier,factor))
                    for name in ('displacement','stress','averaged_stress','von_mises','reactions','applied_force','beam_moments'):
                        np.testing.assert_allclose(getattr(preview,name),getattr(exact,name),rtol=1e-7,atol=1e-7)
                np.testing.assert_array_equal(reference.solution,saved)
                np.testing.assert_array_equal(mesh.points,coordinates)
                self.assertEqual(len(response.triangles),4*len(mesh.boundary_triangles))
                self.assertGreater(response.triangles.max(),len(mesh.points)-1)
                np.testing.assert_allclose(response.projection@mesh.points,reference.dof_points,atol=1e-12)
                for _,_,nodes,weights,_ in response.anchors:
                    self.assertAlmostEqual(weights.sum(),1.)
                with self.assertRaises(ValueError):response.at(float('inf'))
                with self.assertRaises(ValueError):response.at(-1.)
                for key,strength in (('yield',1e5),('uts',2e5)):
                    crossing=response.strength_limits[key]
                    if crossing is not None and crossing>0:
                        tensor=response.at(crossing).stress
                        peak=response.at(crossing).von_mises.max() if key=='yield' else np.linalg.eigvalsh(tensor)[...,-1].max()
                        self.assertAlmostEqual(peak/strength,1.,places=7)

    def test_zero_load_and_missing_load_are_rejected(self):
        g=self.g
        load=SurfaceLoad(self.tip,'force',(0,0,0))
        setup=AnalysisSetup(g.path,g.fingerprint,'m',Material(2e11,.3),MeshSettings(.1),loads=(load,))
        with self.assertRaisesRegex(ValueError,'nonzero'):selected_load(setup,load.identifier)
        with self.assertRaisesRegex(ValueError,'no longer exists'):selected_load(setup,'missing')

    def test_strength_reference_background_exceedance_and_compression(self):
        def response(zero,reference):
            return PreviewResponse(SimpleNamespace(stress=np.array([[np.diag(reference)]])),
                SimpleNamespace(stress=np.array([[np.diag(zero)]])),'id',1.,None,None,None,(),{},(None,None))
        strengths=SimpleNamespace(yield_strength=100.,ultimate_tensile_strength=200.)
        limits=response((20,0,0),(60,0,0)).limits(strengths)
        self.assertAlmostEqual(limits['yield'],2.)
        self.assertAlmostEqual(limits['uts'],4.5)
        self.assertEqual(response((120,0,0),(160,0,0)).limits(strengths)['yield'],0.)
        self.assertIsNone(response((0,0,0),(-50,0,0)).limits(strengths)['uts'])
        self.assertEqual(response((0,0,0),(50,0,0)).limits(SimpleNamespace(yield_strength=None,ultimate_tensile_strength=None)),{'yield':None,'uts':None})
