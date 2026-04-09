"""
胎盘建模：发育/衰退曲线 + 并发症 + budget 效率乘数。

[INPUT]: 当前阶段名
[OUTPUT]: 导出 init_placenta, update_placenta, get_placenta_budget_factor, format_placenta_for_prompt
[POS]: womb/ 的胎盘子系统，被 environment.py 和 stages.py 消费
[PROTOCOL]: 变更时更新此头部，然后检查 CLAUDE.md
"""

from __future__ import annotations

import random


# 胎盘效率曲线：阶段 → 基线效率
PLACENTA_EFFICIENCY_CURVE = {
    "zygote": 0.30,
    "early_organogenesis": 0.50,
    "late_organogenesis": 0.70,
    "early_neural": 0.85,
    "late_neural": 0.95,
    "fetal_movement": 1.00,
    "birth": 0.95,
}

# 胎盘并发症定义
PLACENTA_COMPLICATIONS = {
    "placenta_previa": {
        "probability": 0.005,
        "efficiency_reduction": 0.15,
        "onset_stages": ["late_organogenesis", "early_neural"],
        "description": "Placenta partially or fully covers the cervical opening",
    },
    "placental_abruption": {
        "probability": 0.01,
        "efficiency_reduction": 0.30,
        "onset_stages": ["fetal_movement", "birth"],
        "description": "Premature separation of placenta from uterine wall",
    },
    "placental_insufficiency": {
        "probability": 0.06,    # 真实 8-10% (StatPearls NBK563171)，取保守值 6%
        "efficiency_reduction": 0.25,
        "onset_stages": ["early_neural", "late_neural", "fetal_movement"],
        "description": "Reduced placental blood flow and nutrient transfer capacity",
    },
}


def init_placenta() -> dict:
    """初始化胎盘状态。"""
    return {
        "efficiency": 0.30,
        "complications": [],
        "complication_details": [],
    }


def update_placenta(state: dict, stage: str, env_risk_modifier: float = 1.0) -> dict:
    """
    更新胎盘状态：基线效率 + 并发症触发。

    Args:
        state: 当前胎盘状态
        stage: 当前发育阶段
        env_risk_modifier: 环境风险修正（影响并发症概率）

    Returns:
        更新后的胎盘状态
    """
    updated = dict(state)

    # 基线效率
    base_efficiency = PLACENTA_EFFICIENCY_CURVE.get(stage, 0.80)

    # 检查并发症触发
    for name, config in PLACENTA_COMPLICATIONS.items():
        if name in updated["complications"]:
            continue  # 已触发，不重复
        if stage not in config["onset_stages"]:
            continue
        adjusted_prob = min(config["probability"] * env_risk_modifier, 0.3)
        if random.random() < adjusted_prob:
            updated["complications"].append(name)
            updated["complication_details"].append({
                "complication": name,
                "triggered_at": stage,
                "efficiency_reduction": config["efficiency_reduction"],
            })

    # 计算有效效率：基线 - 所有并发症的减少量
    total_reduction = sum(
        PLACENTA_COMPLICATIONS[c]["efficiency_reduction"]
        for c in updated["complications"]
    )
    updated["efficiency"] = round(max(0.20, base_efficiency - total_reduction), 2)

    return updated


def get_placenta_budget_factor(state: dict) -> float:
    """返回当前胎盘效率作为 budget 乘数。"""
    return state.get("efficiency", 1.0)


def format_placenta_for_prompt(state: dict, stage: str) -> str:
    """生成 LLM prompt 注入文本：胎盘状态。"""
    efficiency = state.get("efficiency", 1.0)
    complications = state.get("complications", [])

    lines = [f"## Placental Status"]
    lines.append(f"- Placental efficiency: {efficiency:.0%}")

    if complications:
        for name in complications:
            config = PLACENTA_COMPLICATIONS.get(name, {})
            lines.append(f"- Complication: {name} — {config.get('description', '')}")
        lines.append("Reduced placental function constrains nutrient and oxygen delivery to the fetus.")
    else:
        base = PLACENTA_EFFICIENCY_CURVE.get(stage, 0.8)
        if base < 0.50:
            lines.append("Placenta is still immature — limited nutrient transfer capacity at this early stage.")

    return "\n".join(lines)
