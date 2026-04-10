"""
Baby data model: the womb's output.

No name, only an ID. Unified structure across species.
Birth attributes (sex, race/breed) read from species blueprint.
Complications, environment, and fate recorded from real probability rolls.

[INPUT]: species blueprints (YAML), 可选 race_weights (from birthplace)
[OUTPUT]: 导出 Baby, ConceptionResult, generate_id, determine_sex, determine_phenotype
[POS]: womb/ 的数据模型层，被 __init__.py 和 api/ 消费
[PROTOCOL]: 变更时更新此头部，然后检查 CLAUDE.md
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
    birthplace: dict = field(default_factory=dict)            # {name, code, coordinates}

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
            "birthplace": self.birthplace,
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
    miscarriage_stage: str = ""     # 流产发生的阶段名
    miscarriage_cause: str = ""     # 主导风险因子类别
    offspring_count: int = 0
    fate_log: dict = field(default_factory=dict)  # all fate rolls recorded

    def to_dict(self) -> dict:
        return {
            "success": self.success,
            "miscarriage": self.miscarriage,
            "miscarriage_stage": self.miscarriage_stage,
            "miscarriage_cause": self.miscarriage_cause,
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


def determine_phenotype(species: str, override: str = None, race_weights: dict = None) -> dict:
    """Determine innate phenotype from species blueprint. race_weights from birthplace."""
    attrs = _load_birth_attributes(species)
    phenotype = {}
    races = attrs.get("races")
    if races:
        if override and override in races:
            phenotype["race"] = override
        elif race_weights:
            available = [r for r in races if r in race_weights]
            if available:
                weights = [race_weights[r] for r in available]
                phenotype["race"] = random.choices(available, weights=weights, k=1)[0]
            else:
                phenotype["race"] = random.choice(races)
        else:
            phenotype["race"] = random.choice(races)
    breeds = attrs.get("breeds")
    if breeds:
        phenotype["breed"] = override if override and override in breeds else random.choice(breeds)
    return phenotype
