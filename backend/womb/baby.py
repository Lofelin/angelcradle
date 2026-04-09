"""
Baby data model: the womb's output.

No name, only an ID. Unified structure across species.
Birth attributes (sex, race/breed) read from species blueprint.
Complications, environment, and fate recorded from real probability rolls.
"""

from __future__ import annotations

import random
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path

import yaml

SPECIES_DIR = Path(__file__).parent / "species"


@dataclass
class Baby:
    """A baby: the womb's output."""
    id: str
    species: str
    sex: str
    phenotype: dict
    born_at: str
    genes: dict                             # {"expression": [...]}
    first_cry: str
    gestation_log: list[dict]               # seven-stage development records
    environment: dict                       # maternal environment during gestation
    complications: list[dict] = field(default_factory=list)   # 升级: list[dict] 含 severity/syndrome_origin
    preterm: dict = field(default_factory=dict)
    alive: bool = True
    parent_genomes: dict = field(default_factory=dict)        # 父母基因快照

    @property
    def complication_names(self) -> list[str]:
        """向后兼容：返回缺陷名称列表。"""
        return [c["defect"] if isinstance(c, dict) else c for c in self.complications]

    def to_dict(self, include_log: bool = True) -> dict:
        result = {
            "id": self.id,
            "species": self.species,
            "sex": self.sex,
            "phenotype": self.phenotype,
            "born_at": self.born_at,
            "alive": self.alive,
            "genes": self.genes,
            "first_cry": self.first_cry,
            "complications": self.complications,
            "complication_names": self.complication_names,
            "preterm": self.preterm,
            "environment": self.environment,
            "parent_genomes": self.parent_genomes,
        }
        if include_log:
            result["gestation_log"] = self.gestation_log
        return result


@dataclass
class ConceptionResult:
    """Result of a conception attempt. May contain babies, or a failure."""
    success: bool
    babies: list[Baby] = field(default_factory=list)
    miscarriage: bool = False
    offspring_count: int = 0
    fate_log: dict = field(default_factory=dict)  # all fate rolls recorded

    def to_dict(self) -> dict:
        return {
            "success": self.success,
            "miscarriage": self.miscarriage,
            "offspring_count": self.offspring_count,
            "babies": [b.to_dict(include_log=False) for b in self.babies],
            "fate_log": self.fate_log,
        }


def generate_id(now: datetime, index: int = 0) -> str:
    """Generate baby ID: AC-YYYYMMDD-XXXX."""
    date_part = now.strftime("%Y%m%d")
    seq = int(now.strftime("%H")) * 3600 + int(now.strftime("%M")) * 60 + int(now.strftime("%S"))
    return f"AC-{date_part}-{seq + index:04d}"


def _load_birth_attributes(species: str) -> dict:
    """Load birth attributes from species blueprint."""
    path = SPECIES_DIR / f"{species}.yaml"
    if not path.is_file():
        return {}
    blueprint = yaml.safe_load(path.read_text(encoding="utf-8"))
    return blueprint.get("birth_attributes", {})


def determine_sex(species: str, override: str = None) -> str:
    """Determine sex based on species blueprint sex determination system."""
    if override in ("male", "female"):
        return override
    attrs = _load_birth_attributes(species)
    sex_system = attrs.get("sex_system", "XY")
    if sex_system == "XY":
        return random.choice(["male", "female"])
    return random.choice(["male", "female"])


def determine_phenotype(species: str, override: str = None) -> dict:
    """Determine innate phenotype from species blueprint."""
    attrs = _load_birth_attributes(species)
    phenotype = {}
    races = attrs.get("races")
    if races:
        phenotype["race"] = override if override and override in races else random.choice(races)
    breeds = attrs.get("breeds")
    if breeds:
        phenotype["breed"] = override if override and override in breeds else random.choice(breeds)
    return phenotype
