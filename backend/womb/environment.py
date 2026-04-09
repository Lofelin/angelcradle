"""
母体环境：随机生成条件 + 量化修正系数。

环境不只是标签——每个条件产生量化修正，在代码层强制执行于资源预算和风险概率。
现已集成营养素细分和致畸毒素类型。

[INPUT]: 可选的环境参数覆盖
[OUTPUT]: 导出 generate_environment, compute_modifiers, get_effective_budget, format_environment 等
[POS]: womb/ 的环境基础设施，被 stages.py、fate.py 和 __init__.py 消费
[PROTOCOL]: 变更时更新此头部，然后检查 CLAUDE.md
"""

from __future__ import annotations

import random

from .nutrients import generate_nutrients, compute_nutrition_label
from .teratogen import assign_toxin_types
from .placenta import init_placenta
from .immunity import generate_immunity


# ============================================================
# 环境等级及权重
# ============================================================

NUTRITION_LEVELS = [
    ("excellent", 0.20),
    ("adequate", 0.50),
    ("moderate_deficiency", 0.20),
    ("severe_deficiency", 0.10),
]

STRESS_LEVELS = [
    ("minimal", 0.25),
    ("mild", 0.35),
    ("moderate", 0.25),
    ("severe", 0.15),
]

TOXIN_EXPOSURES = [
    ("none", 0.60),
    ("mild", 0.25),
    ("moderate", 0.10),
    ("severe", 0.05),
]

# ============================================================
# 量化修正系数
# ============================================================

# 归一化 modifier：E[modifier] = 1.0 across random environment distribution.
# CDC/WHO 基线率已含环境分布，modifier 表示相对于人群平均的偏移。
# optimal 环境 > 1.0（保护性），severe 环境 < 1.0（风险性）。
BUDGET_MODIFIERS = {
    "nutrition": {
        "excellent": 1.1053,
        "adequate": 1.0526,
        "moderate_deficiency": 0.8947,
        "severe_deficiency": 0.7368,
    },
    "stress": {
        "minimal": 1.0701,
        "mild": 1.0380,
        "moderate": 0.9631,
        "severe": 0.8561,
    },
    "toxin_exposure": {
        "none": 1.0444,
        "mild": 0.9922,
        "moderate": 0.8877,
        "severe": 0.7311,
    },
    "maternal_age_factor": {
        "very_young": 0.9446,
        "optimal": 1.0267,
        "moderate": 0.9959,
        "advanced": 0.9548,
        "very_advanced": 0.8727,
    },
}

DEFECT_RISK_MODIFIERS = {
    "toxin_exposure": {
        "none": 0.7692,
        "mild": 1.0,
        "moderate": 1.5385,
        "severe": 2.6923,
    },
    "maternal_age_factor": {
        "very_young": 0.9160,
        "optimal": 0.7634,
        "moderate": 0.9924,
        "advanced": 1.5267,
        "very_advanced": 2.6718,
    },
}

MISCARRIAGE_RISK_MODIFIERS = {
    "stress": {
        "minimal": 0.8889,
        "mild": 0.8889,
        "moderate": 1.0667,
        "severe": 1.3333,
    },
    "maternal_age_factor": {
        "very_young": 1.0092,
        "optimal": 0.9174,
        "moderate": 1.0092,
        "advanced": 1.1927,
        "very_advanced": 1.4679,
    },
}

MULTI_FETUS_BUDGET_FACTOR = {
    1: 1.0,
    2: 0.55,
    3: 0.40,
    4: 0.32,
    5: 0.27,
    6: 0.23,
}


def _weighted_choice(options: list[tuple[str, float]]) -> str:
    labels, weights = zip(*options)
    return random.choices(labels, weights=weights, k=1)[0]


def generate_environment(
    nutrition: str | None = None,
    stress: str | None = None,
    toxin_exposure: str | None = None,
    maternal_age_factor: str | None = None,
    nutrients: dict | None = None,
) -> dict:
    """
    生成母体环境。可选参数覆盖随机掷骰。

    新增：nutrients 子字典（5 种营养素）和 toxin_types 列表。
    nutrition 字符串从 nutrients 加权计算，保持向后兼容。
    """
    valid_stress = {v for v, _ in STRESS_LEVELS}
    valid_toxin = {v for v, _ in TOXIN_EXPOSURES}
    valid_age = {"very_young", "optimal", "moderate", "advanced", "very_advanced"}

    # 营养素细分：先生成 nutrients，再计算综合 nutrition 标签
    nutrient_values = generate_nutrients(nutrients)
    nutrition_label = compute_nutrition_label(nutrient_values)

    # 如果显式传入旧的 nutrition 参数，保留它（向后兼容）
    valid_nutrition = {v for v, _ in NUTRITION_LEVELS}
    if nutrition in valid_nutrition:
        nutrition_label = nutrition

    # 毒素
    toxin_level = toxin_exposure if toxin_exposure in valid_toxin else _weighted_choice(TOXIN_EXPOSURES)
    toxin_types = assign_toxin_types(toxin_level)

    env = {
        "nutrition": nutrition_label,
        "stress": stress if stress in valid_stress else _weighted_choice(STRESS_LEVELS),
        "toxin_exposure": toxin_level,
        "maternal_age_factor": maternal_age_factor if maternal_age_factor in valid_age else _random_age_factor(),
        "nutrients": nutrient_values,
        "toxin_types": toxin_types,
        "placenta": init_placenta(),
        "immunity": generate_immunity(),
    }
    env["modifiers"] = compute_modifiers(env)
    return env


def _random_age_factor() -> str:
    r = random.random()
    if r < 0.05:
        return "very_young"
    elif r < 0.60:
        return "optimal"
    elif r < 0.85:
        return "moderate"
    elif r < 0.95:
        return "advanced"
    else:
        return "very_advanced"


def compute_modifiers(env: dict) -> dict:
    """从环境标签计算量化修正系数。"""
    budget_mod = 1.0
    for factor, levels in BUDGET_MODIFIERS.items():
        budget_mod *= levels.get(env.get(factor, ""), 1.0)

    defect_risk_mod = 1.0
    for factor, levels in DEFECT_RISK_MODIFIERS.items():
        defect_risk_mod *= levels.get(env.get(factor, ""), 1.0)

    miscarriage_risk_mod = 1.0
    for factor, levels in MISCARRIAGE_RISK_MODIFIERS.items():
        miscarriage_risk_mod *= levels.get(env.get(factor, ""), 1.0)

    return {
        "budget_multiplier": round(budget_mod, 3),
        "defect_risk_multiplier": round(defect_risk_mod, 3),
        "miscarriage_risk_multiplier": round(miscarriage_risk_mod, 3),
    }


def get_effective_budget(base_budget: int, env: dict, offspring_count: int = 1) -> int:
    """有效预算 = 基础 × 环境修正 × 多胎系数。"""
    env_mod = env.get("modifiers", {}).get("budget_multiplier", 1.0)
    fetus_factor = MULTI_FETUS_BUDGET_FACTOR.get(offspring_count, 0.20)
    return max(1, round(base_budget * env_mod * fetus_factor))


def get_defect_risk_modifier(env: dict) -> float:
    return env.get("modifiers", {}).get("defect_risk_multiplier", 1.0)


def get_miscarriage_risk_modifier(env: dict) -> float:
    return env.get("modifiers", {}).get("miscarriage_risk_multiplier", 1.0)


def format_environment(env: dict) -> str:
    """格式化环境信息注入 LLM prompt。"""
    lines = [
        f"- Maternal nutrition: {env.get('nutrition', 'unknown')}",
        f"- Maternal stress level: {env.get('stress', 'unknown')}",
        f"- Environmental toxin exposure: {env.get('toxin_exposure', 'unknown')}",
        f"- Maternal age factor: {env.get('maternal_age_factor', 'unknown')}",
    ]
    modifiers = env.get("modifiers", {})
    if modifiers:
        lines.append(f"- Effective resource modifier: {modifiers.get('budget_multiplier', 1.0):.0%} of baseline")
        lines.append(f"- Defect risk modifier: {modifiers.get('defect_risk_multiplier', 1.0):.1f}x baseline")

    # 毒素类型
    toxin_types = env.get("toxin_types", [])
    if toxin_types:
        lines.append(f"- Active teratogens: {', '.join(toxin_types)}")

    return "\n".join(lines)


def environment_impact_text(env: dict) -> str:
    """生成环境对发育影响的描述文本。"""
    impacts = []
    modifiers = env.get("modifiers", {})
    budget_mod = modifiers.get("budget_multiplier", 1.0)

    if budget_mod < 0.80:
        impacts.append(f"Severely constrained uterine environment (resource capacity at {budget_mod:.0%}). "
                       "Multiple developmental systems will be below optimal.")
    elif budget_mod < 0.95:
        impacts.append(f"Moderately constrained environment (resource capacity at {budget_mod:.0%}). "
                       "Some developmental tradeoffs will be sharper than normal.")

    if env.get("stress") in ("moderate", "severe"):
        impacts.append("Elevated maternal cortisol crosses the placenta, shifting fetal arousal baseline upward "
                       "and potentially accelerating neural pruning.")
    if env.get("toxin_exposure") in ("moderate", "severe"):
        risk_mod = modifiers.get("defect_risk_multiplier", 1.0)
        impacts.append(f"Teratogenic exposure active (defect risk at {risk_mod:.1f}x baseline). "
                       "Organogenesis stage particularly vulnerable.")
    if env.get("maternal_age_factor") in ("advanced", "very_advanced"):
        impacts.append("Advanced maternal age reduces placental efficiency and increases chromosomal risk.")

    if not impacts:
        impacts.append("Favorable uterine environment. Development proceeds without significant external constraints.")

    return " ".join(impacts)
