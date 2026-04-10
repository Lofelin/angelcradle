"""
Fate engine: probability rolls using real-world data from species blueprints.

Every roll uses actual rates from WHO, Lancet, CDC, PubMed studies.
Environment modifiers affect probabilities at code level.
No retries. What happens, happens.

[INPUT]: species blueprints (YAML), environment dict, defects, placenta/hormones/immune state
[OUTPUT]: 导出 roll_miscarriage, roll_stage_miscarriage, roll_multiples, roll_stillbirth,
          roll_congenital_defects, roll_preterm, validate_resource_semantics, validate_defect_consistency
[POS]: womb/ 的命运引擎，被 __init__.py 和 stages.py 消费
[PROTOCOL]: 变更时更新此头部，然后检查 CLAUDE.md
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
# 逐阶段流产引擎（human 专用）
# ============================================================

# 条件积: 1 - prod(1 - p_i) ≈ 0.150，环境/缺陷修正进一步调制 → 接近 WHO 15.3%
HUMAN_STAGE_MISCARRIAGE_RATES = {
    "zygote":              0.058,   # 染色体异常、着床失败
    "early_organogenesis": 0.035,   # 遗传 + 营养（叶酸）
    "late_organogenesis":  0.023,   # 胎盘 + 致畸
    "early_neural":        0.018,   # 环境压力 + 免疫
    "late_neural":         0.012,   # 胎盘 + 激素
    "fetal_movement":      0.009,   # 累积风险
    # "birth" 不参与——由 roll_stillbirth() 单独处理
}

STAGE_RISK_FACTORS = {
    "zygote":              "chromosomal_and_implantation",
    "early_organogenesis": "genetic_and_nutritional",
    "late_organogenesis":  "placental_and_teratogenic",
    "early_neural":        "environmental_and_immune",
    "late_neural":         "placental_and_hormonal",
    "fetal_movement":      "cumulative",
}


def roll_stage_miscarriage(
    species: str,
    stage_name: str,
    env: dict,
    defects: list[dict],
    placenta: dict,
    hormones: dict,
    immune_risks: dict,
    nutrient_effects: dict,
    teratogen_risk: float,
) -> dict:
    """
    逐阶段流产判定。仅 human 支持；其他物种返回 {miscarriage: False}。

    每阶段的风险由该阶段特有的主导因子调制，加上全局 healthcare 保护因子。
    """
    if species != "human" or stage_name not in HUMAN_STAGE_MISCARRIAGE_RATES:
        return {"miscarriage": False, "stage": stage_name}

    base_rate = HUMAN_STAGE_MISCARRIAGE_RATES[stage_name]
    risk_modifier = 1.0

    # 阶段特定修正
    if stage_name == "zygote":
        # 遗传缺陷越多/越重，流产风险越高
        defect_severity_sum = sum(d.get("severity", 0.5) for d in defects)
        risk_modifier *= (1.0 + defect_severity_sum * 0.5)

    elif stage_name == "early_organogenesis":
        # 遗传 + 叶酸缺乏
        defect_count = len(defects)
        risk_modifier *= (1.0 + defect_count * 0.15)
        folate_penalty = nutrient_effects.get("risk_effects", {}).get("neural_tube_defect", 1.0)
        risk_modifier *= min(folate_penalty, 2.0)

    elif stage_name == "late_organogenesis":
        # 胎盘效率 + 致畸暴露
        placenta_eff = placenta.get("efficiency", 1.0)
        risk_modifier *= (1.0 + (1.0 - placenta_eff) * 1.5)
        risk_modifier *= min(teratogen_risk, 2.5)

    elif stage_name == "early_neural":
        # 环境压力 + 免疫风险
        stress = env.get("stress", "moderate")
        stress_mod = {"minimal": 0.7, "mild": 0.85, "moderate": 1.0, "high": 1.3, "severe": 1.8}
        risk_modifier *= stress_mod.get(stress, 1.0)
        immune_mod = immune_risks.get("miscarriage_modifier", 1.0)
        risk_modifier *= immune_mod

    elif stage_name == "late_neural":
        # 胎盘 + 激素失衡
        placenta_eff = placenta.get("efficiency", 1.0)
        risk_modifier *= (1.0 + (1.0 - placenta_eff) * 1.0)
        cortisol = hormones.get("cortisol", {}).get("level", 0.5)
        if cortisol > 0.7:
            risk_modifier *= (1.0 + (cortisol - 0.7) * 2.0)

    elif stage_name == "fetal_movement":
        # 累积风险：综合前面所有因子的弱化版
        placenta_eff = placenta.get("efficiency", 1.0)
        risk_modifier *= (1.0 + (1.0 - placenta_eff) * 0.8)
        cortisol = hormones.get("cortisol", {}).get("level", 0.5)
        if cortisol > 0.7:
            risk_modifier *= (1.0 + (cortisol - 0.7) * 1.0)

    # 全局 healthcare 保护因子
    healthcare = env.get("birthplace_modifiers", {}).get("healthcare_baseline", 0.5)
    risk_modifier *= max(0.3, 1.5 - healthcare)  # 0.92 → 0.58x; 0.15 → 1.35x

    adjusted_rate = min(base_rate * risk_modifier, 0.50)

    if roll(adjusted_rate):
        return {
            "miscarriage": True,
            "stage": stage_name,
            "cause": STAGE_RISK_FACTORS[stage_name],
            "base_rate": base_rate,
            "adjusted_rate": round(adjusted_rate, 4),
        }
    return {
        "miscarriage": False,
        "stage": stage_name,
        "base_rate": base_rate,
        "adjusted_rate": round(adjusted_rate, 4),
    }


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
