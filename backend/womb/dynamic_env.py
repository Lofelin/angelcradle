"""
动态环境引擎：阶段间环境变化 + 母体反馈数值化。

[INPUT]: 当前 env 字典、母体反馈 LLM 输出
[OUTPUT]: 导出 roll_env_change, apply_maternal_feedback
[POS]: womb/ 的动态环境子系统，被 stages.py 消费
[PROTOCOL]: 变更时更新此头部，然后检查 CLAUDE.md
"""

from __future__ import annotations

import random
from .nutrients import generate_nutrients, compute_nutrition_label


# ============================================================
# 环境变化事件类型及权重
# ============================================================

ENV_CHANGE_TYPES = {
    "stress_increase": {"field": "stress", "direction": "up", "weight": 2.0},
    "stress_decrease": {"field": "stress", "direction": "down", "weight": 1.5},
    "nutrition_worsen": {"field": "nutrients", "direction": "down", "weight": 1.5},
    "nutrition_improve": {"field": "nutrients", "direction": "up", "weight": 1.0},
    "toxin_onset": {"field": "toxin_exposure", "direction": "up", "weight": 1.0},
    "toxin_end": {"field": "toxin_exposure", "direction": "down", "weight": 0.8},
}

# 等级标尺
STRESS_SCALE = ["minimal", "mild", "moderate", "severe"]
TOXIN_SCALE = ["none", "mild", "moderate", "severe"]


def _shift_level(current: str, direction: str, scale: list[str]) -> str:
    """等级单步移动。"""
    idx = scale.index(current) if current in scale else 0
    if direction == "up":
        return scale[min(idx + 1, len(scale) - 1)]
    else:
        return scale[max(idx - 1, 0)]


def _shift_nutrients(nutrients: dict, direction: str) -> dict:
    """随机调整 1-2 种营养素 ±0.10~0.15。"""
    keys = list(nutrients.keys())
    count = random.randint(1, 2)
    targets = random.sample(keys, min(count, len(keys)))

    updated = dict(nutrients)
    for key in targets:
        delta = random.uniform(0.10, 0.15)
        if direction == "down":
            delta = -delta
        updated[key] = round(max(0.1, min(1.0, updated[key] + delta)), 2)

    return updated


def roll_env_change(env: dict, probability: float = 0.20) -> tuple[dict, dict | None]:
    """
    掷骰判定环境变化。

    Args:
        env: 当前环境字典
        probability: 触发概率（默认 20%/阶段）

    Returns:
        (updated_env, event_record) — event_record 为 None 表示无变化
    """
    if random.random() > probability:
        return env, None

    # 选择变化类型（加权随机）
    types = list(ENV_CHANGE_TYPES.keys())
    weights = [ENV_CHANGE_TYPES[t]["weight"] for t in types]

    # 过滤无效变化（已在极端则不能继续推）
    valid = []
    valid_weights = []
    for t, w in zip(types, weights):
        config = ENV_CHANGE_TYPES[t]
        field = config["field"]
        direction = config["direction"]

        if field == "stress":
            current = env.get("stress", "mild")
            if direction == "up" and current == "severe":
                continue
            if direction == "down" and current == "minimal":
                continue
        elif field == "toxin_exposure":
            current = env.get("toxin_exposure", "none")
            if direction == "up" and current == "severe":
                continue
            if direction == "down" and current == "none":
                continue

        valid.append(t)
        valid_weights.append(w)

    if not valid:
        return env, None

    chosen = random.choices(valid, weights=valid_weights, k=1)[0]
    config = ENV_CHANGE_TYPES[chosen]
    field = config["field"]
    direction = config["direction"]

    # 应用变化
    updated = dict(env)
    event = {"type": chosen, "field": field, "direction": direction}

    if field == "stress":
        old = env.get("stress", "mild")
        new = _shift_level(old, direction, STRESS_SCALE)
        updated["stress"] = new
        event["old"] = old
        event["new"] = new
    elif field == "toxin_exposure":
        old = env.get("toxin_exposure", "none")
        new = _shift_level(old, direction, TOXIN_SCALE)
        updated["toxin_exposure"] = new
        event["old"] = old
        event["new"] = new
        # 毒素等级变化时重新分配毒素类型
        if new == "none":
            updated["toxin_types"] = []
        else:
            from .teratogen import assign_toxin_types
            updated["toxin_types"] = assign_toxin_types(new)
        event["toxin_types"] = updated.get("toxin_types", [])
    elif field == "nutrients":
        old_nutrients = env.get("nutrients", {})
        new_nutrients = _shift_nutrients(old_nutrients, direction)
        updated["nutrients"] = new_nutrients
        updated["nutrition"] = compute_nutrition_label(new_nutrients)
        event["old_nutrition"] = env.get("nutrition", "adequate")
        event["new_nutrition"] = updated["nutrition"]
        event["changed_nutrients"] = {
            k: {"old": old_nutrients.get(k), "new": new_nutrients.get(k)}
            for k in new_nutrients if old_nutrients.get(k) != new_nutrients.get(k)
        }

    # 重新计算 modifiers
    from .environment import compute_modifiers
    updated["modifiers"] = compute_modifiers(updated)

    return updated, event


def apply_maternal_feedback(env: dict, maternal_response: dict) -> tuple[dict, dict | None]:
    """
    解析 LLM 母体反馈，数值化修改 budget_multiplier。

    Returns:
        (updated_env, adjustment_record) — adjustment_record 为 None 表示 neutral
    """
    text = str(maternal_response.get("updated_environment_modifier", "")).lower()
    current = env.get("modifiers", {}).get("budget_multiplier", 1.0)

    if any(kw in text for kw in ("better", "improved", "favorable", "enhanced", "increased efficiency")):
        delta = round(random.uniform(0.01, 0.03), 3)
        direction = "better"
    elif any(kw in text for kw in ("worse", "deteriorated", "declined", "stressed", "reduced", "constrained")):
        delta = -round(random.uniform(0.01, 0.05), 3)
        direction = "worse"
    else:
        return env, None

    new_val = round(max(0.50, min(1.20, current + delta)), 3)
    updated = dict(env)
    updated.setdefault("modifiers", {})["budget_multiplier"] = new_val

    record = {
        "direction": direction,
        "delta": delta,
        "old_budget_multiplier": current,
        "new_budget_multiplier": new_val,
    }
    return updated, record
