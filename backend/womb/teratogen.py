"""
致畸时间窗口：毒素类型定义 + 阶段-风险矩阵。

[INPUT]: toxin_exposure 等级、当前阶段
[OUTPUT]: 导出 assign_toxin_types, get_teratogen_risk, get_overall_teratogen_risk, format_teratogen_for_prompt
[POS]: womb/ 的致畸子系统，被 environment.py、fate.py 和 stages.py 消费
[PROTOCOL]: 变更时更新此头部，然后检查 CLAUDE.md
"""

from __future__ import annotations

import random


# ============================================================
# 毒素类型 × 阶段风险倍数矩阵
# 数值 = 该毒素在该阶段的致畸风险倍数（1.0 = 基线）
# ============================================================

TERATOGEN_STAGE_RISK = {
    "alcohol": {
        "zygote": 2.0,
        "early_organogenesis": 4.0,
        "late_organogenesis": 3.0,
        "early_neural": 2.5,
        "late_neural": 2.0,
        "fetal_movement": 1.5,
        "birth": 1.0,
    },
    "tobacco": {
        "zygote": 1.2,
        "early_organogenesis": 1.5,
        "late_organogenesis": 1.5,
        "early_neural": 1.3,
        "late_neural": 1.3,
        "fetal_movement": 2.2,   # FGR OR=1.9-2.5 (PMC5215872), 取中间值
        "birth": 1.5,
    },
    "heavy_metals": {
        "zygote": 1.5,
        "early_organogenesis": 3.0,
        "late_organogenesis": 2.5,
        "early_neural": 3.0,
        "late_neural": 2.0,
        "fetal_movement": 1.5,
        "birth": 1.0,
    },
    "medication": {
        "zygote": 1.3,
        "early_organogenesis": 3.5,
        "late_organogenesis": 2.5,
        "early_neural": 2.0,
        "late_neural": 1.5,
        "fetal_movement": 1.2,
        "birth": 1.0,
    },
    "radiation": {
        "zygote": 3.0,
        "early_organogenesis": 4.0,
        "late_organogenesis": 2.5,
        "early_neural": 3.5,
        "late_neural": 2.0,
        "fetal_movement": 1.5,
        "birth": 1.0,
    },
    "infection": {
        "zygote": 1.5,
        "early_organogenesis": 3.0,
        "late_organogenesis": 2.0,
        "early_neural": 2.5,
        "late_neural": 2.0,
        "fetal_movement": 1.5,
        "birth": 2.0,
    },
}

# toxin_exposure 等级 → 可能的毒素类型数量和权重
TOXIN_LEVEL_CONFIG = {
    "none": {"count": 0, "weights": {}},
    "mild": {
        "count": 1,
        "weights": {"tobacco": 3, "medication": 2, "alcohol": 1, "heavy_metals": 0.5, "radiation": 0.1, "infection": 1},
    },
    "moderate": {
        "count": (1, 2),
        "weights": {"alcohol": 3, "tobacco": 2, "medication": 2, "heavy_metals": 1, "radiation": 0.5, "infection": 1.5},
    },
    "severe": {
        "count": (1, 3),
        "weights": {"alcohol": 2, "tobacco": 2, "heavy_metals": 2, "medication": 1.5, "radiation": 1, "infection": 2},
    },
}


def assign_toxin_types(toxin_level: str) -> list[str]:
    """根据暴露等级随机选取毒素类型。"""
    config = TOXIN_LEVEL_CONFIG.get(toxin_level, TOXIN_LEVEL_CONFIG["none"])
    count = config["count"]
    if count == 0:
        return []

    if isinstance(count, tuple):
        count = random.randint(*count)

    weights = config["weights"]
    types = list(weights.keys())
    type_weights = [weights[t] for t in types]

    selected = set()
    for _ in range(count):
        chosen = random.choices(types, weights=type_weights, k=1)[0]
        selected.add(chosen)

    return sorted(selected)


def get_teratogen_risk(toxin_types: list[str], stage: str) -> float:
    """查询当前阶段所有毒素的最大风险倍数。"""
    if not toxin_types:
        return 1.0

    max_risk = 1.0
    for toxin in toxin_types:
        risk_map = TERATOGEN_STAGE_RISK.get(toxin, {})
        risk = risk_map.get(stage, 1.0)
        max_risk = max(max_risk, risk)

    return max_risk


def get_overall_teratogen_risk(toxin_types: list[str]) -> float:
    """
    计算全阶段聚合的致畸风险倍数。

    用于发育前的缺陷掷骰——取所有毒素在所有阶段的最大风险。
    """
    if not toxin_types:
        return 1.0

    max_risk = 1.0
    for toxin in toxin_types:
        risk_map = TERATOGEN_STAGE_RISK.get(toxin, {})
        for risk in risk_map.values():
            max_risk = max(max_risk, risk)
    return max_risk


def format_teratogen_for_prompt(toxin_types: list[str], stage: str) -> str:
    """生成 LLM prompt 注入文本：当前阶段的致畸风险。"""
    if not toxin_types:
        return ""

    lines = ["## Teratogenic Exposure"]
    for toxin in toxin_types:
        risk_map = TERATOGEN_STAGE_RISK.get(toxin, {})
        risk = risk_map.get(stage, 1.0)
        severity = "CRITICAL" if risk >= 3.0 else ("significant" if risk >= 2.0 else "moderate" if risk >= 1.5 else "low")
        lines.append(f"- {toxin}: risk multiplier {risk:.1f}x at this stage [{severity}]")

    max_risk = get_teratogen_risk(toxin_types, stage)
    if max_risk >= 3.0:
        lines.append(f"\n⚠ This is a PEAK VULNERABILITY WINDOW for teratogenic damage (max {max_risk:.1f}x).")
        lines.append("Development outcomes MUST reflect increased risk of structural anomalies.")

    return "\n".join(lines)
