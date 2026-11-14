"""A planar outline with straight edges and circular arcs, in meters."""
from dataclasses import dataclass, field
import copy
import math

import numpy as np

EPS = 1e-9


def radius_bulge(start, end, radius, previous):
    """Compute arc bulge for a new radius while preserving the old side and minor/major
    branch with fixed endpoints.

    Args:
        start (sequence): Arc start [x, y] in sketch metres.
        end (sequence): Arc end [x, y] in sketch metres.
        radius (float): Positive arc/circle radius in metres.
        previous (float): Existing signed bulge used to retain side and minor/major
            branch.

    Returns:
        float: Signed tan(sweep/4); an impossible radius raises ValueError.
    """
    chord = math.dist(start, end)
    if radius < chord/2 - 1e-12:
        raise ValueError(f"Radius must be at least {chord/2*1000:.4f} mm for these endpoints")
    ratio = min(1.0, chord/(2*radius))
    minor = ratio/(1 + math.sqrt(max(0.0, 1-ratio*ratio)))
    bulge = 1/minor if abs(previous) > 1+1e-12 else minor
    return math.copysign(bulge, previous)


def three_point_bulge(start, through, end):
    """Fit an arc through three distinct non-collinear planar points.

    Args:
        start (sequence): Arc start [x, y] in sketch metres.
        through (sequence): Distinct point [x, y] on the intended arc, in metres.
        end (sequence): Arc end [x, y] in sketch metres.

    Returns:
        float: Signed tan(sweep/4) for the arc passing through the middle point; invalid
        points raise ValueError.
    """
    a, m, b = (np.asarray(p, dtype=float) for p in (start, through, end))
    u, v = m-a, b-a
    determinant = 2*(u[0]*v[1]-u[1]*v[0])
    if min(math.dist(start, through), math.dist(through, end), math.dist(start, end)) < 1e-6:
        raise ValueError("Choose three distinct points for an arc")
    if abs(determinant) < 1e-10*np.linalg.norm(u)*np.linalg.norm(v):
        raise ValueError("Arc points cannot lie on a straight line")
    center = a + np.array([(np.dot(u,u)*v[1]-np.dot(v,v)*u[1])/determinant,
                           (u[0]*np.dot(v,v)-v[0]*np.dot(u,u))/determinant])
    first, middle, last = (math.atan2(*(p-center)[::-1]) for p in (a,m,b))
    sweep = (last-first) % math.tau
    if (middle-first) % math.tau > sweep:
        sweep -= math.tau
    return math.tan(sweep/4)


def cross(a,b,c):
    """Compute the signed 2D cross product of vectors AB and AC.

    Args:
        a (sequence): Planar [x, y] point; segment endpoints are paired in argument
            order.
        b (sequence): Planar [x, y] point; segment endpoints are paired in argument
            order.
        c (sequence): Planar [x, y] point; segment endpoints are paired in argument
            order.

    Returns:
        float: Twice the signed triangle area; positive for counterclockwise points.
    """
    return (b[0]-a[0])*(c[1]-a[1])-(b[1]-a[1])*(c[0]-a[0])


def intersects(a,b,c,d):
    """Test whether two planar segments cross, touch, or overlap within tolerance.

    Args:
        a (sequence): Planar [x, y] point; segment endpoints are paired in argument
            order.
        b (sequence): Planar [x, y] point; segment endpoints are paired in argument
            order.
        c (sequence): Planar [x, y] point; segment endpoints are paired in argument
            order.
        d (sequence): Planar [x, y] point; segment endpoints are paired in argument
            order.

    Returns:
        bool: True if segments AB and CD intersect.
    """
    tolerance = 1e-12*max(math.dist(a,b),math.dist(c,d),1e-6)
    def on(p,q,r):
        """Test whether a point lies on a segment within the enclosing intersection
        tolerance.

        Args:
            p (sequence): Planar [x, y] point; segment endpoints are paired in argument
                order.
            q (sequence): Planar [x, y] point; segment endpoints are paired in argument
                order.
            r (sequence): Planar [x, y] point; segment endpoints are paired in argument
                order.

        Returns:
            bool: True if R is collinear with and inside segment PQ.
        """
        return abs(cross(p,q,r)) < tolerance and all(min(p[i],q[i])-EPS <= r[i] <= max(p[i],q[i])+EPS for i in (0,1))
    p,q,r,s = cross(a,b,c),cross(a,b,d),cross(c,d,a),cross(c,d,b)
    return (p*q < 0 and r*s < 0) or on(a,b,c) or on(a,b,d) or on(c,d,a) or on(c,d,b)


@dataclass
class Sketch:
    points: list = field(default_factory=list)
    closed: bool = False
    dimensions: list = field(default_factory=list)
    thickness: float = .01
    arcs: list = field(default_factory=list)  # None or {"bulge": tan(signed sweep/4)} per edge
    constraints: list = field(default_factory=list)

    @classmethod
    def circle(cls, center, radius, thickness=.01):
        """Construct and validate an editable closed circle from two exact semicircular
        arcs.

        Args:
            center (sequence): Circle center [x, y] in sketch metres.
            radius (float): Positive arc/circle radius in metres.
            thickness (float): Prism thickness in metres; defaults to 0.01 m.

        Returns:
            Sketch: New circle with undimensioned arcs; invalid radius or coordinates
            raise ValueError.
        """
        if not math.isfinite(radius) or not 1e-6 <= radius <= 1e6:
            raise ValueError("Circle radius must be between 0.001 mm and 1,000,000 m")
        x, y = center
        sketch = cls([[x+radius, y], [x-radius, y]], True,
                     [None, None], thickness, [{"bulge":1.}, {"bulge":1.}])
        sketch.validate()
        return sketch

    @property
    def is_circle(self):
        """Recognize the two-semicircle representation created for a circle.

        Returns:
            bool: True for a closed two-point outline with two positive unit bulges.
        """
        return (self.closed and len(self.points)==2 and len(self.arcs)==2
                and all(arc is not None and abs(arc["bulge"]-1.)<1e-12 for arc in self.arcs))

    @property
    def edges(self):
        """Enumerate consecutive endpoint indices, adding the last-to-first edge for a
        closed outline.

        Returns:
            list: Pairs of zero-based point indices.
        """
        return [(i,(i+1)%len(self.points)) for i in range(len(self.points) if self.closed else max(0,len(self.points)-1))]

    def length(self,index):
        """Measure a straight segment or the full curved length of an arc.

        Args:
            index (int): Zero-based segment index in sketch edge order.

        Returns:
            float: Segment length in metres, rather than the arc's driving radius.
        """
        a,b = self.edges[index]
        if self.is_arc(index):
            _,radius,sweep = self.arc_parameters(index)
            return radius*abs(sweep)
        return math.dist(self.points[a],self.points[b])

    def is_arc(self, index):
        """Check whether an edge has a stored circular-arc definition.

        Args:
            index (int): Zero-based segment index in sketch edge order.

        Returns:
            bool: True when the segment has non-null arc data.
        """
        return bool(self.arcs) and self.arcs[index] is not None

    def arc_parameters(self, index):
        """Recover an arc's circle and sweep from its endpoints and bulge.

        Args:
            index (int): Zero-based segment index in sketch edge order.

        Returns:
            tuple: Center [x, y] in metres, radius in metres, and signed sweep in
            radians.
        """
        a, b = (np.asarray(self.points[i], dtype=float) for i in self.edges[index])
        bulge = self.arcs[index]["bulge"]
        delta = b-a
        center = (a+b)/2 + np.array([-delta[1],delta[0]])*(1-bulge*bulge)/(4*bulge)
        radius = float(np.linalg.norm(delta))*(1+bulge*bulge)/(4*abs(bulge))
        return center.tolist(), radius, 4*math.atan(bulge)

    def dimension_value(self, index):
        """Measure the quantity used by a driving dimension.

        Args:
            index (int): Zero-based segment index in sketch edge order.

        Returns:
            float: Line length or arc radius, in metres.
        """
        return self.arc_parameters(index)[1] if self.is_arc(index) else self.length(index)

    def segment_points(self, index):
        """Sample a segment, tessellating arcs at angular steps of at most five degrees.

        Args:
            index (int): Zero-based segment index in sketch edge order.

        Returns:
            list: XY point lists in metres, including both exact endpoints.
        """
        a,b = (self.points[i] for i in self.edges[index])
        if not self.is_arc(index):
            return [list(a),list(b)]
        center,radius,sweep = self.arc_parameters(index)
        start = math.atan2(a[1]-center[1], a[0]-center[0])
        steps = max(2, math.ceil(abs(sweep)/math.radians(5)))
        points = [[center[0]+radius*math.cos(start+sweep*i/steps),
                   center[1]+radius*math.sin(start+sweep*i/steps)] for i in range(steps+1)]
        points[0],points[-1] = list(a),list(b)
        return points

    @property
    def outline_points(self):
        """Collect the tessellated boundary in drawing order without repeating a closed
        outline's first point.

        Returns:
            list: Independent XY coordinate lists in metres.
        """
        if not self.edges:
            return copy.deepcopy(self.points)
        result = []
        for index in range(len(self.edges)):
            result.extend(self.segment_points(index)[:-1])
        if not self.closed:
            result.append(list(self.points[-1]))
        return result

    def _polygon(self):
        """Replace curves with sampled straight edges for area and triangulation
        calculations.

        Returns:
            Sketch: Undimensioned polygon approximation retaining closure and thickness.
        """
        return Sketch(self.outline_points, self.closed, [None]*len(self.outline_points), self.thickness)

    @property
    def signed_area(self):
        """Compute oriented area, using a tessellated polygon for curves.

        Returns:
            float: Signed square metres; positive for counterclockwise outlines and zero
            for drafts.
        """
        if any(self.arcs):
            return self._polygon().signed_area
        return sum(self.points[a][0]*self.points[b][1]-self.points[b][0]*self.points[a][1]
                   for a,b in self.edges)/2 if self.closed else 0

    @property
    def centroid(self):
        """Compute the polygon area centroid, approximating curves by tessellation.

        Returns:
            tuple: XY centroid in metres, or (0, 0) for zero area.
        """
        if any(self.arcs):
            return self._polygon().centroid
        area = self.signed_area
        if not area:
            return (0,0)
        terms = [(self.points[a],self.points[b],self.points[a][0]*self.points[b][1]-self.points[b][0]*self.points[a][1])
                 for a,b in self.edges]
        return tuple(sum((a[i]+b[i])*v for a,b,v in terms)/(6*area) for i in (0,1))

    def validate(self):
        """Check coordinate limits, thickness, topology, dimensions, curves, and geometric
        relations without solving them.

        Returns:
            None. Raises ValueError if geometry is malformed, self-intersecting, or
            violates a constraint.
        """
        if type(self.closed) is not bool or not isinstance(self.points,list) or len(self.points)>256:
            raise ValueError("A sketch supports at most 256 points and a boolean closed flag")
        for point in self.points:
            if not isinstance(point,(tuple,list)) or len(point)!=2 or any(isinstance(v,bool) or not isinstance(v,(float,int)) or not math.isfinite(v) or abs(v)>1e6 for v in point):
                raise ValueError("Sketch points must have two finite coordinates within ±1,000,000 meters")
        if not isinstance(self.thickness,(float,int)) or isinstance(self.thickness,bool) or not math.isfinite(self.thickness) or not 1e-6 <= self.thickness <= 1e6:
            raise ValueError("Thickness must be between 0.001 mm and 1,000,000 m")
        if self.closed and len(self.points)<3 and not (len(self.points)==2 and isinstance(self.arcs,list) and any(self.arcs)):
            raise ValueError("A face needs at least three points")
        if len(self.dimensions)!=len(self.edges):
            raise ValueError("Every segment must have a dimension entry (line length or arc radius)")
        if not isinstance(self.arcs,list) or (self.arcs and len(self.arcs)!=len(self.edges)):
            raise ValueError("Arcs must contain one entry per segment")
        for arc in self.arcs:
            if arc is not None:
                if not isinstance(arc,dict) or set(arc)!={"bulge"}:
                    raise ValueError("An arc must define its bulge")
                value = arc["bulge"]
                if isinstance(value,bool) or not isinstance(value,(int,float)) or not math.isfinite(value) or not 1e-6 <= abs(value) <= 1e6:
                    raise ValueError("Arc curvature is outside the supported range")
        self._validate_constraints()
        for i,(a,b) in enumerate(self.edges):
            if math.dist(self.points[a], self.points[b])<1e-6:
                raise ValueError("Segment endpoints must be at least 0.001 mm apart")
            if self.is_arc(i):
                _,radius,_ = self.arc_parameters(i)
                if not math.isfinite(radius) or not 1e-6 <= radius <= 1e6:
                    raise ValueError("Arc radius is outside the supported range")
            if self.length(i)<1e-6:
                raise ValueError("Lines must be at least 0.001 mm long")
            target = self.dimensions[i]
            if target is not None:
                if isinstance(target,bool) or not isinstance(target,(float,int)) or not math.isfinite(target) or target<1e-6:
                    raise ValueError("A driving length must be positive and at least 0.001 mm")
                if abs(self.dimension_value(i)-target)>max(1e-8,target*1e-7):
                    raise ValueError("The sketch does not satisfy its driving dimensions")
            for j,(c,d) in enumerate(self.edges[:i]):
                if not any(self.arcs) and len({a,b,c,d})==4 and intersects(self.points[a],self.points[b],self.points[c],self.points[d]):
                    raise ValueError("Lines cannot cross or overlap")
        if any(self.arcs):
            outline = self.outline_points
            if len(outline)>4096:
                raise ValueError("The curved outline is too detailed; use fewer arcs")
            edges = [(i,(i+1)%len(outline)) for i in range(len(outline) if self.closed else len(outline)-1)]
            for i,(a,b) in enumerate(edges):
                for c,d in edges[:i]:
                    if len({a,b,c,d})==4 and intersects(outline[a],outline[b],outline[c],outline[d]):
                        raise ValueError("Sketch segments cannot cross or overlap")
        if self.closed and abs(self.signed_area)<1e-10:
            raise ValueError("The enclosed outline must have a nonzero area")
        for relation in self.constraints:
            kind,segments = relation["type"],relation["segments"]
            first = self.length(segments[0])
            for index in segments:
                a,b = (self.points[i] for i in self.edges[index])
                error = abs(b[1]-a[1]) if kind=="horizontal" else abs(b[0]-a[0]) if kind=="vertical" else abs(self.length(index)-first)
                if error>max(1e-8,first*1e-7):
                    raise ValueError(f"The sketch does not satisfy its {kind} constraint")

    def _validate_constraints(self):
        """Check relation structure, supported kinds, unique indices, and straight-edge
        references.

        Returns:
            None. Raises ValueError for malformed or duplicate relations; does not solve
            geometry.
        """
        if not isinstance(self.constraints,list) or len(self.constraints)>1024:
            raise ValueError("Constraints must be a list of at most 1024 relations")
        seen = set()
        for relation in self.constraints:
            if not isinstance(relation,dict) or set(relation)!={"type","segments"}:
                raise ValueError("Each constraint needs a type and segment indices")
            kind,segments = relation["type"],relation["segments"]
            if kind not in ("horizontal","vertical","equal") or not isinstance(segments,list):
                raise ValueError("Supported line constraints are horizontal, vertical and equal")
            if (len(segments)<2 if kind=="equal" else len(segments)!=1):
                raise ValueError("Equal needs at least two lines; Horizontal/Vertical need one line")
            if any(type(i) is not int or not 0<=i<len(self.edges) for i in segments) or len(set(segments))!=len(segments):
                raise ValueError("Constraint segment indices must be unique existing edges")
            if any(self.is_arc(i) for i in segments):
                raise ValueError("Horizontal, Vertical and Equal apply to straight lines only")
            key = (kind,tuple(sorted(segments)))
            if key in seen:
                raise ValueError("Duplicate sketch constraint")
            seen.add(key)

    def add_constraint(self,kind,segments):
        """Solve a new horizontal, vertical, or equal relation on a copy, then commit only
        a valid result.

        Args:
            kind (str): Supported relation kind: horizontal, vertical, or equal.
            segments (iterable): Zero-based straight-edge indices affected by a
                relation.

        Returns:
            bool: True if a relation was added, False if already present; conflicts
            raise ValueError without committing the candidate.
        """
        if kind not in ("horizontal","vertical","equal"):
            raise ValueError("Choose Horizontal, Vertical or Equal")
        if not segments:
            raise ValueError("Select a straight line first")
        if any(type(i) is not int for i in segments):
            raise ValueError("Select valid straight lines")
        segments = sorted(set(segments))
        if kind=="equal" and len(segments)<2:
            raise ValueError("Ctrl-click at least two straight lines to make them Equal")
        additions = ([{"type":kind,"segments":segments}] if kind=="equal" else
                     [{"type":kind,"segments":[i]} for i in segments])
        candidate = copy.deepcopy(self)
        existing = {(r["type"],tuple(sorted(r["segments"]))) for r in self.constraints}
        additions = [r for r in additions if (r["type"],tuple(r["segments"])) not in existing]
        if not additions:
            return False
        if kind in ("horizontal","vertical"):
            opposite = "vertical" if kind=="horizontal" else "horizontal"
            blocked = {r["segments"][0] for r in self.constraints if r["type"]==opposite}
            if blocked.intersection(segments):
                raise ValueError(f"A selected line already has a {opposite} constraint. Delete it before making the line {kind}.")
        candidate.constraints.extend(additions)
        candidate._validate_constraints()
        candidate._solve(preserve_axes=kind=="equal", orient=additions if kind!="equal" else ())
        candidate.validate()
        self.points,self.arcs,self.constraints = candidate.points,candidate.arcs,candidate.constraints
        return True

    def remove_constraint(self,index):
        """Remove one geometric relation without moving the outline.

        Args:
            index (int): Zero-based relation index in the constraints list.

        Returns:
            None. Mutates constraints; an invalid index raises ValueError.
        """
        if type(index) is not int or not 0<=index<len(self.constraints):
            raise ValueError("Select a constraint to delete")
        self.constraints.pop(index)

    def add_point(self, point):
        """Append an undimensioned straight segment to an open outline, committing only
        after validation.

        Args:
            point (sequence): New endpoint [x, y] in sketch metres.

        Returns:
            None. Updates points and segment metadata; invalid geometry raises
            ValueError.
        """
        if self.closed:
            raise ValueError("The face is closed. Start a new sketch to draw another outline.")
        candidate = copy.deepcopy(self)
        candidate.points.append(list(point))
        if len(candidate.points)>1:
            candidate.dimensions.append(None)
            if candidate.arcs:
                candidate.arcs.append(None)
        candidate.validate()
        self.points,self.dimensions,self.arcs = candidate.points,candidate.dimensions,candidate.arcs

    def without_segment(self, index):
        """Remove an edge into independent open outlines, preserving surviving geometry and
        remapping constraints.

        Args:
            index (int): Zero-based segment index in sketch edge order.

        Returns:
            list: One or two validated Sketch objects, or an empty Sketch when no edges
            remain; this sketch is unchanged.
        """
        if not 0 <= index < len(self.edges):
            raise ValueError("Select a line or arc to delete")
        if self.closed:
            points = [(index+1+i) % len(self.points) for i in range(len(self.points))]
            segments = points[:-1]
            groups = [(points, segments)]
        else:
            groups = [
                (list(range(index+1)), list(range(index))),
                (list(range(index+1, len(self.points))), list(range(index+1, len(self.edges)))),
            ]
        result = []
        for points, segments in groups:
            if not segments:
                continue
            sketch = Sketch(
                [copy.deepcopy(self.points[i]) for i in points], False,
                [self.dimensions[i] for i in segments], self.thickness,
                [copy.deepcopy(self.arcs[i]) for i in segments] if self.arcs else [],
            )
            remap = {old:new for new,old in enumerate(segments)}
            for relation in self.constraints:
                surviving = [remap[i] for i in relation["segments"] if i in remap]
                if len(surviving)>=(2 if relation["type"]=="equal" else 1):
                    sketch.constraints.append({"type":relation["type"],"segments":surviving})
            sketch.validate()
            result.append(sketch)
        return result or [Sketch(thickness=self.thickness)]

    def add_arc(self, through, end, close=False):
        """Append a three-point arc from the last endpoint, optionally closing at the first
        point. Commit only after validation.

        Args:
            through (sequence): Distinct point [x, y] on the intended arc, in metres.
            end (sequence): Arc end [x, y] in sketch metres.
            close (bool): End at the first sketch point and close the outline when True.

        Returns:
            None. Updates geometry and segment metadata; invalid arcs or closure raise
            ValueError.
        """
        if self.closed or not self.points:
            raise ValueError("Choose an arc start point in an open sketch")
        candidate = copy.deepcopy(self)
        bulge = three_point_bulge(self.points[-1], through, end)
        if not candidate.arcs:
            candidate.arcs = [None]*len(candidate.edges)
        if close:
            if list(end)!=list(candidate.points[0]):
                raise ValueError("A closing arc must end at the first point")
            candidate.closed = True
        else:
            candidate.points.append(list(end))
        candidate.arcs.append({"bulge":bulge})
        candidate.dimensions.append(None)
        candidate.validate()
        self.points,self.closed,self.dimensions,self.arcs = candidate.points,candidate.closed,candidate.dimensions,candidate.arcs

    def close(self):
        """Close an open outline with an undimensioned straight edge after validation.

        Returns:
            None. Updates closure and metadata; an already closed sketch is unchanged.
        """
        if self.closed:
            return
        candidate = copy.deepcopy(self)
        candidate.closed = True
        candidate.dimensions.append(None)
        if candidate.arcs:
            candidate.arcs.append(None)
        candidate.validate()
        self.closed,self.dimensions,self.arcs = True,candidate.dimensions,candidate.arcs

    def set_dimension(self,index,length):
        """Apply a driving line length or arc radius on a copy, solve affected geometry,
        and commit a valid result. A circle's radius edit resizes the whole circle.

        Args:
            index (int): Zero-based segment index in sketch edge order.
            length (float): Driving line length or arc radius in metres.

        Returns:
            None. Updates points, arcs, and/or dimensions; conflicts raise ValueError
            without committing the candidate.
        """
        if not 0 <= index < len(self.edges):
            raise ValueError("Select a line first")
        if not math.isfinite(length) or length<1e-6 or length>1e6:
            raise ValueError("Enter a length from 0.001 mm to 1,000,000 m")
        candidate = copy.deepcopy(self)
        candidate.dimensions[index] = length
        if self.is_circle:
            center, radius, _ = self.arc_parameters(0)
            candidate.points = [[center[axis]+(point[axis]-center[axis])*length/radius
                                 for axis in (0,1)] for point in self.points]
            candidate.dimensions = [length if i==index or target is not None else None
                                    for i,target in enumerate(self.dimensions)]
            candidate.validate()
            self.points,self.dimensions = candidate.points,candidate.dimensions
            return
        if self.is_arc(index):
            a,b = self.edges[index]
            candidate.arcs[index]["bulge"] = radius_bulge(self.points[a],self.points[b],length,self.arcs[index]["bulge"])
            candidate.validate()
            self.arcs,self.dimensions = candidate.arcs,candidate.dimensions
            return
        candidate._solve()
        candidate.validate()
        self.points,self.dimensions,self.arcs = candidate.points,candidate.dimensions,candidate.arcs

    def move_point(self, index, position):
        """Move one endpoint while keeping other endpoints fixed and respecting explicit
        relations and dimensions. Commit only a validated solution.

        Args:
            index (int): Zero-based endpoint index in the points list.
            position (list or tuple): Requested endpoint [x, y] in metres; the solver
                can restrict motion to satisfy constraints.

        Returns:
            None. Updates points and arcs when movement is possible; invalid positions
            or conflicts raise ValueError.
        """
        if type(index) is not int or not 0 <= index < len(self.points):
            raise ValueError("Select a sketch point to move")
        if not isinstance(position, (list, tuple)) or len(position) != 2 or any(
            isinstance(v, bool) or not isinstance(v, (int, float)) or not math.isfinite(v) or abs(v)>1e6
            for v in position
        ):
            raise ValueError("Choose a finite point within the sketch coordinate limits")
        candidate = copy.deepcopy(self)
        candidate._solve(preserve_axes=False, drag=(index, position))
        candidate.validate()
        if math.dist(candidate.points[index], self.points[index]) < 1e-10:
            return
        self.points, self.arcs = candidate.points, candidate.arcs

    def _solve(self,preserve_axes=True,orient=(),drag=None):
        """Solve relations and dimensions in this candidate using iterative least squares.
        Call on a copy when transactional edits are required.

        Args:
            preserve_axes (bool): Retain existing incidental horizontal/vertical
                alignment when solving.
            orient (iterable): Newly added horizontal/vertical relations used to seed
                endpoint positions.
            drag (tuple, optional): (point index, target XY metres); restrict solving to
                that endpoint, or None for ordinary dimension solving.

        Returns:
            None. Mutates candidate points and driving arc bulges; unresolved
            constraints raise ValueError.
        """
        self._validate_constraints()
        initial = np.asarray(self.points,dtype=float)
        points = initial.copy()
        if drag is not None:
            points[drag[0]] = drag[1]
        for relation in orient:
            axis = 0 if relation["type"]=="horizontal" else 1
            a,b = self.edges[relation["segments"][0]]
            delta = points[b]-points[a]
            direction = np.zeros(2)
            direction[axis] = 1 if delta[axis]>=0 else -1
            points[b] = points[a]+direction*np.linalg.norm(delta)
        # Preserve existing horizontal/vertical relationships, all previous
        # driving dimensions, and the first point. Other vertices may move.
        axes = []
        for i,(a,b) in enumerate(self.edges):
            delta = initial[b]-initial[a]
            axes.append(None if self.is_arc(i) or not preserve_axes else 0 if abs(delta[0])<EPS else 1 if abs(delta[1])<EPS else None)
        for _ in range(150):
            residual,jacobian = [],[]
            def length_row(index):
                """Form the current line length and its derivatives for the solver's
                working points.

                Args:
                    index (int): Zero-based segment index in sketch edge order.

                Returns:
                    tuple: Scalar length and flat Jacobian row; a collapsed edge raises
                    ValueError.
                """
                a,b = self.edges[index]
                delta = points[b]-points[a]
                current = np.linalg.norm(delta)
                if current<1e-12:
                    raise ValueError("Constraints would collapse a line")
                row = np.zeros(points.size)
                row[2*a:2*a+2],row[2*b:2*b+2] = -delta/current,delta/current
                return current,row
            for i,(a,b) in enumerate(self.edges):
                target = self.dimensions[i]
                if target is not None and not self.is_arc(i):
                    current,row = length_row(i)
                    residual.append(current-target)
                    jacobian.append(row)
                if axes[i] is not None:
                    axis = axes[i]
                    row = np.zeros(points.size)
                    row[2*b+axis],row[2*a+axis] = 1,-1
                    residual.append(points[b,axis]-points[a,axis])
                    jacobian.append(row)
            for relation in self.constraints:
                kind,segments = relation["type"],relation["segments"]
                if kind=="equal":
                    first,base_row = length_row(segments[0])
                    for index in segments[1:]:
                        current,row = length_row(index)
                        residual.append(current-first)
                        jacobian.append(row-base_row)
                else:
                    a,b = self.edges[segments[0]]
                    axis = 1 if kind=="horizontal" else 0
                    row = np.zeros(points.size)
                    row[2*b+axis],row[2*a+axis] = 1,-1
                    residual.append(points[b,axis]-points[a,axis])
                    jacobian.append(row)
            fixed_points = [] if drag is not None else [0]
            for point in fixed_points:
                for axis in (0,1):
                    row = np.zeros(points.size)
                    row[2*point+axis] = 1
                    residual.append(points[point,axis]-initial[point,axis])
                    jacobian.append(row)
            if not residual:
                break
            if max(abs(v) for v in residual)<1e-10:
                break
            matrix = np.asarray(jacobian)
            if drag is not None:
                # Only the dragged endpoint is an unknown. This leaves other
                # endpoints exactly unchanged and keeps large sketches fast.
                index = drag[0]
                step = np.linalg.lstsq(matrix[:,2*index:2*index+2], -np.asarray(residual), rcond=None)[0]
                points[index] += step
            else:
                step = np.linalg.lstsq(matrix,-np.asarray(residual),rcond=None)[0]
                points += step.reshape(-1,2)
            if not np.isfinite(points).all():
                raise ValueError("These constraints cannot be solved")
        if residual and max(abs(v) for v in residual)>1e-8:
            raise ValueError("This constraint conflicts with another relation or dimension. Remove a conflicting constraint first.")
        self.points = points.tolist()
        for i,(a,b) in enumerate(self.edges):
            if self.is_arc(i) and self.dimensions[i] is not None:
                self.arcs[i]["bulge"] = radius_bulge(self.points[a],self.points[b],self.dimensions[i],self.arcs[i]["bulge"])

    def geometry(self):
        """Serialize editable geometry, including optional curves and relations when
        present.

        Returns:
            dict: Independent JSON-compatible sketch definition in metres.
        """
        result = dict(type="sketch",points=copy.deepcopy(self.points),closed=self.closed,
                      dimensions=list(self.dimensions),thickness=self.thickness)
        if any(self.arcs):
            result["arcs"] = copy.deepcopy(self.arcs)
        if self.constraints:
            result["constraints"] = copy.deepcopy(self.constraints)
        return result

    @classmethod
    def from_geometry(cls,g):
        """Validate a sketch envelope, copy its editable data, and check all geometry and
        constraints.

        Args:
            g (dict): Serialized geometry envelope to parse and validate.

        Returns:
            Sketch: Independent validated sketch; invalid input raises ValueError.
        """
        if not isinstance(g,dict) or set(g)-{"arcs","constraints"}!={"type","points","closed","dimensions","thickness"} or g["type"]!="sketch":
            raise ValueError("Expected a sketch with points, closed, dimensions and thickness")
        if not isinstance(g["dimensions"],list):
            raise ValueError("Dimensions must be a list")
        sketch = cls(copy.deepcopy(g["points"]),g["closed"],list(g["dimensions"]),g["thickness"],copy.deepcopy(g.get("arcs",[])),copy.deepcopy(g.get("constraints",[])))
        sketch.validate()
        return sketch

    def triangles(self):
        """Validate and triangulate a closed simple outline by ear clipping, tessellating
        curves first.

        Returns:
            list: Counterclockwise index triples into outline_points; invalid or open
            geometry raises ValueError.
        """
        self.validate()
        if not self.closed:
            raise ValueError("Close the outline to create a face before importing it into a scene")
        if any(self.arcs):
            return self._polygon()._triangles_unchecked()
        return self._triangles_unchecked()

    def _triangles_unchecked(self):
        """Ear-clip an already validated straight-edge polygon, removing redundant
        collinear vertices.

        Returns:
            list: Counterclockwise triples indexing this sketch's points; triangulation
            failure raises ValueError.
        """
        span = max(max(p[axis] for p in self.points)-min(p[axis] for p in self.points) for axis in (0,1))
        tolerance = max(1e-30, span*span*1e-12)
        remaining = list(range(len(self.points)))
        if self.signed_area<0:
            remaining.reverse()
        # Collinear sketch segments remain editable but need no extra face ear.
        while len(remaining)>3:
            redundant = next((i for i in range(len(remaining)) if abs(cross(self.points[remaining[i-1]],self.points[remaining[i]],self.points[remaining[(i+1)%len(remaining)]]))<tolerance),None)
            if redundant is None:
                break
            remaining.pop(redundant)
        result = []
        while len(remaining)>3:
            for i,b in enumerate(remaining):
                a,c = remaining[i-1],remaining[(i+1)%len(remaining)]
                pa,pb,pc = [self.points[v] for v in (a,b,c)]
                if cross(pa,pb,pc)<=0:
                    continue
                if any(all(v>=-tolerance for v in (cross(pa,pb,self.points[p]),cross(pb,pc,self.points[p]),cross(pc,pa,self.points[p]))) for p in remaining if p not in (a,b,c)):
                    continue
                result.append((a,b,c))
                remaining.pop(i)
                break
            else:
                raise ValueError("Cannot triangulate this face; check its outline")
        return result+[tuple(remaining)]


def prism_vertices(sketch, dtype=np.float32):
    """Build a flat-shaded closed prism with outward normals, centered on its area centroid
    in XY and symmetric about Z=0.

    Args:
        sketch (Sketch): Outline and thickness used by this operation, in metres.

    Returns:
        numpy.ndarray: Flat float32 XYZ/normal data for triangles; invalid or
        unrenderable geometry raises ValueError.
    """
    triangles = sketch.triangles()
    cx,cy = sketch.centroid
    low,high = -sketch.thickness/2,sketch.thickness/2
    outline = sketch.outline_points
    points = [(x-cx,y-cy) for x,y in outline]
    clockwise = sketch.signed_area<0
    result = []

    def triangle(a,b,c):
        """Append one triangle and its computed flat normal to the enclosing output list.

        Args:
            a (sequence): Local XYZ triangle vertex in metres, ordered for the desired
                outward normal.
            b (sequence): Local XYZ triangle vertex in metres, ordered for the desired
                outward normal.
            c (sequence): Local XYZ triangle vertex in metres, ordered for the desired
                outward normal.

        Returns:
            None. Extends the prism builder's result with three XYZ/normal vertices.
        """
        normal = np.cross(np.subtract(b,a),np.subtract(c,a))
        normal /= np.linalg.norm(normal)
        for p in (a,b,c):
            result.extend((*p,*normal))

    for a,b,c in triangles:
        triangle((*points[a],high),(*points[b],high),(*points[c],high))
        triangle((*points[c],low),(*points[b],low),(*points[a],low))
    for a,b in [(i,(i+1)%len(points)) for i in range(len(points))]:
        if clockwise:
            a,b = b,a
        triangle((*points[a],low),(*points[b],low),(*points[b],high))
        triangle((*points[a],low),(*points[b],high),(*points[a],high))
    output = np.asarray(result,dtype=dtype)
    if not np.isfinite(output).all():
        raise ValueError("Sketch exceeds the renderer's numeric range")
    return output
