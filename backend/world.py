"""
世界层 -- 日程模板 + 事件路由 + 事件处理。

为 DES 调度器提供每日日程生成和事件处理能力。
世界向 Agent 推送事件，Agent 感知并反应。

[INPUT]: 依赖 events/ 共享事件系统，cradle/state.py BabyState
[OUTPUT]: generate_daily_schedule(), process_event(), select_template(), 标签规则
[POS]: 顶级模块，被 scheduler.py 消费
[PROTOCOL]: 变更时更新此头部，然后检查 CLAUDE.md
"""

from __future__ import annotations

import random

from events.definitions import get_event


# ============================================================
# 日程模板 -- 每个模板是 (事件名, 基准小时) 的列表
# ============================================================

SCHEDULE_TEMPLATES: dict[str, list[tuple[str, float]]] = {
    # 新生儿（phase 0-1）：吃睡循环
    "infant": [
        ("wake_up",    6.0),
        ("feeding",    7.0),
        ("nap",        9.0),
        ("feeding",   12.0),
        ("nap",       13.5),
        ("feeding",   17.0),
        ("bath",      19.0),
        ("sleep",     20.0),
    ],
    # 幼儿（phase 2-4）：有更多活动
    "toddler": [
        ("wake_up",    6.5),
        ("breakfast",  7.0),
        ("morning_play", 9.0),
        ("lunch",     12.0),
        ("nap",       13.0),
        ("afternoon_activity", 15.0),
        ("dinner",    18.0),
        ("bath",      19.0),
        ("sleep",     20.0),
    ],
    # 学龄前在家（phase 5-8, 无 enrolled_school）
    "preschool_home": [
        ("wake_up",    7.0),
        ("breakfast",  7.5),
        ("morning_play", 9.0),
        ("lunch",     12.0),
        ("nap",       13.0),
        ("afternoon_activity", 15.0),
        ("dinner",    18.0),
        ("family_time", 19.0),
        ("sleep",     20.5),
    ],
    # 学龄（phase 9+, enrolled_school）
    "school_age": [
        ("wake_up",    6.5),
        ("breakfast",  7.0),
        ("school_morning", 8.5),
        ("lunch",     12.0),
        ("school_afternoon", 13.0),
        ("after_school", 16.0),
        ("dinner",    18.0),
        ("homework",  19.0),
        ("family_time", 20.0),
        ("sleep",     21.0),
    ],
}


# ============================================================
# 阶段自动标签规则 -- phase -> 自动添加的标签
# ============================================================

PHASE_AUTO_TAGS: dict[int, set[str]] = {
    4: {"can_walk"},           # Motor Explosion
    5: {"can_talk_basic"},     # First Words
    6: {"can_talk"},           # Language Explosion
    9: {"enrolled_school"},    # Rule Understanding (4-5 岁，默认上学)
}


# ============================================================
# 能力解锁 -> 标签映射
# ============================================================

CAPABILITY_TAGS: dict[str, str] = {
    "walk_first_steps": "can_walk",
    "social_smile": "social_awareness",
    "visual_tracking": "can_see_well",
    "sound_localization": "can_hear_well",
}


# ============================================================
# 关键事件决策 -> 标签变更
# ============================================================

DECISION_TAG_EFFECTS: dict[tuple[str, str], dict] = {
    ("pet_encounter", "adopt"): {"add": {"has_pet"}},
    ("kindergarten_entry", "enroll"): {"add": {"enrolled_school"}},
    ("kindergarten_entry", "delay"): {"remove": {"enrolled_school"}},
    ("room_separation", "separate"): {"add": {"own_room"}},
}


# ============================================================
# 模板选择
# ============================================================

def select_template(phase: int, life_tags: set[str]) -> str:
    """根据阶段和标签选择日程模板名。"""
    if phase <= 1:
        return "infant"
    if phase <= 4:
        return "toddler"
    if "enrolled_school" in life_tags:
        return "school_age"
    return "preschool_home"


# ============================================================
# 日程生成（含随机化）
# ============================================================

def generate_daily_schedule(
    phase: int,
    life_tags: set[str],
    day_offset: float = 0.0,
) -> list[tuple[str, float]]:
    """
    生成一天的日程事件列表。

    Args:
        phase: 当前阶段
        life_tags: 生活上下文标签
        day_offset: 当天的模拟时间偏移（sim_time 中的天起始小时数）

    Returns:
        [(event_name, sim_time), ...] 按时间排序
    """
    template_name = select_template(phase, life_tags)
    template = SCHEDULE_TEMPLATES[template_name]

    schedule = []
    prev_time = -1.0
    for event_name, base_hour in template:
        # +-0.5 小时随机偏移
        offset = random.uniform(-0.5, 0.5)
        actual_hour = base_hour + offset
        # 保持先后顺序
        if actual_hour <= prev_time:
            actual_hour = prev_time + 0.25
        # 限制在 0-24 范围
        actual_hour = max(0.0, min(23.75, actual_hour))
        prev_time = actual_hour
        schedule.append((event_name, day_offset + actual_hour))

    return schedule


# ============================================================
# 事件处理（分层：规则引擎 vs LLM）
# ============================================================

# 日程事件的显示名映射
_DISPLAY_NAMES: dict[str, str] = {
    "wake_up": "Wake Up",
    "feeding": "Feeding",
    "breakfast": "Breakfast",
    "lunch": "Lunch",
    "dinner": "Dinner",
    "nap": "Nap",
    "sleep": "Sleep",
    "bath": "Bath",
    "morning_play": "Morning Play",
    "afternoon_activity": "Afternoon Activity",
    "after_school": "After School",
    "family_time": "Family Time",
    "school_morning": "School Morning",
    "school_afternoon": "School Afternoon",
    "homework": "Homework",
}


def process_event(event_name: str, state, sim_hour: float) -> dict:
    """
    处理一个事件，返回结果字典。

    日常/日程事件 -> 规则引擎（不调 LLM）
    环境/关键事件 -> 需要 LLM（返回标记，由调度器负责调 LLM）

    Returns:
        {
            "type": "routine" | "story",
            "event_name": str,
            "display_name": str,
            "sim_hour": float,
            "changes": dict,           # 状态变化
            "needs_llm": bool,         # 是否需要 LLM 处理
            "event": Event | None,     # 原始事件对象（供 LLM 使用）
        }
    """
    # 查找事件对象
    event_obj = get_event(event_name)
    display_name = _DISPLAY_NAMES.get(
        event_name,
        event_obj.display_name if event_obj else event_name,
    )

    # 环境/关键事件 -> 需要 LLM
    if event_obj and event_obj.category in ("environment", "critical"):
        return {
            "type": "story",
            "event_name": event_name,
            "display_name": display_name,
            "sim_hour": sim_hour,
            "changes": {},
            "needs_llm": True,
            "event": event_obj,
        }

    # 学校/作业事件 -> 需要 LLM（有"事"的事件）
    if event_name in ("school_morning", "school_afternoon", "homework"):
        return {
            "type": "story",
            "event_name": event_name,
            "display_name": display_name,
            "sim_hour": sim_hour,
            "changes": {},
            "needs_llm": True,
            "event": event_obj,
        }

    # ---- 规则引擎：日常/日程事件，不调 LLM ----
    changes: dict = {}

    if event_name in ("feeding", "breakfast", "lunch", "dinner"):
        # 轻微降低压力
        if hasattr(state, "stress") and state.stress is not None:
            new_level = max(0.0, state.stress.stress_level - 0.02)
            state.stress.stress_level = new_level
            changes["stress_level"] = round(new_level, 4)

    elif event_name in ("nap", "sleep"):
        # 睡眠质量微调，压力衰减
        if hasattr(state, "stress") and state.stress is not None:
            new_level = max(0.0, state.stress.stress_level - 0.05)
            state.stress.stress_level = new_level
            changes["stress_level"] = round(new_level, 4)
        if hasattr(state, "nutrition_sleep") and state.nutrition_sleep is not None:
            # 睡眠后质量略微回升
            new_quality = min(1.0, state.nutrition_sleep.sleep_quality + 0.01)
            state.nutrition_sleep.sleep_quality = new_quality
            changes["sleep_quality"] = round(new_quality, 4)

    elif event_name in ("morning_play", "afternoon_activity", "after_school"):
        # 情绪轻微提升（tantrum_frequency 降低）
        if hasattr(state, "emotional") and state.emotional is not None:
            new_freq = max(0.0, state.emotional.tantrum_frequency - 0.01)
            state.emotional.tantrum_frequency = new_freq
            changes["tantrum_frequency"] = round(new_freq, 4)

    elif event_name == "family_time":
        # 照护者 responsiveness 微增
        if hasattr(state, "caregivers") and state.caregivers:
            for cid, cg in state.caregivers.items():
                new_resp = min(1.0, cg.responsiveness + 0.01)
                cg.responsiveness = new_resp
                changes[f"caregiver_{cid}_responsiveness"] = round(new_resp, 4)

    # wake_up / bath: 无状态变化

    return {
        "type": "routine",
        "event_name": event_name,
        "display_name": display_name,
        "sim_hour": sim_hour,
        "changes": changes,
        "needs_llm": False,
        "event": event_obj,
    }
