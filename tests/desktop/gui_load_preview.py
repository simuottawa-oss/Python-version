"""Real OpenGL selected-load preview: P2 shape, slider and session isolation."""
from unittest.mock import patch
import sys,traceback
import numpy as np
from PySide6.QtCore import Qt
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication
from simuo.rendering.context import configure_opengl
from tests.integration.test_load_preview_workflow import PreviewWorkflowTests


def main():
    configure_opengl()
    app=QApplication([])
    PreviewWorkflowTests.app=app
    fixture=PreviewWorkflowTests('test_slider_is_ephemeral_and_deformation_uses_quadratic_nodes')
    errors=[]
    def error_hook(*args):
        errors.append(''.join(traceback.format_exception(*args)))
        traceback.print_exception(*args)
    sys.excepthook=error_hook
    fixture.setUp()
    w=fixture.w;p=w.load_preview_panel
    w.show();w.select_item('results')
    try:
        QTest.qWait(300)
        scroll=w.properties.widget(w.pages['results'])
        scroll.ensureWidgetVisible(p.prepare_button)
        reference=w.result;inputs=w.state.inputs;mesh=w.mesh
        before=reference.solution.copy()
        QTest.mouseClick(p.prepare_button,Qt.LeftButton)
        fixture.wait()
        assert p.active and w.viewport.isValid()
        scroll.ensureWidgetVisible(p.slider)
        with patch.object(w.job,'start',wraps=w.job.start) as start:
            p.slider.setValue(8000)
            QTest.qWait(80)
            p.slider.setFocus()
            QTest.keyClick(p.slider,Qt.Key_Right)
            QTest.qWait(100)
            start.assert_not_called()
        assert w.result is reference and w.mesh is mesh and w.state.inputs==inputs
        np.testing.assert_array_equal(reference.solution,before)
        frame=w.viewport.grabFramebuffer()
        assert w.viewport.draw_count==len(p.response.triangles)*3
        assert frame.save('/tmp/simuo-load-preview-frame.png')
        assert 'Estimated first yield' in p.limits.text()
        assert 'UTS' in p.limits.text()
        w.deformation_mode.setCurrentIndex(w.deformation_mode.findData('custom'))
        w.deformation_custom.setValue(1000.)
        w.deformation_scale_changed()
        w.viewport.frame_all()
        QTest.qWait(100)
        assert np.isclose(w.viewport.deformation_scale,1000.)
        assert w.grab().save('/tmp/simuo-load-preview-workspace.png')
        QTest.keyClick(w.viewport,Qt.Key_Escape)
        QTest.qWait(50)
        assert not p.active and w.viewport.result is reference
        assert not errors, '\n'.join(errors)
        print('PASS load-preview worker, slider without solves, P2 OpenGL geometry, magnitude labels, magnification, Escape and unchanged design',flush=True)
    finally:
        fixture.doCleanups()
    return 0


if __name__=='__main__':raise SystemExit(main())
