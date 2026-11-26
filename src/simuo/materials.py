"""Shared room-temperature isotropic material snapshots, stored in SI units."""
from dataclasses import asdict, dataclass, replace
from pathlib import Path
import json
import math
from uuid import uuid4

from simuo.resources.paths import resource_path
from simuo.project.temporary_parts import atomic_write


@dataclass(frozen=True)
class MaterialDefinition:
    name: str
    young_modulus: float | None = None
    poisson_ratio: float | None = None
    density: float | None = None
    preset_id: str | None = None
    yield_strength: float | None = None
    ultimate_tensile_strength: float | None = None

    def __post_init__(self):
        if not isinstance(self.name, str) or not self.name.strip():
            raise ValueError("Material needs a name")
        for label, value in (("Young's modulus", self.young_modulus), ("Poisson ratio", self.poisson_ratio), ("Density", self.density)):
            if value is not None and (isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value)):
                raise ValueError(f"{label} must be finite")
        if self.young_modulus is not None and self.young_modulus <= 0:
            raise ValueError("Young's modulus must be positive")
        if self.poisson_ratio is not None and not -1 < self.poisson_ratio < .5:
            raise ValueError("Poisson ratio must be between -1 and 0.5")
        if self.density is not None and self.density <= 0:
            raise ValueError("Density must be positive")
        if self.preset_id is not None and not isinstance(self.preset_id, str):
            raise ValueError("Invalid material preset identifier")
        validate_strengths(self.yield_strength, self.ultimate_tensile_strength)

    def to_dict(self):
        return asdict(self)


def validate_strengths(yield_strength, ultimate_tensile_strength):
    for label, value in (("Yield strength", yield_strength), ("Ultimate tensile strength", ultimate_tensile_strength)):
        if value is not None and (isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value) or value <= 0):
            raise ValueError(f"{label} must be finite and positive (Pa)")
    if yield_strength is not None and ultimate_tensile_strength is not None and ultimate_tensile_strength < yield_strength:
        raise ValueError("Ultimate tensile strength must be at least the yield strength")


def inherited_material(part=None):
    if part is None:
        return MaterialDefinition("From Part")
    return MaterialDefinition("From Part", density=part.density)


def material_from_dict(data):
    if data is None:
        return None
    if not isinstance(data, dict):
        raise ValueError("Material assignment must be an object")
    try:
        return MaterialDefinition(**data)
    except TypeError as error:
        raise ValueError("Invalid material assignment") from error


# JSON is the single source of preset properties and reference metadata.


@dataclass(frozen=True)
class MaterialRecord:
    material: MaterialDefinition
    source_url: str | None = None
    strength_source_url: str | None = None
    strength_notes: str | None = None

    def __post_init__(self):
        if not isinstance(self.material, MaterialDefinition):
            raise ValueError("Invalid material definition")
        for value in (self.source_url, self.strength_source_url, self.strength_notes):
            if value is not None and not isinstance(value, str):
                raise ValueError("Material references must be text")

    def to_dict(self):
        return {"format": "simuo.material", "version": 1, **asdict(self)}


def load_material(path):
    try:
        data = json.loads(Path(path).read_text(encoding="utf-8-sig"))
        if not isinstance(data, dict) or data.get("format") != "simuo.material":
            raise ValueError("Not a SimuO material JSON file")
        if type(data.get("version")) is not int or data["version"] != 1:
            raise ValueError("Unsupported material file version")
        material = material_from_dict(data.get("material"))
        return MaterialRecord(material, data.get("source_url"), data.get("strength_source_url"), data.get("strength_notes"))
    except (TypeError, UnicodeError, json.JSONDecodeError) as error:
        raise ValueError(f"Invalid material JSON: {error}") from error


def save_material(path, record):
    if isinstance(record, MaterialDefinition):
        record = MaterialRecord(record)
    if not isinstance(record, MaterialRecord):
        raise ValueError("Invalid material record")
    supplied = (getattr(record.material, name) for name in MaterialDefinition.__dataclass_fields__
                if name not in ("name", "preset_id"))
    if not any(value is not None for value in supplied):
        raise ValueError("Supply at least one material property before saving")
    atomic_write(path, (json.dumps(record.to_dict(), indent=2, allow_nan=False)+"\n").encode("utf-8"))


def _load_bundled():
    paths = sorted(resource_path("Assets", "materials").glob("*.json"))
    if not paths:
        raise ValueError("Bundled material catalog is missing")
    records = tuple(load_material(path) for path in paths)
    ids = [record.material.preset_id for record in records]
    if any(not key or key == "custom" or key.startswith("user:") for key in ids) or len(ids) != len(set(ids)):
        raise ValueError("Invalid bundled material identifiers")
    return records


BUNDLED_MATERIALS = _load_bundled()
# Compatibility views for existing callers; no separate hard-coded data.
PRESETS = tuple(record.material for record in BUNDLED_MATERIALS)
MATERIAL_PRESETS = {material.preset_id: material for material in PRESETS}
PRESET_SOURCES = {r.material.preset_id: r.source_url for r in BUNDLED_MATERIALS if r.source_url}
STRENGTH_SOURCES = {r.material.preset_id: r.strength_source_url for r in BUNDLED_MATERIALS if r.strength_source_url}
STRENGTH_NOTES = {r.material.preset_id: r.strength_notes for r in BUNDLED_MATERIALS if r.strength_notes}


class MaterialCatalog:
    """Bundled records plus a writable personal JSON library; no Qt dependency."""
    def __init__(self, directory):
        self.directory = Path(directory)
        self.reload()

    def reload(self):
        self.records = {r.material.preset_id: r for r in BUNDLED_MATERIALS}
        self.personal = {}
        self.paths = {}
        self.errors = []
        for path in sorted(self.directory.glob("*.json")):
            try:
                record = load_material(path)
                key = record.material.preset_id
                if not key or not key.startswith("user:") or key in self.records:
                    raise ValueError("Personal material needs a unique user identifier")
                self.personal[key] = record
                self.paths[key] = path
                self.records[key] = record
            except (OSError, ValueError) as error:
                self.errors.append(f"{path.name}: {error}")

    def get(self, key):
        return self.records.get(key)

    def named(self, name):
        return next((key for key, r in self.personal.items() if r.material.name.casefold() == name.strip().casefold()), None)

    def save(self, record, *, replace_id=None):
        self.reload()
        if replace_id is not None and replace_id not in self.personal:
            raise ValueError("Only personal materials can be replaced")
        key = replace_id or "user:"+uuid4().hex
        name = record.material.name.strip()
        if replace_id is None:
            original = name
            count = 2
            while self.named(name):
                name = f"{original} ({count})"
                count += 1
        record = replace(record, material=replace(record.material, name=name, preset_id=key))
        self.directory.mkdir(parents=True, exist_ok=True)
        path = self.paths[replace_id] if replace_id else self.directory/f"{key.replace(':', '-')}.json"
        save_material(path, record)
        self.reload()
        return record

    def import_file(self, path):
        record = load_material(path)
        self.reload()
        key = record.material.preset_id
        if key in self.records and self.records[key] == record:
            return record
        for existing in self.records.values():
            if replace(existing, material=replace(existing.material, preset_id=None)) == replace(record, material=replace(record.material, preset_id=None)):
                return existing
        return self.save(record)
