"""
简化遗传模型：关键性状的孟德尔遗传。

不是全基因组模拟——是 10 个可观察性状的显隐性/不完全显性/共显性遗传。
足以让 Baby "像妈妈的眼睛"成为可能。

[INPUT]: 可选的父母 ParentGenome，或随机生成
[OUTPUT]: 导出 ParentGenome, random_genome, crossover, genotype_to_phenotype, format_genetics_for_prompt
[POS]: womb/ 的遗传子系统，被 __init__.py 和 stages.py 消费
[PROTOCOL]: 变更时更新此头部，然后检查 CLAUDE.md
"""

from __future__ import annotations

import random
from dataclasses import dataclass, field


# ============================================================
# 人类关键性状定义
# ============================================================

HUMAN_TRAITS = {
    "eye_color": {
        "alleles": ["brown", "blue", "green"],
        "dominance": {"brown": 2, "green": 1, "blue": 0},
        "mode": "simple",
    },
    "hair_type": {
        "alleles": ["curly", "wavy", "straight"],
        "dominance": {"curly": 2, "wavy": 1, "straight": 0},
        "mode": "simple",
    },
    "hair_color": {
        "alleles": ["black", "brown", "red", "blonde"],
        "dominance": {"black": 3, "brown": 2, "red": 1, "blonde": 0},
        "mode": "simple",
    },
    "skin_tone": {
        "alleles": ["dark", "medium", "light"],
        "dominance": {"dark": 2, "medium": 1, "light": 0},
        "mode": "incomplete",  # 不完全显性：dark+light → medium
    },
    "height_tendency": {
        "alleles": ["tall", "average", "short"],
        "dominance": {"tall": 1, "average": 1, "short": 1},
        "mode": "incomplete",
    },
    "metabolism_type": {
        "alleles": ["fast", "moderate", "slow"],
        "dominance": {"fast": 1, "moderate": 1, "slow": 1},
        "mode": "incomplete",
    },
    "blood_type_abo": {
        "alleles": ["A", "B", "O"],
        "dominance": {"A": 1, "B": 1, "O": 0},
        "mode": "codominant",  # A+B → AB
    },
    "earwax_type": {
        "alleles": ["wet", "dry"],
        "dominance": {"wet": 1, "dry": 0},
        "mode": "simple",
    },
    "dimples": {
        "alleles": ["present", "absent"],
        "dominance": {"present": 1, "absent": 0},
        "mode": "simple",
    },
    "freckles": {
        "alleles": ["present", "absent"],
        "dominance": {"present": 1, "absent": 0},
        "mode": "simple",
    },
}

# 物种 → 性状表
SPECIES_TRAITS = {
    "human": HUMAN_TRAITS,
}


@dataclass
class ParentGenome:
    """单个亲本的基因组。每个性状由一对等位基因表示。"""
    traits: dict[str, tuple[str, str]] = field(default_factory=dict)

    def to_dict(self) -> dict:
        return {k: list(v) for k, v in self.traits.items()}

    @classmethod
    def from_dict(cls, data: dict) -> ParentGenome:
        traits = {k: tuple(v) for k, v in data.items()}
        return cls(traits=traits)


def random_genome(species: str = "human") -> ParentGenome:
    """随机生成一个亲本基因组。"""
    trait_defs = SPECIES_TRAITS.get(species, HUMAN_TRAITS)
    traits = {}
    for name, config in trait_defs.items():
        alleles = config["alleles"]
        # 每个等位基因独立随机选取
        traits[name] = (random.choice(alleles), random.choice(alleles))
    return ParentGenome(traits=traits)


def crossover(father: ParentGenome, mother: ParentGenome, species: str = "human") -> dict:
    """
    孟德尔杂交：从父母各取一个等位基因。

    Returns:
        子代基因型 dict: {trait_name: (allele_from_father, allele_from_mother)}
    """
    trait_defs = SPECIES_TRAITS.get(species, HUMAN_TRAITS)
    child = {}
    for name in trait_defs:
        f_alleles = father.traits.get(name, (trait_defs[name]["alleles"][0],) * 2)
        m_alleles = mother.traits.get(name, (trait_defs[name]["alleles"][0],) * 2)
        child[name] = (random.choice(f_alleles), random.choice(m_alleles))
    return child


def genotype_to_phenotype(genotype: dict, species: str = "human") -> dict:
    """
    基因型 → 表现型。

    规则：
    - simple: 显性值更高的等位基因胜出
    - incomplete: 不同等位基因时取中间值（如 dark+light → medium）
    - codominant: 两个不同的非隐性等位基因共同表达（如 A+B → AB）
    """
    trait_defs = SPECIES_TRAITS.get(species, HUMAN_TRAITS)
    phenotype = {}

    for name, (a1, a2) in genotype.items():
        config = trait_defs.get(name)
        if not config:
            phenotype[name] = a1
            continue

        mode = config["mode"]
        dom = config["dominance"]

        if a1 == a2:
            phenotype[name] = a1
            continue

        if mode == "simple":
            # 显性值高的胜出
            phenotype[name] = a1 if dom.get(a1, 0) >= dom.get(a2, 0) else a2

        elif mode == "incomplete":
            # 不完全显性：取中间值
            alleles = config["alleles"]
            i1 = alleles.index(a1) if a1 in alleles else 0
            i2 = alleles.index(a2) if a2 in alleles else 0
            mid = round((i1 + i2) / 2)
            phenotype[name] = alleles[min(mid, len(alleles) - 1)]

        elif mode == "codominant":
            # 共显性：如 A+B → AB, A+O → A
            d1, d2 = dom.get(a1, 0), dom.get(a2, 0)
            if d1 > 0 and d2 > 0 and a1 != a2:
                phenotype[name] = f"{a1}{a2}"  # AB
            elif d1 >= d2:
                phenotype[name] = a1
            else:
                phenotype[name] = a2

        else:
            phenotype[name] = a1

    return phenotype


# 影响发育和资源分配的性状；其余（如 earwax/dimples/freckles）仅为外观，
# 记录在 gestation_log 但不注入 prompt 浪费 token
_DEVELOPMENTAL_TRAITS = {
    "eye_color", "hair_type", "hair_color", "skin_tone",
    "height_tendency", "metabolism_type", "blood_type_abo",
}


def format_genetics_for_prompt(genotype: dict, phenotype: dict) -> str:
    """生成 LLM prompt 注入文本：仅发育相关的遗传基因型信息。"""
    lines = ["## Genetic Inheritance"]
    lines.append("This individual's traits are inherited from parents:")
    for name, (a1, a2) in genotype.items():
        if name not in _DEVELOPMENTAL_TRAITS:
            continue
        expressed = phenotype.get(name, "?")
        lines.append(f"- {name}: genotype ({a1}/{a2}) → expressed as {expressed}")
    return "\n".join(lines)
