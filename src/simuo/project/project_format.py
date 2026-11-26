"""Content-based SimuO project routing, independent of editors and geometry."""
from dataclasses import dataclass
import json
import math
from pathlib import Path

PROJECT_FILTER = "SimuO Projects (*.simuO);;Legacy Structural Analysis (*.simuOAnalysis);;All Files (*)"


@dataclass(frozen=True)
class ProjectDocument:
    project_type: str
    data: dict
    legacy: bool = False


def project_data(project_type, **payload):
    if project_type not in ("scene", "structural"):
        raise ValueError("Unknown SimuO project type")
    return {"format": ".simuO", "version": 2, "project_type": project_type, **payload}


def read_project(path):
    def pairs(items):
        result = {}
        for key, value in items:
            if key in result:
                raise ValueError(f"Duplicate JSON key: {key}")
            result[key] = value
        return result
    def invalid(value):
        raise ValueError(f"Nonfinite JSON number: {value}")
    def real(value):
        number = float(value)
        return number if math.isfinite(number) else invalid(value)
    data = json.loads(Path(path).read_text(encoding="utf-8-sig"), object_pairs_hook=pairs,
                      parse_constant=invalid, parse_float=real)
    if not isinstance(data, dict):
        raise ValueError("A SimuO project must be a JSON object")
    legacy = False
    if data.get("format") == ".simuO":
        if type(data.get("version")) is not int or data["version"] != 2:
            raise ValueError("Unsupported SimuO project version")
        kind = data.get("project_type")
    elif data.get("format") == ".simuOAnalysis":
        if type(data.get("version")) is not int or data["version"] != 1:
            raise ValueError("Unsupported legacy structural analysis version")
        kind, legacy = "structural", True
    elif "format" not in data and "project_type" not in data and "objects" in data:
        if "version" in data and (type(data["version"]) is not int or data["version"] != 1):
            raise ValueError("Unsupported legacy scene version")
        kind, legacy = "scene", True
    else:
        raise ValueError("Unrecognized SimuO project header")
    if kind == "scene":
        if not isinstance(data.get("objects"), list) or any(not isinstance(obj, dict) for obj in data["objects"]):
            raise ValueError("A scene requires an objects array")
    elif kind == "structural":
        if not isinstance(data.get("setup"), dict):
            raise ValueError("A structural project requires analysis setup")
    else:
        raise ValueError(f"Unsupported project type: {kind!r}")
    return ProjectDocument(kind, data, legacy)
