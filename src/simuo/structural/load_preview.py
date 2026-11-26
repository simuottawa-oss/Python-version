"""Session-only linear superposition for one load, with P2 display geometry."""
from dataclasses import dataclass, replace
from types import SimpleNamespace
import numpy as np
from scipy.sparse import coo_matrix
from .models import PointLoad, AnalysisResult, all_supports
from .postprocessing import von_mises


def selected_load(setup, identifier):
    for field in ('loads', 'point_loads', 'area_loads'):
        for load in getattr(setup, field):
            if load.identifier == identifier:
                values = np.asarray(load.force if isinstance(load, PointLoad) else load.value, dtype=float)
                magnitude = float(np.linalg.norm(values)) if len(values) == 3 else abs(float(values[0]))
                if not np.isfinite(magnitude) or magnitude <= 0:
                    raise ValueError('Choose a nonzero load so its direction is defined')
                return field, load, magnitude
    raise ValueError('Selected load no longer exists')


def scaled_setup(setup, identifier, factor):
    if not np.isfinite(factor) or factor < 0:
        raise ValueError('Load multiplier must be finite and nonnegative')
    field, load, _ = selected_load(setup, identifier)
    attribute = 'force' if isinstance(load, PointLoad) else 'value'
    value = replace(load, **{attribute: tuple(factor*x for x in getattr(load, attribute))})
    return replace(setup, **{field: tuple(value if item.identifier == identifier else item for item in getattr(setup, field))})


def p2_surface(mesh, basis):
    """Tessellate each quadratic boundary face into four display triangles."""
    vertex_nodes = basis.nodal_dofs[0]//3
    edge_nodes = basis.edge_dofs[0]//3
    lookup = {tuple(sorted(edge)): int(node) for edge, node in zip(basis.mesh.edges.T, edge_nodes)}
    faces = []
    six_nodes = []
    for a, b, c in mesh.boundary_triangles:
        ab, bc, ac = [lookup[tuple(sorted(edge))] for edge in ((a,b),(b,c),(a,c))]
        a, b, c = vertex_nodes[[a,b,c]]
        six_nodes.append((a,b,c,ab,bc,ac))
        faces.extend(((a,ab,ac),(ab,b,bc),(ac,bc,c),(ab,bc,ac)))
    rows = list(vertex_nodes)
    cols = list(range(len(vertex_nodes)))
    values = [1.]*len(rows)
    for edge, node in zip(basis.mesh.edges.T, edge_nodes):
        rows.extend((node,node)); cols.extend(edge); values.extend((.5,.5))
    projection = coo_matrix((values,(rows,cols)), shape=(basis.N//3,len(mesh.points))).tocsr()
    return np.asarray(faces, dtype=int), np.repeat(mesh.boundary_patch,4), projection, np.asarray(six_nodes)


def surface_weights(mesh, six_nodes, point):
    tolerance = np.linalg.norm(np.ptp(mesh.points, axis=0))*1e-8
    for face, nodes in zip(mesh.boundary_triangles, six_nodes):
        vertices = mesh.points[face]
        edges = (vertices[1:]-vertices[0]).T
        uv = np.linalg.lstsq(edges, np.asarray(point)-vertices[0], rcond=None)[0]
        bary = np.r_[1-uv.sum(),uv]
        if min(bary) >= -1e-8 and np.linalg.norm(vertices[0]+edges@uv-point) <= tolerance:
            a,b,c = bary
            return nodes, np.array((a*(2*a-1),b*(2*b-1),c*(2*c-1),4*a*b,4*b*c,4*a*c))
    raise ValueError('Could not anchor a preview annotation on the mesh')


@dataclass
class PreviewResponse:
    reference: AnalysisResult
    fixed: AnalysisResult
    load_id: str
    magnitude: float
    triangles: np.ndarray
    patches: np.ndarray
    projection: object
    anchors: tuple
    strength_limits: dict
    strengths: tuple

    def at(self, factor):
        if not np.isfinite(factor) or factor < 0:
            raise ValueError('Load multiplier must be finite and nonnegative')
        def combine(name):
            first, zero = getattr(self.reference,name), getattr(self.fixed,name)
            if first is None or zero is None:
                return None
            with np.errstate(over='ignore', invalid='ignore'):
                value = zero+factor*(first-zero)
            if not np.isfinite(value).all():
                raise ValueError('Load multiplier is too large; keeping the previous preview')
            return value
        arrays = {name: combine(name) for name in ('displacement','stress','averaged_stress','reactions',
                  'solution','applied_force','applied_moment','root_reaction','beam_moments')}
        arrays['von_mises'] = von_mises(arrays['stress'])
        arrays['averaged_von_mises'] = von_mises(arrays['averaged_stress'])
        if not np.isfinite(arrays['von_mises']).all() or not np.isfinite(arrays['averaged_von_mises']).all():
            raise ValueError('Load multiplier produces nonfinite stress; reduce it')
        reactions = {}
        for key, value in self.reference.support_reactions.items():
            zero = self.fixed.support_reactions[key]
            reactions[key] = {name: value[name].copy() if name == 'origin' else zero[name]+factor*(value[name]-zero[name])
                              for name in value}
        return replace(self.reference, **arrays, support_reactions=reactions)

    def limits(self, material):
        sigma0 = self.fixed.stress
        delta = self.reference.stress-sigma0
        def crossing(strength, tensile=False):
            if strength is None:
                return None
            def peak(factor):
                with np.errstate(over='ignore', invalid='ignore'):
                    tensors = sigma0+factor*delta
                    values = np.maximum(np.linalg.eigvalsh(tensors)[...,-1],0) if tensile else von_mises(tensors)
                return float(values.max())
            if peak(0) >= strength:
                return 0.
            if not np.any(delta):
                return None
            upper = 1.
            for _ in range(60):
                if peak(upper) >= strength:
                    break
                upper *= 2
            else:
                return None
            lower = 0.
            for _ in range(55):
                mid = (lower+upper)/2
                if peak(mid) >= strength: upper = mid
                else: lower = mid
            return upper
        return {'yield': crossing(material.yield_strength),
                'uts': crossing(material.ultimate_tensile_strength, True)}


def prepare_preview(mesh, setup, reference, identifier, progress=lambda text: None):
    from .solver import solve_analysis, make_basis
    from .meshing import point_position
    from .load_regions import area_region
    _, load, magnitude = selected_load(setup, identifier)
    progress('Preparing selected-load response; other loads and gravity remain fixed')
    fixed = solve_analysis(mesh, scaled_setup(setup,identifier,0.), progress=progress)
    basis = make_basis(mesh)
    triangles, patches, projection, six_nodes = p2_surface(mesh,basis)
    anchors = []
    for condition in (*setup.point_loads,*setup.loads,*setup.area_loads,*all_supports(setup)):
        if isinstance(condition, PointLoad) or getattr(condition,'kind',None) == 'fixed_point':
            point = point_position(SimpleNamespace(points=mesh.source_points,triangles=mesh.source_triangles),condition)
        elif condition in setup.area_loads:
            point = area_region(mesh.source_points,mesh.source_triangles,condition).center
        else:
            # A centroid may be off-surface for multi-face selections. Use one
            # actual boundary facet for a surface-attached label in that case.
            face = mesh.selected_boundary(condition.triangles)[0]
            point = mesh.points[mesh.boundary_triangles[face]].mean(axis=0)
        nodes, weights = surface_weights(mesh,six_nodes,point)
        if hasattr(condition,'force'): direction = condition.force
        elif getattr(condition,'kind',None) == 'force': direction = condition.value
        elif getattr(condition,'kind',None) == 'pressure':
            face = mesh.selected_boundary(condition.triangles)[0]
            v = mesh.points[mesh.boundary_triangles[face]]
            direction = -condition.value[0]*np.cross(v[1]-v[0],v[2]-v[0])
        else: direction = (0.,0.,0.)
        anchors.append((condition.identifier,condition.name or getattr(condition,"kind","point force").replace('_',' ').title(),nodes,weights,np.asarray(direction)))
    response = PreviewResponse(reference,fixed,identifier,magnitude,triangles,patches,projection,tuple(anchors),{},
        (setup.material.yield_strength,setup.material.ultimate_tensile_strength))
    progress("Estimating yield and tensile strength reference loads")
    response.strength_limits = response.limits(setup.material)
    return response
