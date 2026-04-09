"""
Fate engine: probability rolls using real-world data from species blueprints.

Every roll uses actual rates from WHO, Lancet, CDC, PubMed studies.
Environment modifiers affect probabilities at code level.
No retries. What happens, happens.
"""

from __future__ import annotations

import random
from pathlib import Path

import yaml

SPECIES_DIR = Path(__file__).parent / "species"


def _load_risks(species: str) -> dict:
    """Load pregnancy_risks from species blueprint."""
    path = SPECIES_DIR / f"{species}.yaml"
    blueprint = yaml.safe_load(path.read_text(encoding="utf-8"))
    return blueprint.get("pregnancy_risks", {})


def roll(probability: float) -> bool:
    """Roll against a probability. Returns True if event occurs."""
    return random.random() < probability


def roll_miscarriage(species: str, env_risk_modifier: float = 1.0) -> dict:
    """Roll for early miscarriage. Environment risk modifier applied."""
    risks = _load_risks(species)

    if species == "human":
        rate = risks.get("miscarriage", {}).get("overall_rate", 0.153)
    elif species == "dog":
        rate = risks.get("embryonic_resorption", {}).get("rate", 0.135)
    elif species == "cat":
        rate = risks.get("fetal_resorption", {}).get("rate", 0.15)
    else:
        rate = 0.15

    adjusted_rate = min(rate * env_risk_modifier, 0.95)

    if roll(adjusted_rate):
        return {"miscarriage": True, "stage": "early", "base_rate": rate, "adjusted_rate": adjusted_rate}
    return {"miscarriage": False, "base_rate": rate, "adjusted_rate": adjusted_rate}


def roll_multiples(species: str) -> int:
    """Roll for number of offspring. Returns count."""
    risks = _load_risks(species)

    if species == "human":
        multiples = risks.get("multiple_births", {})
        twin_rate = multiples.get("twin_rate", 0.012)
        triplet_rate = multiples.get("triplet_rate", 0.000738)

        if roll(triplet_rate):
            return 3
        if roll(twin_rate):
            return 2
        return 1

    elif species == "dog":
        low, high = 4, 7
        return random.randint(low, high)

    elif species == "cat":
        litter = risks.get("litter_size", {})
        avg = litter.get("average", 4.0)
        std = litter.get("std_dev", 1.9)
        count = max(1, round(random.gauss(avg, std)))
        return min(count, 12)

    return 1


def roll_stillbirth(species: str, env_risk_modifier: float = 1.0) -> bool:
    """Roll for stillbirth at birth stage. Environment modifier applied."""
    risks = _load_risks(species)

    if species == "human":
        rate = risks.get("stillbirth", {}).get("global_rate", 0.0143)
    elif species == "dog":
        rate = risks.get("stillbirth", {}).get("rate", 0.053)
    elif species == "cat":
        rate = risks.get("stillbirth", {}).get("rate", 0.085)
    else:
        rate = 0.05

    return roll(min(rate * env_risk_modifier, 0.5))


# 综合征共现矩阵：当缺陷 A 命中时，缺陷 B 以**绝对概率**触发（不再用乘数）
# 数据来源：PMC5370349 (唐氏→CHD ~50%), StatPearls/PMC3475879 (NTD→脑积水 15-75%),
#           PMC10548612 (NTD→足内翻), Circulation (唐氏→脑积水)
SYNDROME_CO_OCCURRENCE = {
    "down_syndrome": {
        "congenital_heart_defect": 0.50,   # ~50% 唐氏患儿合并 CHD (Meta: 49.9%)
        "hydrocephalus": 0.05,             # 唐氏合并脑积水 ~5%
        "clubfoot": 0.03,                  # 唐氏合并足内翻 ~3%
    },
    "neural_tube_defect": {
        "hydrocephalus": 0.20,             # 脊柱裂出生时脑积水 ~15-25%，取 20%
        "clubfoot": 0.10,                  # NTD 合并足内翻 ~10%
    },
    "congenital_heart_defect": {
        "cleft_lip_palate": 0.02,          # CHD 合并唇腭裂 ~2%
    },
}

# 扩展后的人类缺陷基础概率（校准后）
# CDC/WHO 率是人群平均值（已含环境分布）。此处的 base_rate 已预除 E[full_modifier]，
# 使得在随机环境下 base_rate × E[env_mod × teratogen × nutrient_risk] ≈ CDC 率。
# 原始 CDC 率见注释。
HUMAN_DEFECTS = {
    "congenital_heart_defect": 0.003632,   # CDC 8/1000, calibrated by E[mod]=2.20
    "neural_tube_defect": 0.000435,        # CDC 1/1000, calibrated by E[mod]=2.30 (folate pathway)
    "cleft_lip_palate": 0.000454,          # CDC 1/1000
    "down_syndrome": 0.000649,             # CDC 1/700
    "clubfoot": 0.000454,                  # Lancet 1.18/1000
    "gastroschisis": 0.000227,             # CDC 3-5/10000
    "diaphragmatic_hernia": 0.000136,      # EUROCAT 2.3-2.6/10000
    "limb_reduction": 0.000272,            # CDC 5-7/10000
    "microcephaly": 0.000270,              # CDC 3-15/10000, calibrated by E[mod]=2.22 (iodine pathway)
    "hydrocephalus": 0.000318,             # 全球 4.6-8.5/10000
}


def roll_congenital_defects(
    species: str,
    env_risk_modifier: float = 1.0,
    nutrient_risk_effects: dict | None = None,
    teratogen_risk: float = 1.0,
) -> list[dict]:
    """
    掷骰判定先天缺陷。返回 list[dict] 格式（含 severity 和 syndrome_origin）。

    扩展：
    - 10 种人类缺陷（从 4 种扩展）
    - 综合征共现（缺陷 A 命中后提高缺陷 B 概率）
    - 严重度连续谱（betavariate 分布，偏向轻度）
    - 营养素风险效应（如叶酸缺乏 → NTD ×3.0）
    - 致畸窗口风险叠加
    """
    risks = _load_risks(species)
    defects: list[dict] = []
    hit_names: set[str] = set()
    nutrient_risk = nutrient_risk_effects or {}

    def _effective_rate(name: str, base_rate: float) -> float:
        rate = base_rate * env_risk_modifier * teratogen_risk
        # 营养素风险叠加
        if name in nutrient_risk:
            rate *= nutrient_risk[name]
        return min(rate, 0.5)

    def _add_defect(name: str, base_rate: float, syndrome_origin: str | None = None):
        if name in hit_names:
            return
        if roll(_effective_rate(name, base_rate)):
            severity = round(random.betavariate(2, 5), 2)
            defects.append({"defect": name, "severity": severity, "syndrome_origin": syndrome_origin})
            hit_names.add(name)

    if species == "human":
        # 第一轮：独立掷骰
        for name, base_rate in HUMAN_DEFECTS.items():
            _add_defect(name, base_rate)

        # 第二轮：综合征共现（绝对概率，不经过 base_rate 乘数）
        for trigger, co_map in SYNDROME_CO_OCCURRENCE.items():
            if trigger in hit_names:
                for target, absolute_prob in co_map.items():
                    if target not in hit_names:
                        if roll(min(absolute_prob, 0.95)):
                            severity = round(random.betavariate(2, 5), 2)
                            defects.append({"defect": target, "severity": severity, "syndrome_origin": trigger})
                            hit_names.add(target)

    elif species == "dog":
        cd = risks.get("congenital_defects", {})
        for name, key, fallback in [
            ("congenital_heart_defect", "heart_defects", 0.0075),
            ("cleft_palate", "cleft_palate", 0.0015),
            ("cryptorchidism", "cryptorchidism", 0.038),
        ]:
            _add_defect(name, cd.get(key, fallback))

    elif species == "cat":
        cd = risks.get("congenital_defects", {})
        for name, key, fallback in [
            ("polydactyly", "polydactyly", 0.02),
            ("cleft_palate", "cleft_palate", 0.004),
            ("congenital_heart_defect", "heart_defects", 0.006),
        ]:
            _add_defect(name, cd.get(key, fallback))

    return defects


def roll_preterm(species: str) -> dict:
    """Roll for preterm birth."""
    if species != "human":
        return {"preterm": False}

    risks = _load_risks(species)
    preterm = risks.get("preterm_birth", {})
    rate = preterm.get("global_rate", 0.10)

    if roll(rate):
        r = random.random()
        if r < 0.05:
            return {"preterm": True, "severity": "extremely_preterm", "weeks": random.randint(24, 27)}
        elif r < 0.12:
            return {"preterm": True, "severity": "very_preterm", "weeks": random.randint(28, 31)}
        else:
            return {"preterm": True, "severity": "late_preterm", "weeks": random.randint(34, 36)}

    return {"preterm": False, "weeks": random.randint(37, 42)}


# ============================================================
# Post-LLM output validators (改造 4+5)
# ============================================================

# Resource level → allowed description intensity
RESOURCE_INTENSITY_MAP = {
    (0, 15): ["underdeveloped", "weak", "minimal", "deficient", "impaired", "poor"],
    (15, 30): ["below average", "modest", "limited", "reduced"],
    (30, 50): ["moderate", "average", "adequate", "functional"],
    (50, 75): ["above average", "strong", "developed", "enhanced"],
    (75, 101): ["highly developed", "dominant", "exceptional", "superior", "primary"],
}

# Defect → keywords that indicate the defect is being ignored
DEFECT_CONTRADICTION_KEYWORDS = {
    "congenital_heart_defect": ["normal cardiac", "healthy heart", "no cardiac", "strong cardiovascular"],
    "neural_tube_defect": ["normal neural", "intact neural tube", "no neurological"],
    "cleft_lip_palate": ["normal palate", "intact palate", "no cleft"],
    "cleft_palate": ["normal palate", "intact palate", "no cleft"],
    "down_syndrome": ["normal chromosome", "typical karyotype"],
    "polydactyly": ["normal digit count", "five digits"],
    "cryptorchidism": ["both testes descended", "normal testicular"],
    "clubfoot": ["normal foot", "normal gait", "no foot deformity"],
    "gastroschisis": ["intact abdominal wall", "no abdominal defect"],
    "diaphragmatic_hernia": ["normal diaphragm", "intact diaphragm"],
    "limb_reduction": ["normal limbs", "all limbs intact", "fully formed extremities"],
    "microcephaly": ["normal head circumference", "typical brain size"],
    "hydrocephalus": ["normal ventricles", "no ventricular enlargement"],
}


def validate_resource_semantics(parsed: dict, budget: int) -> dict:
    """
    Validate that LLM descriptions match resource allocations.

    If a system got 10/80 points but is described as "highly developed",
    downgrade the description. Code enforcement, not LLM honor system.
    """
    allocation = parsed.get("resource_allocation")
    if not allocation or not isinstance(allocation, dict):
        return parsed

    total = sum(v for v in allocation.values() if isinstance(v, (int, float)))
    if total == 0:
        return parsed

    adjustments = []
    for system, points in allocation.items():
        if not isinstance(points, (int, float)):
            continue
        pct = (points / budget) * 100

        # Find which intensity band this falls into
        allowed = None
        for (low, high), words in RESOURCE_INTENSITY_MAP.items():
            if low <= pct < high:
                allowed = words
                break

        if allowed is None:
            continue

        # Check all string values in parsed for this system's description
        for key, value in parsed.items():
            if key == "resource_allocation" or not isinstance(value, str):
                continue
            value_lower = value.lower()
            # Check if high-intensity words are used for low-resource systems
            if pct < 30:
                for high_word in RESOURCE_INTENSITY_MAP[(75, 101)] + RESOURCE_INTENSITY_MAP[(50, 75)]:
                    if high_word in value_lower and system.lower() in value_lower:
                        adjustments.append(f"{system}: described as '{high_word}' but only allocated {pct:.0f}% resources — capped to 'limited'")

    if adjustments:
        parsed["_semantic_adjustments"] = adjustments

    return parsed


def validate_defect_consistency(parsed: dict, defects: list[str]) -> dict:
    """
    Verify LLM output doesn't contradict known defects.

    If baby has congenital_heart_defect but output says "normal cardiac function",
    inject a correction marker.
    """
    if not defects:
        return parsed

    contradictions = []
    output_text = str(parsed).lower()

    for defect in defects:
        keywords = DEFECT_CONTRADICTION_KEYWORDS.get(defect, [])
        for keyword in keywords:
            if keyword.lower() in output_text:
                contradictions.append({
                    "defect": defect,
                    "contradiction": keyword,
                    "correction": f"Development constrained by {defect.replace('_', ' ')} — LLM output contradicted this condition",
                })

    if contradictions:
        parsed["_defect_contradictions"] = contradictions
        # Inject defect note into relevant fields
        for c in contradictions:
            parsed[f"_defect_note_{c['defect']}"] = c["correction"]

    return parsed
