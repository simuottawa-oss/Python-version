"""Geometric line constraints, selection, deletion, and persistence."""
import copy
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import numpy as np
from simuo.parts.sketch_geometry import Sketch
from simuo.parts.part_document import new_document,save_document,open_document
from simuo.parts.feature_document import new_feature_document,save_feature_document,open_feature_document
from simuo.parts.part_assets import load_asset


def rectangle():
    return Sketch([[0,0],[.1,0],[.1,.05],[0,.05]],True,[None]*4,.01)


class ConstraintGeometryTests(unittest.TestCase):
    def test_horizontal_and_vertical_reorient_diagonal_while_retaining_length(self):
        for kind,axis in [('horizontal',1),('vertical',0)]:
            with self.subTest(kind=kind):
                sketch=Sketch([[0,0],[.03,.04]],False,[None])
                sketch.add_constraint(kind,[0])
                self.assertAlmostEqual(sketch.points[1][axis],sketch.points[0][axis])
                self.assertAlmostEqual(sketch.length(0),.05)
                sketch.set_dimension(0,.08)
                self.assertAlmostEqual(sketch.points[1][axis],sketch.points[0][axis])
                self.assertAlmostEqual(sketch.length(0),.08)

    def test_equal_propagates_driving_length_and_keeps_relations(self):
        sketch=rectangle()
        sketch.add_constraint('horizontal',[0,2])
        sketch.add_constraint('vertical',[1,3])
        sketch.set_dimension(0,.1)
        sketch.add_constraint('equal',[0,1,2,3])
        self.assertTrue(all(abs(sketch.length(i)-.1)<1e-8 for i in range(4)))
        sketch.set_dimension(0,.2)
        self.assertTrue(all(abs(sketch.length(i)-.2)<1e-8 for i in range(4)))
        sketch.validate()

    def test_duplicate_relations_are_noop(self):
        sketch=rectangle()
        self.assertTrue(sketch.add_constraint('equal',[0,2]))
        self.assertFalse(sketch.add_constraint('equal',[2,0]))
        self.assertEqual(len(sketch.constraints),1)

    def test_conflicting_relations_and_dimensions_are_transactional(self):
        sketch=Sketch([[0,0],[.05,0]],False,[.05])
        sketch.add_constraint('horizontal',[0])
        previous=sketch.geometry()
        with self.assertRaises(ValueError):
            sketch.add_constraint('vertical',[0])
        self.assertEqual(sketch.geometry(),previous)
        sketch=rectangle()
        sketch.set_dimension(0,.1)
        sketch.set_dimension(1,.05)
        previous=sketch.geometry()
        with self.assertRaises(ValueError):
            sketch.add_constraint('equal',[0,1])
        self.assertEqual(sketch.geometry(),previous)

    def test_delete_preserves_geometry_and_releases_orientation(self):
        sketch=Sketch([[0,0],[.03,.04]],False,[None])
        sketch.add_constraint('horizontal',[0])
        before=copy.deepcopy(sketch.points)
        sketch.remove_constraint(0)
        self.assertEqual(sketch.points,before)
        sketch.add_constraint('vertical',[0])
        self.assertAlmostEqual(sketch.points[1][0],0)
        self.assertAlmostEqual(sketch.length(0),.05)

    def test_invalid_inputs_and_arcs_are_rejected(self):
        sketch=rectangle()
        for kind,indices in [('equal',[0]),('horizontal',[]),('vertical',[99]),('equal',[True,1]),('other',[0])]:
            with self.subTest(kind=kind,indices=indices),self.assertRaises(ValueError):
                sketch.add_constraint(kind,indices)
        arc=Sketch([[0,0]])
        arc.add_arc([.05,.05],[.1,0])
        with self.assertRaisesRegex(ValueError,'straight lines'):
            arc.add_constraint('horizontal',[0])

    def test_malformed_or_unsatisfied_saved_relations_are_rejected(self):
        geometry=rectangle().geometry()
        bad=[None,[{'type':'parallel','segments':[0]}],[{'type':'horizontal','segments':[True]}],
             [{'type':'equal','segments':[0,0]}],[{'type':'horizontal','segments':[0,1]}],
             [{'type':'vertical','segments':[0]}],
             [{'type':'horizontal','segments':[0]}]*2]
        for constraints in bad:
            with self.subTest(constraints=constraints),self.assertRaises(ValueError):
                Sketch.from_geometry(dict(geometry,constraints=constraints))

    def test_segment_deletion_remaps_and_drops_affected_constraints(self):
        sketch=rectangle()
        sketch.add_constraint('horizontal',[0,2])
        sketch.add_constraint('vertical',[1,3])
        sketch.add_constraint('equal',[0,2])
        remaining=sketch.without_segment(0)[0]
        self.assertEqual(len(remaining.constraints),3)
        self.assertTrue(all(r['type']!='equal' for r in remaining.constraints))
        self.assertEqual(sorted(r['segments'][0] for r in remaining.constraints),[0,1,2])
        remaining.validate()
        original=Sketch([[0,0],[.1,0],[.1,.1],[.2,.1]],False,[None]*3)
        original.add_constraint('horizontal',[0,2])
        original.add_constraint('equal',[0,2])
        pieces=original.without_segment(1)
        self.assertEqual(len(pieces),2)
        self.assertEqual([p.constraints for p in pieces],[[{'type':'horizontal','segments':[0]}]]*2)

    def test_draft_and_feature_roundtrip_and_legacy_compatibility(self):
        sketch=rectangle()
        original=sketch.geometry()
        self.assertNotIn('constraints',Sketch.from_geometry(original).geometry())
        sketch.add_constraint('horizontal',[0])
        sketch.add_constraint('vertical',[1])
        sketch.add_constraint('equal',[0,1])
        with tempfile.TemporaryDirectory() as directory:
            path=Path(directory)/'relations.simuOPart'
            save_document(path,new_document(),sketch)
            _,loaded=open_document(path)
            self.assertEqual(loaded.geometry(),sketch.geometry())
            data,model=new_feature_document()
            feature=model.new_sketch({'type':'plane','name':'Top'})
            feature['sketch']=sketch.geometry()
            feature['depth']=.01
            save_feature_document(path,data,model)
            _,loaded_model=open_feature_document(path)
            self.assertEqual(loaded_model.features[0]['sketch']['constraints'],sketch.constraints)
            self.assertGreater(load_asset(path).part.volume,0)


class ConstraintEditorTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        from PySide6.QtWidgets import QApplication
        cls.app=QApplication.instance() or QApplication([])

    def setUp(self):
        from simuo.ui.parts.part_editor import PartEditor
        self.editor=PartEditor()
        self.addCleanup(self.dispose)

    def dispose(self):
        self.editor.dirty=False
        self.editor.close()

    def test_menu_apply_multiple_selection_constraint_list_and_delete_undo(self):
        self.editor.commit(rectangle())
        self.editor.select_segments([0,1])
        self.assertEqual(self.editor.selected_segments(),[0,1])
        menu=next(a.menu() for a in self.editor.menuBar().actions() if a.text()=='Constraints')
        next(a for a in menu.actions() if a.text()=='Make equal').trigger()
        self.assertAlmostEqual(self.editor.sketch.length(0),self.editor.sketch.length(1))
        self.assertEqual(self.editor.constraint_list.count(),1)
        self.assertTrue(self.editor.constraint_list.item(0).text().startswith('Equal'))
        before=copy.deepcopy(self.editor.sketch.points)
        self.editor.constraint_list.setCurrentRow(0)
        self.editor.delete_constraint_button.click()
        self.assertEqual(self.editor.sketch.constraints,[])
        self.assertEqual(self.editor.sketch.points,before)
        self.editor.undo()
        self.assertEqual(len(self.editor.sketch.constraints),1)
        self.editor.redo()
        self.assertEqual(self.editor.sketch.constraints,[])

    def test_ctrl_click_canvas_selects_lines_for_equal(self):
        from PySide6.QtCore import Qt
        from PySide6.QtTest import QTest
        self.editor.commit(rectangle())
        self.editor.canvas.resize(700,600)
        self.editor.canvas.fit()
        self.editor.select_mode()
        for index in (0,1):
            a,b=(np.asarray(self.editor.sketch.points[i]) for i in self.editor.sketch.edges[index])
            point=self.editor.canvas.screen((a+b)/2).toPoint()
            QTest.mouseClick(self.editor.canvas,Qt.LeftButton,Qt.ControlModifier,pos=point)
        self.assertEqual(self.editor.selected_segments(),[0,1])
        self.editor.apply_geometric_constraint('equal')
        self.assertEqual(len(self.editor.sketch.constraints),1)

    def test_delete_dimension_from_constraints_list_keeps_geometry(self):
        self.editor.commit(rectangle())
        self.editor.select_line(0)
        self.editor.length.setValue(150)
        self.editor.apply_dimension()
        self.assertEqual(self.editor.constraint_list.count(),1)
        self.assertTrue(self.editor.constraint_list.item(0).text().startswith('Length'))
        before=copy.deepcopy(self.editor.sketch.points)
        self.editor.constraint_list.setCurrentRow(0)
        self.editor.delete_selected_constraint()
        self.assertIsNone(self.editor.sketch.dimensions[0])
        self.assertEqual(self.editor.sketch.points,before)

    def test_conflict_dialog_keeps_history_and_geometry(self):
        self.editor.commit(Sketch([[0,0],[.05,0]],False,[.05]))
        self.editor.select_line(0)
        self.editor.apply_geometric_constraint('horizontal')
        previous=self.editor.sketch.geometry()
        history=len(self.editor.history)
        with patch('simuo.ui.parts.part_editor.QMessageBox.warning') as message:
            self.editor.apply_geometric_constraint('vertical')
        message.assert_called_once()
        self.assertEqual(self.editor.sketch.geometry(),previous)
        self.assertEqual(len(self.editor.history),history)

    def test_delete_key_in_constraint_list_does_not_delete_geometry(self):
        from PySide6.QtCore import Qt
        from PySide6.QtTest import QTest
        self.editor.commit(rectangle())
        self.editor.select_line(0)
        self.editor.apply_geometric_constraint('horizontal')
        self.editor.show()
        self.app.processEvents()
        self.editor.constraint_list.setCurrentRow(0)
        self.editor.constraint_list.setFocus()
        QTest.keyClick(self.editor.constraint_list,Qt.Key_Delete)
        self.assertEqual(self.editor.sketch.constraints,[])
        self.assertEqual(len(self.editor.sketch.edges),4)

    def test_feature_editor_constraints_save_and_undo(self):
        from simuo.ui.parts.feature_editor import FeaturePartEditor
        editor=FeaturePartEditor()
        try:
            editor.new_sketch()
            editor.commit(rectangle())
            editor.select_segments([0,1])
            editor.apply_geometric_constraint('equal')
            self.assertAlmostEqual(editor.sketch.length(0),editor.sketch.length(1))
            editor.undo()
            self.assertEqual(editor.sketch.constraints,[])
            editor.redo()
            self.assertEqual(len(editor.sketch.constraints),1)
            editor.extrude_active(.01)
            with tempfile.TemporaryDirectory() as directory:
                path=Path(directory)/'constrained part.simuOPart'
                self.assertTrue(editor._save_to(path))
                self.assertTrue(editor.open_path(path))
                self.assertEqual(len(editor.sketch.constraints),1)
        finally:
            editor.dirty=False
            editor.close()

if __name__=='__main__':
    unittest.main()
