"""
营养素系统：5 种关键营养素的生成、加权、阶段敏感性。

[INPUT]: 可选的营养素覆盖值
[OUTPUT]: 导出 generate_nutrients, compute_nutrition_label, get_stage_nutrient_effects, get_overall_nutrient_risk_effects, format_nutrients_for_prompt
[POS]: womb/ 的营养子系统，被 environment.py 和 stages.py 消费
[PROTOCOL]: 变更时更新此头部，然后检查 CLAUDE.md
"""

from __future__ import annotations

import random


# ============================================================
# 营养素-阶段敏感性配置
# ============================================================

NUTRIENT_STAGE_SENSITIVITY = {
    "folate": {
        "sensitive_stages": ["zygote", "early_organogenesis"],
        "target_system": "neural_tube",
        "deficiency_threshold": 0.35,
        "risk_effect": {"neural_tube_defect": 3.0},
        "budget_penalty": 0.05,
    },
    "iodine": {
        "sensitive_stages": ["early_neural", "late_neural"],
        "target_system": "thyroid_neural",
        "deficiency_threshold": 0.30,
        "risk_effect": {"microcephaly": 2.0},
        "budget_penalty": 0.04,
    },
    "iron": {
        "sensitive_stages": ["late_organogenesis", "early_neural", "late_neural", "fetal_movement", "birth"],
        "target_system": "hematopoietic",
        "deficiency_threshold": 0.30,
        "risk_effect": {},
        "budget_penalty": 0.06,
    },
    "dha": {
        "sensitive_stages": ["late_neural", "fetal_movement"],
        "target_system": "brain_development",
        "deficiency_threshold": 0.30,
        "risk_effect": {},
        "budget_penalty": 0.04,
    },
    "calcium": {
        "sensitive_stages": ["late_organogenesis", "fetal_movement"],
        "target_system": "skeletal",
        "deficiency_threshold": 0.30,
        "risk_effect": {},
        "budget_penalty": 0.03,
    },
}

# 综合 nutrition 标签的加权系数
NUTRITION_WEIGHTS = {
    "folate": 0.25,
    "iodine": 0.20,
    "iron": 0.20,
    "dha": 0.20,
    "calcium": 0.15,
}

# nutrition_score → 四档映射阈值
NUTRITION_THRESHOLDS = [
    (0.80, "excellent"),
    (0.55, "adequate"),
    (0.35, "moderate_deficiency"),
    (0.00, "severe_deficiency"),
]


def generate_nutrients(overrides: dict | None = None) -> dict:
    """生成 5 种营养素值。正态分布 N(0.65, 0.15), clamp [0.1, 1.0]。"""
    nutrients = {}
    for name in NUTRIENT_STAGE_SENSITIVITY:
        val = random.gauss(0.65, 0.15)
        nutrients[name] = round(max(0.1, min(1.0, val)), 2)

    if overrides:
        for name, val in overrides.items():
            if name in nutrients and isinstance(val, (int, float)):
                nutrients[name] = round(max(0.1, min(1.0, float(val))), 2)

    return nutrients


def compute_nutrition_label(nutrients: dict) -> str:
    """从 5 种营养素加权计算综合 nutrition 标签。"""
    score = sum(nutrients.get(n, 0.5) * w for n, w in NUTRITION_WEIGHTS.items())
    for threshold, label in NUTRITION_THRESHOLDS:
        if score >= threshold:
            return label
    return "severe_deficiency"


def get_stage_nutrient_effects(nutrients: dict, stage: str) -> dict:
    """
    返回当前阶段的营养素效应。

    Returns:
        {
            "budget_penalty": float,    # 总 budget 惩罚（叠加所有缺乏营养素）
            "risk_effects": dict,       # {defect_name: risk_multiplier}
            "deficient_nutrients": list, # 本阶段缺乏的敏感营养素
        }
    """
    total_penalty = 0.0
    risk_effects = {}
    deficient = []

    for nutrient, config in NUTRIENT_STAGE_SENSITIVITY.items():
        if stage not in config["sensitive_stages"]:
            continue

        value = nutrients.get(nutrient, 0.5)
        if value < config["deficiency_threshold"]:
            deficient.append(nutrient)
            total_penalty += config["budget_penalty"]
            for defect, multiplier in config["risk_effect"].items():
                # 取最大倍数（如果多个营养素影响同一缺陷）
                risk_effects[defect] = max(risk_effects.get(defect, 1.0), multiplier)

    return {
        "budget_penalty": round(total_penalty, 3),
        "risk_effects": risk_effects,
        "deficient_nutrients": deficient,
    }


def get_overall_nutrient_risk_effects(nutrients: dict) -> dict:
    """
    计算全阶段聚合的营养素风险效应。

    用于发育前的缺陷掷骰——取所有阶段中最大风险倍数。
    例如：叶酸缺乏 → neural_tube_defect ×3.0（无论当前阶段）。
    """
    risk_effects: dict[str, float] = {}
    for nutrient, config in NUTRIENT_STAGE_SENSITIVITY.items():
        value = nutrients.get(nutrient, 0.5)
        if value < config["deficiency_threshold"]:
            for defect, multiplier in config["risk_effect"].items():
                risk_effects[defect] = max(risk_effects.get(defect, 1.0), multiplier)
    return risk_effects


def format_nutrients_for_prompt(nutrients: dict, stage: str) -> str:
    """生成 LLM prompt 注入文本：当前阶段的营养素状态。"""
    effects = get_stage_nutrient_effects(nutrients, stage)

    lines = ["## Nutrient Status"]
    for name, value in nutrients.items():
        config = NUTRIENT_STAGE_SENSITIVITY[name]
        sensitive = stage in config["sensitive_stages"]
        status = "DEFICIENT" if name in effects["deficient_nutrients"] else ("adequate" if value >= 0.55 else "low")
        marker = " ⚠ CRITICAL for this stage" if sensitive and status == "DEFICIENT" else (" (sensitive this stage)" if sensitive else "")
        lines.append(f"- {name}: {value:.2f} [{status}]{marker}")

    if effects["deficient_nutrients"]:
        lines.append(f"\nNutrient deficiency impact: {', '.join(effects['deficient_nutrients'])} below threshold.")
        lines.append(f"Target systems affected: {', '.join(NUTRIENT_STAGE_SENSITIVITY[n]['target_system'] for n in effects['deficient_nutrients'])}")

    return "\n".join(lines)
