"""Plane-supported sketches and additive, watertight solid extrusions."""
import copy
import math
import uuid

import numpy as np

from simuo.parts.sketch_geometry import Sketch

PLANES = {
    "Front": {"origin":[0,0,0],"u":[1,0,0],"v":[0,1,0]},
    "Right": {"origin":[0,0,0],"u":[0,0,-1],"v":[0,1,0]},
    "Top": {"origin":[0,0,0],"u":[1,0,0],"v":[0,0,-1]},
}


def validate_frame(frame):
    """Check finite bounded origin/axes and orthogonal unit sketch axes.

    Args:
        frame (dict): Metre-valued origin and orthogonal unit axes u/v defining a sketch
            plane.

    Returns:
        dict: Original frame; raises ValueError for an invalid frame.
    """
    if not isinstance(frame,dict) or set(frame)!={"origin","u","v"}:
        raise ValueError("A sketch frame needs origin, u and v")
    for value in frame.values():
        if not isinstance(value,list) or len(value)!=3 or any(isinstance(v,bool) or not isinstance(v,(int,float)) or not math.isfinite(v) or abs(v)>1e6 for v in value):
            raise ValueError("Sketch frames require finite 3D vectors")
    u,v = np.asarray(frame["u"]),np.asarray(frame["v"])
    if abs(np.linalg.norm(u)-1)>1e-7 or abs(np.linalg.norm(v)-1)>1e-7 or abs(np.dot(u,v))>1e-7:
        raise ValueError("Sketch axes must be orthogonal unit vectors")
    return frame


def support_frame(support):
    """Resolve a reference plane or validate a saved face frame.

    Args:
        support (dict): Named reference-plane support or face support with parent ID,
            label, and frame.

    Returns:
        dict: Independent reference-plane frame, or the validated face frame from the
        support.
    """
    if not isinstance(support,dict):
        raise ValueError("Select a reference plane or a flat face")
    if support.get("type")=="plane" and set(support)=={"type","name"} and support["name"] in PLANES:
        return copy.deepcopy(PLANES[support["name"]])
    if support.get("type")=="face" and set(support)=={"type","parent","label","frame"}:
        if not isinstance(support["parent"],str) or not isinstance(support["label"],str):
            raise ValueError("A face support needs a parent feature and a label")
        return validate_frame(support["frame"])
    raise ValueError("Invalid sketch support")


def to_world(points,frame):
    """Map planar coordinates into 3D using the frame origin and axes.

    Args:
        points (array-like): Planar XY coordinates in metres, reshapeable to (N, 2).
        frame (dict): Metre-valued origin and orthogonal unit axes u/v defining a sketch
            plane.

    Returns:
        numpy.ndarray: Shape (N, 3) world points in metres.
    """
    points = np.asarray(points,dtype=float).reshape(-1,2)
    return np.asarray(frame["origin"])+points[:,:1]*frame["u"]+points[:,1:]*frame["v"]


def to_plane(points,frame):
    """Project 3D points into a frame's two orthogonal sketch axes.

    Args:
        points (array-like): World coordinates in metres with final dimension 3.
        frame (dict): Metre-valued origin and orthogonal unit axes u/v defining a sketch
            plane.

    Returns:
        numpy.ndarray: Coordinates with the input's leading dimensions and a final
        dimension of 2.
    """
    delta = np.asarray(points)-np.asarray(frame["origin"])
    return np.stack((delta @ frame["u"],delta @ frame["v"]),axis=-1)


def planar_faces(vertices):
    """Group edge-connected coplanar triangles into selectable faces and extract their
    boundaries.

    Args:
        vertices (array-like): Interleaved triangle XYZ/normal data, reshapeable to
            (triangle_count, 3, 6).

    Returns:
        list: Face dictionaries containing label, triangles, normal, frame, and boundary
        edges; empty for an empty mesh.
    """
    triangles = np.asarray(vertices).reshape(-1,3,6)[:,:,:3].astype(float)
    if not len(triangles):
        return []
    normals = np.cross(triangles[:,1]-triangles[:,0],triangles[:,2]-triangles[:,0])
    normals /= np.linalg.norm(normals,axis=1)[:,None]
    edges = {}
    neighbors = [set() for _ in triangles]
    for index,triangle in enumerate(triangles):
        for a,b in ((0,1),(1,2),(2,0)):
            key = tuple(sorted((tuple(triangle[a]),tuple(triangle[b]))))
            for other in edges.get(key,[]):
                if np.dot(normals[index],normals[other])>1-1e-7:
                    neighbors[index].add(other)
                    neighbors[other].add(index)
            edges.setdefault(key,[]).append(index)
    remaining = set(range(len(triangles)))
    faces = []
    while remaining:
        first = min(remaining)
        group,queue = [],[first]
        while queue:
            item = queue.pop()
            if item not in remaining:
                continue
            remaining.remove(item)
            group.append(item)
            queue.extend(neighbors[item] & remaining)
        normal = normals[first]
        mesh = triangles[group]
        areas = np.linalg.norm(np.cross(mesh[:,1]-mesh[:,0],mesh[:,2]-mesh[:,0]),axis=1)
        origin = np.average(mesh.mean(axis=1),axis=0,weights=areas)
        u = np.array([1.,0,0]) if abs(normal[0])<.9 else np.array([0.,0,-1])
        u -= np.dot(u,normal)*normal
        u /= np.linalg.norm(u)
        v = np.cross(normal,u)
        counts = {}
        for triangle in mesh:
            for a,b in ((0,1),(1,2),(2,0)):
                key = tuple(sorted((tuple(triangle[a]),tuple(triangle[b]))))
                counts[key] = counts.get(key,0)+1
        faces.append({"label":f"Face {len(faces)+1}","triangles":mesh,"normal":normal,
                      "frame":{"origin":origin.tolist(),"u":u.tolist(),"v":v.tolist()},
                      "edges":[np.array(edge) for edge,count in counts.items() if count==1]})
    return faces


class FeatureModel:
    def __init__(self,features=None):
        """Copy feature history and initialize empty derived mesh, face, and volume data.
        Call build to evaluate the history.

        Args:
            features (list, optional): Feature dictionaries to deep-copy; None creates
                empty history.

        Returns:
            None.
        """
        self.features = copy.deepcopy(features or [])
        self.vertices = np.empty(0,dtype=np.float32)
        self.analysis_points = np.empty((0, 3), dtype=np.float64)
        self.analysis_triangles = np.empty((0, 3), dtype=np.int64)
        self.faces = []
        self.volume = 0.

    @property
    def has_solid(self):
        """Check whether a built display mesh exists.

        Returns:
            bool: True when the vertex buffer is nonempty.
        """
        return bool(self.vertices.size)

    @property
    def size(self):
        """Measure the built mesh's axis-aligned bounding-box dimensions.

        Returns:
            tuple: XYZ extents in metres, or (0.001, 0.001, 0.001) for a draft.
        """
        return tuple(np.ptp(self.vertices.reshape(-1,6)[:,:3],axis=0)) if self.has_solid else (.001,.001,.001)

    @property
    def last_extrusion(self):
        """Find the last feature with an extrusion depth in history order.

        Returns:
            str or None: Feature ID, or None if no extrusion exists.
        """
        return next((f["id"] for f in reversed(self.features) if f["depth"] is not None),None)

    def geometry(self):
        """Serialize the editable feature history without derived mesh data.

        Returns:
            dict: feature_part geometry with a deep copy of the feature list.
        """
        return {"type":"feature_part","features":copy.deepcopy(self.features)}

    def new_sketch(self,support):
        """Validate a support and append an empty sketch feature with a new UUID. Does not
        build the model.

        Args:
            support (dict): Named reference-plane support or face support with parent
                ID, label, and frame.

        Returns:
            dict: Newly appended feature, also owned by this model.
        """
        support_frame(support)
        feature = {"id":str(uuid.uuid4()),"name":f"Sketch {len(self.features)+1}",
                   "support":copy.deepcopy(support),"sketch":Sketch().geometry(),"depth":None,"symmetric":False}
        self.features.append(feature)
        return feature

    def build(self):
        """Validate ordered features and rebuild one connected solid with manifold3d.
        Updates volume, float32 triangles/normals, and double-precision face supports;
        invalid history or geometry raises ValueError.

        Returns:
            FeatureModel: This model after rebuilding; a draft can have no solid.
        """
        if len(self.features)>64:
            raise ValueError("This editor supports up to 64 sketches")
        solid = None
        previous_ids = set()
        seen = set()
        for feature in self.features:
            if not isinstance(feature,dict) or set(feature)!={"id","name","support","sketch","depth","symmetric"}:
                raise ValueError("Invalid sketch/extrusion feature")
            if not isinstance(feature["id"],str) or not feature["id"] or feature["id"] in seen:
                raise ValueError("Features need unique nonempty IDs")
            seen.add(feature["id"])
            if not isinstance(feature["name"],str) or not feature["name"].strip() or type(feature["symmetric"]) is not bool:
                raise ValueError("Invalid feature name or extrusion mode")
            frame = support_frame(feature["support"])
            sketch = Sketch.from_geometry(feature["sketch"])
            if feature["support"]["type"]=="face":
                if feature["support"]["parent"] not in previous_ids or solid is None:
                    raise ValueError("A face sketch must reference an earlier extrusion")
                mesh = solid.to_mesh64()
                points = np.asarray(mesh.vert_properties)[:,:3]
                indices = np.asarray(mesh.tri_verts)
                tri = points[indices]
                normal = np.cross(tri[:,1]-tri[:,0],tri[:,2]-tri[:,0])
                normal /= np.linalg.norm(normal,axis=1)[:,None]
                expected = np.cross(frame["u"],frame["v"])
                distance = np.abs((tri[:,0]-frame["origin"]) @ expected)
                if not np.any((normal @ expected > 1-1e-7) & (distance<1e-7)):
                    raise ValueError(f"{feature['name']}: its supporting face moved or no longer exists. Recreate the sketch on a current face.")
            depth = feature["depth"]
            if depth is not None:
                if isinstance(depth,bool) or not isinstance(depth,(int,float)) or not math.isfinite(depth) or not 1e-6<=abs(depth)<=1e3:
                    raise ValueError("Extrusion distance must be between 0.001 mm and 1,000 m")
                if not sketch.closed:
                    raise ValueError("Close the sketch before extruding it")
                try:
                    import manifold3d as m
                except ImportError as error:
                    raise ValueError("Install the project requirements (manifold3d) to build 3D feature parts") from error
                contour = sketch.outline_points if sketch.signed_area>0 else list(reversed(sketch.outline_points))
                overlap = 0.
                if feature["support"]["type"]=="face" and depth>0 and not feature["symmetric"]:
                    bounds = np.asarray(solid.bounding_box())
                    overlap = min(abs(depth)*.001,max(1e-10,float(np.linalg.norm(bounds[3:]-bounds[:3]))*1e-8))
                # Shared-face joins need a tiny inward overlap: even double
                # arithmetic may place a computed frame one ULP off a cap.
                # The outward end remains exactly at the requested distance.
                extrusion = m.CrossSection([contour]).extrude(abs(depth)+overlap)
                if overlap:
                    extrusion = extrusion.translate((0,0,-overlap))
                direction = np.cross(frame["u"],frame["v"])*(1 if depth>0 else -1)
                origin = np.asarray(frame["origin"])
                if feature["symmetric"]:
                    origin = origin-direction*abs(depth)/2
                # Keep a positive determinant for reversed extrusions.
                if depth<0:
                    extrusion = extrusion.translate((0,0,-abs(depth)))
                    direction = -direction
                matrix = np.column_stack((frame["u"],frame["v"],direction,origin))
                extrusion = extrusion.transform(matrix)
                candidate = extrusion if solid is None else solid+extrusion
                if candidate.is_empty() or candidate.status()!=m.Error.NoError:
                    raise ValueError("This extrusion does not produce a valid solid")
                if len(candidate.decompose())!=1:
                    raise ValueError("The extrusion must join the existing solid across a face")
                solid = candidate
                previous_ids.add(feature["id"])
        self.vertices = np.empty(0,dtype=np.float32)
        self.volume = 0
        self.analysis_points = np.empty((0, 3), dtype=np.float64)
        self.analysis_triangles = np.empty((0, 3), dtype=np.int64)
        face_vertices = np.empty(0,dtype=float)
        if solid is not None:
            mesh = solid.to_mesh64()
            self.analysis_points = np.asarray(mesh.vert_properties)[:, :3].copy()
            self.analysis_triangles = np.asarray(mesh.tri_verts, dtype=np.int64).copy()
            triangles = np.asarray(mesh.vert_properties)[:,:3][np.asarray(mesh.tri_verts)]
            # Face supports must retain the kernel's double precision. Using
            # rendered float32 coordinates here can leave a microscopic gap
            # between a new extrusion and its supporting face.
            native_normals = np.cross(triangles[:,1]-triangles[:,0],triangles[:,2]-triangles[:,0])
            native_lengths = np.linalg.norm(native_normals,axis=1)
            native_valid = native_lengths>0
            triangles,native_normals,native_lengths = triangles[native_valid],native_normals[native_valid],native_lengths[native_valid]
            native_normals /= native_lengths[:,None]
            face_vertices = np.concatenate((triangles,np.repeat(native_normals[:,None,:],3,axis=1)),axis=2).ravel()
            # Tiny boolean slivers can collapse at GPU float32 precision.
            # Remove those zero-area triangles from the display/export mesh.
            triangles = triangles.astype(np.float32).astype(float)
            normals = np.cross(triangles[:,1]-triangles[:,0],triangles[:,2]-triangles[:,0])
            lengths = np.linalg.norm(normals,axis=1)
            valid = lengths>0
            triangles,normals,lengths = triangles[valid],normals[valid],lengths[valid]
            if not len(triangles):
                raise ValueError("The solid is too small for the rendering precision")
            normals /= lengths[:,None]
            interleaved = np.concatenate((triangles,np.repeat(normals[:,None,:],3,axis=1)),axis=2)
            self.vertices = interleaved.astype(np.float32).ravel()
            self.volume = solid.volume()
            if not np.isfinite(self.vertices).all() or self.volume<=0:
                raise ValueError("Solid exceeds the supported numerical range")
        self.faces = planar_faces(face_vertices)
        return self

    @classmethod
    def from_geometry(cls,g):
        """Validate a feature_part geometry envelope and evaluate its history.

        Args:
            g (dict): Serialized geometry envelope to parse and validate.

        Returns:
            FeatureModel: New built model; invalid geometry raises ValueError.
        """
        if not isinstance(g,dict) or set(g)!={"type","features"} or g["type"]!="feature_part" or not isinstance(g["features"],list):
            raise ValueError("Expected a feature part with a list of sketches and extrusions")
        return cls(g["features"]).build()

    def face_support(self,index):
        """Describe a built face as a sketch support tied to the last extrusion.

        Args:
            index (int): Zero-based planar face index from the built model.

        Returns:
            dict: Face support with parent ID, label, and copied frame.
        """
        face = self.faces[index]
        return {"type":"face","parent":self.last_extrusion,"label":face["label"],"frame":copy.deepcopy(face["frame"])}

    def face_sketch(self,index):
        """Trace a flat face's single boundary into an editable closed outline. Rejects
        holes or complex boundaries.

        Args:
            index (int): Zero-based planar face index from the built model.

        Returns:
            Sketch: Validated outline in the face's local frame.
        """
        face = self.faces[index]
        edges = [(tuple(a),tuple(b)) for a,b in face["edges"]]
        adjacency = {}
        for a,b in edges:
            adjacency.setdefault(a,[]).append(b)
            adjacency.setdefault(b,[]).append(a)
        if not adjacency or any(len(values)!=2 for values in adjacency.values()):
            raise ValueError("This face has a complex boundary. Create a sketch on it instead.")
        first = next(iter(adjacency))
        outline,previous,current = [],None,first
        while True:
            outline.append(current)
            following = next(p for p in adjacency[current] if p!=previous)
            previous,current = current,following
            if current==first:
                break
            if current in outline:
                raise ValueError("Cannot trace this face boundary")
        if len(outline)!=len(adjacency):
            raise ValueError("This face contains holes. Create a sketch on it instead of pulling the whole face.")
        sketch = Sketch(to_plane(outline,face["frame"]).tolist(),True,[None]*len(outline))
        sketch.validate()
        return sketch
