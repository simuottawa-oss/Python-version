"""Editable sketch-part documents. Geometry uses meters; the UI shows mm."""
import copy
import json
from pathlib import Path
import uuid

from simuo.parts.part_format import load_part
from simuo.parts.sketch_geometry import Sketch
from simuo.project.temporary_parts import atomic_write


def new_document():
    """Create a version-2 draft with a new UUID and default material and physics settings.

    Returns:
        dict: New document with an empty sketch and SI units.
    """
    return {"format":".simuOPart","version":2,"id":str(uuid.uuid4()),"name":"New part",
            "units":{"length":"m","mass":"kg","time":"s"},
            "coordinates":{"handedness":"right","up":"+Y"},
            "geometry":Sketch().geometry(),"appearance":{"color":"#47b9d5"},
            "material":{"name":"Default material","density":1000,"friction":.5,"restitution":.2},
            "physics":{"body_type":"dynamic","mass_source":"density","collider":"geometry"},
            "initial_state":{"position":[0,1,0],"velocity":[0,0,0]},"properties":{}}


def open_document(path):
    """Load an editable sketch document, allowing drafts; otherwise use the part bounds to
    make a rectangular sketch.

    Args:
        path (str or Path): Source or destination file path used by this operation.

    Returns:
        tuple: Document dictionary and independent Sketch, represented as version 2.
    """
    part = load_part(path,allow_draft=True)
    data = json.loads(Path(path).read_text(encoding="utf-8-sig"))
    if part.sketch is not None:
        sketch = copy.deepcopy(part.sketch)
    else:
        x,y,z = part.size
        sketch = Sketch([[-x/2,-y/2],[x/2,-y/2],[x/2,y/2],[-x/2,y/2]],True,[None]*4,z)
    data["version"] = 2
    data["geometry"] = sketch.geometry()
    return data,sketch


def save_document(path,data,sketch):
    """Validate the sketch and atomically save version-2 geometry in a document copy. Other
    material and physics fields are not fully revalidated here.

    Args:
        path (str or Path): Source or destination file path used by this operation.
        data (dict): Editable part document fields to preserve around serialized
            geometry.
        sketch (Sketch): Outline and thickness used by this operation, in metres.

    Returns:
        dict: Saved document data; validation or filesystem failures propagate.
    """
    sketch.validate()
    saved = copy.deepcopy(data)
    saved["format"],saved["version"],saved["geometry"] = ".simuOPart",2,sketch.geometry()
    if not isinstance(saved.get("name"),str) or not saved["name"].strip():
        raise ValueError("Give the part a name before saving")
    atomic_write(path,json.dumps(saved,indent=2,allow_nan=False).encode("utf-8"))
    return saved
