"""Shared room-temperature isotropic material snapshots, stored in SI units."""
from dataclasses import asdict, dataclass
import math


@dataclass(frozen=True)
class MaterialDefinition:
    name: str
    young_modulus: float | None = None
    poisson_ratio: float | None = None
    density: float | None = None
    preset_id: str | None = None

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

    def to_dict(self):
        return asdict(self)


# Typical engineering values, not strength allowables. Polymer Poisson ratios
# and nominal alloy constants are modelling approximations; see materials.md.
PRESETS = (
    MaterialDefinition("A36 steel", 200e9, .30, 7850., "steel-a36"),
    MaterialDefinition("304 stainless steel", 200e9, .30, 7900., "stainless-304"),
    MaterialDefinition("6061-T6 aluminum", 69e9, .33, 2700., "aluminum-6061-t6"),
    MaterialDefinition("Ti-6Al-4V titanium", 114e9, .31, 4420., "titanium-ti6al4v"),
    MaterialDefinition("C110 copper", 117e9, .328125, 8940., "copper-c110"),
    MaterialDefinition("ABS (unfilled)", 2.3e9, .35, 1040., "abs"),
    MaterialDefinition("Polycarbonate (unfilled)", 2.4e9, .37, 1200., "polycarbonate"),
)
MATERIAL_PRESETS = {item.preset_id: item for item in PRESETS}


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


PRESET_SOURCES = {
    "steel-a36": "https://www.ssab.com/en/support/product-material-data/steel/20-questions",
    "stainless-304": "https://www.outokumpu.com/en/products/product-ranges/core",
    "aluminum-6061-t6": "https://www.hydro.com/globalassets/01-products--services/extruded-profiles/americas/ena-resources/alloy-data-sheets/hydro_2019_data_sheet_6061.pdf",
    "titanium-ti6al4v": "https://www.timet.com/assets/local/documents/datasheets/alphaandbetaalloys/6-4.pdf",
    "copper-c110": "https://ucpcdn.thyssenkrupp.com/_legacy/UCPthyssenkruppBAMXNA/assets.files/tkmna_com/products/collateral/copper-and-alloys-guide.pdf",
    "abs": "https://www.ineos-styrolution.com/Product/Terluran_Terluran-GP-22_SKU300600120827_lang_en_GB.html",
    "polycarbonate": "https://www.covestro.com/en/products/makrolon-2405-00945088",
}
