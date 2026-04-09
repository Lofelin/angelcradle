"""
免疫交互：血型/Rh 不兼容 + TORCH 感染。

[INPUT]: 无（随机生成）
[OUTPUT]: 导出 generate_blood_types, check_rh_incompatibility, roll_torch_infections, get_immune_risk_modifiers, format_immunity_for_prompt
[POS]: womb/ 的免疫子系统，被 environment.py 和 stages.py 消费
[PROTOCOL]: 变更时更新此头部，然后检查 CLAUDE.md
"""

from __future__ import annotations

import random


# ============================================================
# 血型系统
# ============================================================

ABO_DISTRIBUTION = {
    "O": 0.44,
    "A": 0.28,
    "B": 0.20,
    "AB": 0.08,
}

RH_POSITIVE_RATE = 0.85  # 85% Rh+


def generate_blood_types() -> dict:
    """随机生成母亲和胎儿血型。"""
    def _random_blood():
        types = list(ABO_DISTRIBUTION.keys())
        weights = list(ABO_DISTRIBUTION.values())
        abo = random.choices(types, weights=weights, k=1)[0]
        rh = "+" if random.random() < RH_POSITIVE_RATE else "-"
        return {"abo": abo, "rh": rh}

    return {
        "maternal": _random_blood(),
        "fetal": _random_blood(),
    }


def check_rh_incompatibility(blood_types: dict) -> bool:
    """检查 Rh 不兼容：母 Rh- 且胎 Rh+。"""
    maternal = blood_types.get("maternal", {})
    fetal = blood_types.get("fetal", {})
    return maternal.get("rh") == "-" and fetal.get("rh") == "+"


# ============================================================
# TORCH 感染
# ============================================================

TORCH_INFECTIONS = {
    "toxoplasma": {
        "probability": 0.005,
        "stage_risk": {
            "early_organogenesis": 2.0,
            "late_organogenesis": 1.5,
        },
        "defect_boost": 1.5,
        "miscarriage_boost": 1.3,
        "description": "Toxoplasma gondii — risk of cerebral calcifications and chorioretinitis",
    },
    "rubella": {
        "probability": 0.001,
        "stage_risk": {
            "zygote": 3.0,
            "early_organogenesis": 4.0,
            "late_organogenesis": 2.0,
        },
        "defect_boost": 3.0,
        "miscarriage_boost": 2.0,
        "description": "Rubella virus — congenital rubella syndrome (deafness, cataracts, heart defects)",
    },
    "cmv": {
        "probability": 0.01,
        "stage_risk": {
            "early_neural": 2.0,
            "late_neural": 1.5,
        },
        "defect_boost": 1.8,
        "miscarriage_boost": 1.2,
        "description": "Cytomegalovirus — risk of sensorineural hearing loss and microcephaly",
    },
    "hsv": {
        "probability": 0.02,    # 母体孕期活动性生殖器疱疹 ~2% (PMC4164179)
        "stage_risk": {          # 传播主要在分娩期，首次感染传播率 ~30-50%，复发 <2%
            "birth": 2.5,
        },
        "defect_boost": 1.3,
        "miscarriage_boost": 1.1,
        "description": "Herpes simplex — active maternal genital herpes; neonatal transmission risk primarily during birth",
    },
}


def roll_torch_infections() -> list[str]:
    """概率触发 TORCH 感染。"""
    infections = []
    for name, config in TORCH_INFECTIONS.items():
        if random.random() < config["probability"]:
            infections.append(name)
    return infections


def get_immune_risk_modifiers(immunity: dict, stage: str) -> dict:
    """
    返回免疫因素对当前阶段的风险修正。

    Returns:
        {
            "defect_risk_boost": float,      # 缺陷风险额外倍数
            "miscarriage_risk_boost": float,  # 流产风险额外倍数
            "active_infections": list[str],   # 本阶段活跃的感染
        }
    """
    defect_boost = 1.0
    miscarriage_boost = 1.0
    active = []

    # TORCH 感染
    infections = immunity.get("torch_infections", [])
    for name in infections:
        config = TORCH_INFECTIONS.get(name, {})
        stage_risk = config.get("stage_risk", {})
        if stage in stage_risk:
            active.append(name)
            defect_boost = max(defect_boost, config.get("defect_boost", 1.0))
            miscarriage_boost = max(miscarriage_boost, config.get("miscarriage_boost", 1.0))

    # Rh 不兼容
    if immunity.get("rh_incompatible", False):
        # 简化：Rh 不兼容在所有阶段轻微增加风险
        defect_boost *= 1.2
        miscarriage_boost *= 1.15

    return {
        "defect_risk_boost": round(defect_boost, 2),
        "miscarriage_risk_boost": round(miscarriage_boost, 2),
        "active_infections": active,
    }


def generate_immunity() -> dict:
    """生成完整免疫状态。"""
    blood_types = generate_blood_types()
    rh_incompatible = check_rh_incompatibility(blood_types)
    torch = roll_torch_infections()

    return {
        "maternal_blood_type": blood_types["maternal"],
        "fetal_blood_type": blood_types["fetal"],
        "rh_incompatible": rh_incompatible,
        "torch_infections": torch,
    }


def format_immunity_for_prompt(immunity: dict, stage: str) -> str:
    """生成 LLM prompt 注入文本：免疫状态。"""
    lines = ["## Immune Status"]

    maternal = immunity.get("maternal_blood_type", {})
    fetal = immunity.get("fetal_blood_type", {})
    lines.append(f"- Maternal blood type: {maternal.get('abo', '?')}{maternal.get('rh', '?')}")
    lines.append(f"- Fetal blood type: {fetal.get('abo', '?')}{fetal.get('rh', '?')}")

    if immunity.get("rh_incompatible"):
        lines.append("- ⚠ Rh INCOMPATIBILITY: maternal Rh- carrying Rh+ fetus — risk of hemolytic disease")

    infections = immunity.get("torch_infections", [])
    if infections:
        for name in infections:
            config = TORCH_INFECTIONS.get(name, {})
            stage_risk = config.get("stage_risk", {})
            risk_at_stage = stage_risk.get(stage)
            if risk_at_stage:
                lines.append(f"- ⚠ ACTIVE INFECTION: {name} — {config.get('description', '')} (risk {risk_at_stage:.1f}x at this stage)")
            else:
                lines.append(f"- Infection present: {name} (not at peak risk this stage)")

    return "\n".join(lines)
