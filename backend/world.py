"""
世界层 -- 日程模板 + 事件路由 + 事件处理 + 世界快照。

为 DES 调度器提供每日日程生成、事件处理、世界上下文驱动的涌现事件能力。
世界向 Agent 推送事件，Agent 感知并反应。

[INPUT]: 依赖 events/ 共享事件系统，cradle/state.py BabyState，cradle/mind.py _call_and_parse
[OUTPUT]: generate_daily_schedule(), process_event(), select_template(), roll_environment(),
          is_story_worthy(), template_reaction(), 标签规则,
          WorldSnapshot, SnapshotEvent, generate_world_snapshot(), pick_daily_event(),
          snapshot_event_to_event(), roll_emergent_event_legacy(), infer_season(), SNAPSHOT_INTERVAL
[POS]: 顶级模块，被 scheduler.py 消费
[PROTOCOL]: 变更时更新此头部，然后检查 CLAUDE.md
"""

from __future__ import annotations

import logging
import random
from dataclasses import dataclass, field

from events import Event
from events.definitions import get_event

logger = logging.getLogger(__name__)


# ============================================================
# 工具函数
# ============================================================

def _clamp_stress(state, delta: float) -> None:
    """安全地修改 stress_level，确保结果在 [0.0, 1.0] 范围内。"""
    if hasattr(state, "stress") and state.stress is not None:
        state.stress.stress_level = max(
            0.0, min(1.0, state.stress.stress_level + delta),
        )


# ============================================================
# 世界快照数据模型
# ============================================================

@dataclass
class SnapshotEvent:
    """快照中的一个候选涌现事件（LLM 生成）。"""
    name: str                    # lowercase_snake_case 标识
    display_name: str            # 显示名（中文）
    description: str             # 1-2 句话描述
    sensory_channels: list[str]  # 涉及的感官通道
    intensity: float             # 0-1 刺激强度
    day_index: int               # 周期中第几天（0-based），-1 = surprise
    category: str = "environment"

    def to_dict(self) -> dict:
        return {
            "name": self.name,
            "display_name": self.display_name,
            "description": self.description,
            "sensory_channels": self.sensory_channels,
            "intensity": self.intensity,
            "day_index": self.day_index,
            "category": self.category,
        }


@dataclass
class WorldSnapshot:
    """N 天的世界状态快照（LLM 生成，缓存在 BabyState 上）。"""
    start_day: int                      # 覆盖的起始天
    end_day: int                        # 结束天（exclusive）
    weather_pattern: str                # 天气模式
    family_arc: str                     # 家庭事件弧线
    ambient_mood: str                   # 环境氛围
    events: list[SnapshotEvent] = field(default_factory=list)
    surprise_pool: list[SnapshotEvent] = field(default_factory=list)
    used_events: set[str] = field(default_factory=set)  # 周期内已使用

    def to_dict(self) -> dict:
        return {
            "start_day": self.start_day,
            "end_day": self.end_day,
            "weather_pattern": self.weather_pattern,
            "family_arc": self.family_arc,
            "ambient_mood": self.ambient_mood,
            "events": [e.to_dict() for e in self.events],
            "surprise_pool": [e.to_dict() for e in self.surprise_pool],
            "used_events": sorted(self.used_events),
        }


def _parse_snapshot_event(d: dict) -> SnapshotEvent:
    return SnapshotEvent(
        name=d.get("name", "unknown"),
        display_name=d.get("display_name", d.get("name", "?")),
        description=d.get("description", ""),
        sensory_channels=d.get("sensory_channels", []),
        intensity=float(d.get("intensity", 0.3)),
        day_index=int(d.get("day_index", -1)),
        category=d.get("category", "environment"),
    )


def snapshot_from_dict(d: dict) -> WorldSnapshot:
    """从 JSON dict 恢复 WorldSnapshot。"""
    return WorldSnapshot(
        start_day=d.get("start_day", 0),
        end_day=d.get("end_day", 0),
        weather_pattern=d.get("weather_pattern", ""),
        family_arc=d.get("family_arc", ""),
        ambient_mood=d.get("ambient_mood", ""),
        events=[_parse_snapshot_event(e) for e in d.get("events", [])],
        surprise_pool=[_parse_snapshot_event(e) for e in d.get("surprise_pool", [])],
        used_events=set(d.get("used_events", [])),
    )


def snapshot_event_to_event(se: SnapshotEvent) -> Event:
    """将 SnapshotEvent 转换为 Event，供 is_story_worthy / template_reaction / _generate_story 消费。"""
    return Event(
        name=se.name,
        category=se.category,
        display_name=se.display_name,
        description=se.description,
        sensory_channels=se.sensory_channels,
        intensity=se.intensity,
        requires_parent=False,
        phase_range=(0, 11),
        weight=1.0,
    )


# ============================================================
# 快照周期：按阶段可变（默认 / slow / normal）
# ============================================================

SNAPSHOT_INTERVAL: dict[int, int] = {
    0: 14,   # Neonatal (30天) — 吃睡循环，世界稳定
    1: 14,   # Sensory Awakening (60天)
    2: 7,    # Body Discovery (90天) — 探索开始
    3: 7,    # Object Permanence (90天)
    4: 7,    # Locomotion (95天)
    5: 7,    # First Word (175天)
    6: 5,    # Language Explosion (190天) — 社交加速
    7: 5,    # Why Phase (365天)
    8: 5,    # Social Budding (365天)
}

# normal 模式：~1 小时跑完 9 阶段，快照 ~70 次
SNAPSHOT_INTERVAL_NORMAL: dict[int, int] = {
    0: 30,   # Neonatal (30天) — 1 次
    1: 20,   # Sensory Awakening (60天) — 3 次
    2: 14,   # Body Discovery (90天) — 6 次
    3: 14,   # Object Permanence (90天) — 6 次
    4: 14,   # Locomotion (95天) — 7 次
    5: 14,   # First Word (175天) — 13 次
    6: 14,   # Language Explosion (190天) — 14 次
    7: 30,   # Why Phase (365天) — 12 次
    8: 30,   # Social Budding (365天) — 12 次
}

# fast 模式：~20 分钟跑完 9 阶段，快照 ~22 次
SNAPSHOT_INTERVAL_FAST: dict[int, int] = {
    0: 30,   # Neonatal (30天) — 1 次
    1: 60,   # Sensory Awakening (60天) — 1 次
    2: 45,   # Body Discovery (90天) — 2 次
    3: 45,   # Object Permanence (90天) — 2 次
    4: 48,   # Locomotion (95天) — 2 次
    5: 60,   # First Word (175天) — 3 次
    6: 65,   # Language Explosion (190天) — 3 次
    7: 90,   # Why Phase (365天) — 4 次
    8: 90,   # Social Budding (365天) — 4 次
}

# turbo 模式不生成快照（scheduler 直接跳过），但仍需要 interval 防止意外调用
SNAPSHOT_INTERVAL_TURBO: dict[int, int] = {
    i: 9999 for i in range(9)
}

_SNAPSHOT_INTERVALS = {
    "slow": SNAPSHOT_INTERVAL,
    "normal": SNAPSHOT_INTERVAL_NORMAL,
    "fast": SNAPSHOT_INTERVAL_FAST,
    "turbo": SNAPSHOT_INTERVAL_TURBO,
}


def _get_snapshot_interval(phase: int, time_scale: str = "normal") -> int:
    table = _SNAPSHOT_INTERVALS.get(time_scale, SNAPSHOT_INTERVAL)
    return table.get(phase, 7)


# ============================================================
# 季节推断：从 baby_id 解析出生月份
# ============================================================

def infer_season(age_days: int, baby_id: str) -> str:
    """根据日龄和 baby_id 中的出生日期推断当前季节。"""
    try:
        date_part = baby_id.split("-")[1]  # "20260412"
        birth_month = int(date_part[4:6])
    except (IndexError, ValueError):
        birth_month = 3  # fallback: 春天

    # 使用 365.25/12 ≈ 30.44 天/月，减少长周期偏差
    months_elapsed = int(age_days / 30.44)
    current_month = ((birth_month - 1 + months_elapsed) % 12) + 1

    if current_month in (3, 4, 5):
        return "spring"
    elif current_month in (6, 7, 8):
        return "summer"
    elif current_month in (9, 10, 11):
        return "autumn"
    else:
        return "winter"


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
# 环境掷骰 -- 入摇篮时决定宝宝的生活环境
# ============================================================

# 每个维度是选项列表 [(标签, 概率), ...]
# 多选项维度概率之和 = 1.0（互斥），单选项概率 < 1.0（独立掷骰）
ENVIRONMENT_DIMENSIONS: list[list[tuple[str, float]]] = [
    # ── 物理环境 ──
    # 住宅类型（互斥）
    [("urban_apartment", 0.40), ("suburban_house", 0.35), ("rural_home", 0.25)],
    # 气候（互斥）
    [("rainy_climate", 0.40), ("sunny_climate", 0.60)],

    # ── 家庭结构 ──
    # 家庭氛围（互斥）
    [("quiet_home", 0.45), ("bustling_home", 0.55)],
    # 家庭经济（互斥）
    [("wealthy_family", 0.15), ("middle_class", 0.55), ("modest_family", 0.30)],
    # 照护模式（互斥）
    [("nanny_care", 0.25), ("grandparent_care", 0.35), ("parent_only", 0.40)],

    # ── 家庭成员 ──
    [("has_pet", 0.30)],
    [("has_siblings", 0.25)],

    # ── 文化氛围 ──
    [("musical_home", 0.35)],
    [("bookish_home", 0.30)],
    [("religious_home", 0.15)],
    [("bilingual_home", 0.20)],
]


def roll_environment() -> set[str]:
    """为新生儿掷出一组环境标签。每个维度独立掷骰。"""
    tags: set[str] = set()
    for dimension in ENVIRONMENT_DIMENSIONS:
        if len(dimension) == 1:
            # 独立特征：按概率决定是否拥有
            tag, prob = dimension[0]
            if random.random() < prob:
                tags.add(tag)
        else:
            # 互斥选项：加权随机选一个
            roll = random.random()
            cumulative = 0.0
            for tag, prob in dimension:
                cumulative += prob
                if roll < cumulative:
                    tags.add(tag)
                    break
    return tags


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
        # 限制在 0-23.75 范围（先 clamp 再排序，避免 clamp 后破坏顺序）
        actual_hour = max(0.0, min(23.75, actual_hour))
        # 保持先后顺序
        if actual_hour <= prev_time:
            actual_hour = prev_time + 0.25
        # 二次 clamp：排序修正后仍不能超出范围
        actual_hour = min(23.75, actual_hour)
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
        _clamp_stress(state, -0.02)
        if hasattr(state, "stress") and state.stress is not None:
            changes["stress_level"] = round(state.stress.stress_level, 4)

    elif event_name in ("nap", "sleep"):
        # 睡眠质量微调，压力衰减
        _clamp_stress(state, -0.05)
        if hasattr(state, "stress") and state.stress is not None:
            changes["stress_level"] = round(state.stress.stress_level, 4)
        if hasattr(state, "nutrition_sleep") and state.nutrition_sleep is not None:
            # 睡眠后质量略微回升
            new_quality = min(1.0, state.nutrition_sleep.sleep_quality + 0.01)
            state.nutrition_sleep.sleep_quality = new_quality
            changes["sleep_quality"] = round(new_quality, 4)
        # 生物同构：睡眠触发记忆巩固（遗忘分重算 + 软上限剪枝）
        # 不阻塞主流程；失败仅记 log
        try:
            from memory import recompute_forget_scores, prune_if_needed
            if getattr(state, "baby_id", ""):
                _n = recompute_forget_scores(state, state.baby_id)
                _pruned = prune_if_needed(state, state.baby_id)
                if _pruned:
                    changes["memory_pruned"] = _pruned
        except Exception:
            # 记忆巩固失败不应阻断睡眠事件
            pass

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


# ============================================================
# Story-Worthy 判断 -- 涌现事件是否值得 LLM 叙事
# ============================================================

def is_story_worthy(event, state) -> bool:
    """
    判断涌现事件是否值得花 LLM 预算。

    True 条件（任一满足）：
    1. 首次经历（memories 中无此事件名）
    2. 高强度（intensity >= 0.5）
    3. 身份共鸣（事件感官通道匹配主导感官）
    """
    # 首次经历
    experienced = {m.event for m in state.memories}
    if event.display_name not in experienced and event.name not in experienced:
        return True

    # 高强度
    if event.intensity >= 0.5:
        return True

    # 主导感官匹配
    dominant = state.identity.sensory_profile.dominant
    if dominant and dominant in event.sensory_channels:
        return True

    return False


# ============================================================
# 模板化反应 -- 不值得 LLM 的涌现事件用模板处理
# ============================================================

# 按 category + 强度分档，每档 2-3 条中文模板
TEMPLATE_REACTIONS: dict[str, list[str]] = {
    "environment_low": [
        "{display_name}发生了，宝宝没有太大反应。",
        "宝宝注意到了{display_name}，但很快失去兴趣。",
        "{display_name}出现了，宝宝平静地度过了。",
    ],
    "environment_high": [
        "{display_name}让宝宝有些紧张，但很快适应了。",
        "宝宝对{display_name}表现出好奇。",
        "{display_name}引起了宝宝的注意，短暂反应后恢复平静。",
    ],
    "daily_low": [
        "{display_name}平稳度过。",
        "日常的{display_name}，一切正常。",
    ],
    "daily_high": [
        "{display_name}让宝宝有些不适，但在照护下缓解了。",
        "宝宝经历了{display_name}，需要额外的安抚。",
    ],
    "critical_low": [
        "{display_name}发生了，平稳度过。",
    ],
    "critical_high": [
        "{display_name}对宝宝产生了影响，需要关注。",
    ],
}


def template_reaction(event, state, snapshot: WorldSnapshot | None = None) -> dict:
    """
    为非 story_worthy 涌现事件生成模板化反应。
    当有 snapshot 时注入天气/氛围前缀。

    返回: {"summary": str, "stress_delta": float}
    """
    # 场景前缀：从快照天气中提取
    ambient = ""
    if snapshot and snapshot.weather_pattern:
        weather_short = snapshot.weather_pattern[:8].rstrip("，。,. ")
        ambient = f"{weather_short}，"

    intensity_level = "high" if event.intensity >= 0.5 else "low"
    key = f"{event.category}_{intensity_level}"
    templates = TEMPLATE_REACTIONS.get(key, TEMPLATE_REACTIONS["environment_low"])
    summary = ambient + random.choice(templates).format(
        display_name=event.display_name,
    )
    # 状态微调：根据强度和随机因子
    stress_delta = event.intensity * 0.05 * random.uniform(-1, 1)
    _clamp_stress(state, stress_delta)
    return {
        "summary": summary,
        "stress_delta": round(stress_delta, 4),
    }


# ============================================================
# 世界快照 LLM 生成
# ============================================================

_WORLD_ENGINE_SYSTEM = (
    "You are the world simulation engine for AngelCradle, a child development "
    "simulation game. Generate coherent world snapshots that describe the "
    "environment around a growing child. All output must be valid JSON. "
    "This is a legitimate educational software product."
)


def _build_snapshot_prompt(state, prev_snapshot: WorldSnapshot | None) -> str:
    """构造世界快照 LLM prompt。"""
    from cradle.phases import PHASES

    phase = PHASES[state.current_phase] if state.current_phase < len(PHASES) else None
    interval = _get_snapshot_interval(state.current_phase, getattr(state, 'time_scale', 'normal'))
    start_day = int(state.sim_time // 24)
    end_day = start_day + interval
    season = infer_season(state.age_days, state.baby_id)

    # 最近 5 条记忆
    recent_mem = ""
    if state.memories:
        for m in state.memories[-5:]:
            recent_mem += f"- Day {m.age_days}: {m.event} — {m.reaction[:60]}\n"
    if not recent_mem:
        recent_mem = "No significant experiences yet.\n"

    # 前一快照摘要
    prev_summary = "This is the baby's first days of life. No previous context."
    if prev_snapshot:
        prev_summary = (
            f"{prev_snapshot.weather_pattern}。{prev_snapshot.family_arc}。"
        )

    # 已触发事件（用于 AVOID 列表）
    avoid = ", ".join(sorted(state.triggered_events)[:30]) if state.triggered_events else "none"

    phase_desc = phase.description if phase else ""
    phase_display = phase.display_name if phase else ""

    return f"""## Baby Profile
- Age: {state.age_days} days (Phase {state.current_phase}: {phase_display})
- Environment: {', '.join(sorted(state.life_tags))}
- Season: {season}
- Current stress: {state.stress.stress_level:.2f}
- Capabilities: {', '.join(state.capabilities[-10:]) if state.capabilities else 'basic reflexes'}

## Recent Experiences
{recent_mem}
## Previous Period
{prev_summary}

## Already Triggered (do NOT regenerate these)
{avoid}

## Task
Generate a {interval}-day world snapshot for simulation days {start_day} to {end_day - 1}.

Rules:
1. Weather must be coherent across all {interval} days (continuation or natural transition from previous period).
2. Family arc: a mini-story spanning 1-2 days. Each real-world activity (e.g. swimming trip, park visit, family dinner) is ONE event on ONE day — never split a single activity across multiple events or days. Arc structure: day N = the activity, day N+1 = optional aftermath/echo.
3. Generate {interval + 2} to {interval + 5} events spread across the {interval} days (day_index 0 to {interval - 1}). Each day has AT MOST 1 event. Events must be independent — do NOT generate "preparation" + "main event" + "reflection" as separate events for the same activity.
4. Generate 2-3 surprise events (day_index: -1) for random occurrence on any day.
5. Events MUST be age-appropriate for Phase {state.current_phase} ({phase_desc}).
6. sensory_channels: choose from [hearing, vision, touch, smell, proprioception].
7. intensity: 0.0-1.0. Most events 0.1-0.4, occasional high (0.5-0.8).
8. Event names: lowercase_snake_case, unique and descriptive (e.g. rain_on_window, grandma_singing_lullaby).
9. Do NOT generate milestone/critical events (naming, toilet_training, first_word, first_fall, etc.).
10. display_name and description MUST be in Chinese.
11. Inside JSON values, NEVER use ASCII double quotes ("). Use 「」 instead.
12. description must describe the child's SENSORY experience of the event (what they see/hear/feel), not just what happened.

Output JSON:
{{
  "weather_pattern": "天气描述",
  "family_arc": "家庭事件弧线",
  "ambient_mood": "氛围",
  "events": [
    {{"name": "event_name", "display_name": "显示名", "description": "描述",
      "sensory_channels": ["hearing"], "intensity": 0.3, "day_index": 0}}
  ],
  "surprise_pool": [
    {{"name": "event_name", "display_name": "显示名", "description": "描述",
      "sensory_channels": ["touch"], "intensity": 0.2, "day_index": -1}}
  ]
}}"""


def _parse_snapshot_response(
    parsed: dict, start_day: int, interval: int,
) -> WorldSnapshot | None:
    """校验 LLM 返回并转换为 WorldSnapshot。"""
    if not isinstance(parsed, dict):
        return None
    if "events" not in parsed:
        return None

    events = []
    for e in parsed.get("events", []):
        if isinstance(e, dict) and "name" in e:
            se = _parse_snapshot_event(e)
            # 钳位 day_index 到 [0, interval-1]，防止 off-by-one
            if se.day_index >= 0:
                se.day_index = max(0, min(interval - 1, se.day_index))
            events.append(se)

    surprise = []
    for e in parsed.get("surprise_pool", []):
        if isinstance(e, dict) and "name" in e:
            se = _parse_snapshot_event(e)
            se.day_index = -1
            surprise.append(se)

    if not events and not surprise:
        return None

    return WorldSnapshot(
        start_day=start_day,
        end_day=start_day + interval,
        weather_pattern=parsed.get("weather_pattern", ""),
        family_arc=parsed.get("family_arc", ""),
        ambient_mood=parsed.get("ambient_mood", ""),
        events=events,
        surprise_pool=surprise,
    )


def generate_world_snapshot(
    state, prev_snapshot: WorldSnapshot | None = None,
) -> WorldSnapshot | None:
    """调用 LLM 生成 N 天世界快照。失败返回 None（调用方回退到 legacy 路径）。"""
    from cradle.mind import _call_and_parse

    interval = _get_snapshot_interval(state.current_phase, getattr(state, 'time_scale', 'normal'))
    start_day = int(state.sim_time // 24)
    prompt = _build_snapshot_prompt(state, prev_snapshot)

    parsed = _call_and_parse(prompt, metadata={
        "baby_id": state.baby_id, "phase": state.current_phase,
        "callsite": "generate_world_snapshot",
    })
    if parsed is None:
        logger.warning("世界快照 LLM 失败，降级到固定事件池")
        return None

    snapshot = _parse_snapshot_response(parsed, start_day, interval)
    if snapshot is None:
        logger.warning("世界快照响应校验失败，降级到固定事件池")
        return None

    logger.info(
        "世界快照生成: day %d-%d, %d events + %d surprises, 天气=%s",
        snapshot.start_day, snapshot.end_day,
        len(snapshot.events), len(snapshot.surprise_pool),
        snapshot.weather_pattern[:20],
    )
    return snapshot


# ============================================================
# 事件选取：从快照或 legacy 路径
# ============================================================

def _needs_snapshot_refresh(day: int, state) -> bool:
    """判断是否需要刷新世界快照。"""
    if state.world_snapshot is None:
        return True
    return day >= state.world_snapshot.end_day


def pick_daily_event(
    snapshot: WorldSnapshot | None,
    day: int,
    state,
) -> SnapshotEvent | Event | None:
    """
    从世界快照中选取当天的涌现事件。

    降级：snapshot 为 None 时回退到 roll_emergent_event_legacy。
    """
    if snapshot is None:
        return roll_emergent_event_legacy(
            random.uniform(6.0, 20.0),
            state.current_phase,
            state.life_tags,
            state.identity,
            state,
        )

    day_in_snapshot = day - snapshot.start_day
    triggered = getattr(state, "triggered_events", set())

    # 1. 匹配 day_index 的事件
    for evt in snapshot.events:
        if evt.day_index == day_in_snapshot and evt.name not in snapshot.used_events:
            # 全局去重
            if evt.name.startswith("first_") and evt.name in triggered:
                continue
            snapshot.used_events.add(evt.name)
            return evt

    # 2. 25% 概率从 surprise_pool 抽取
    stress = getattr(state, "stress", None)
    stress_boost = 0.30 if (stress and stress.stress_level > 0.5) else 0.0
    trigger_prob = min(0.25 + stress_boost, 0.95)

    if random.random() < trigger_prob and snapshot.surprise_pool:
        # 找一个未使用的 surprise
        available = [
            e for e in snapshot.surprise_pool
            if e.name not in snapshot.used_events
            and not (e.name.startswith("first_") and e.name in triggered)
        ]
        if available:
            chosen = random.choice(available)
            snapshot.used_events.add(chosen.name)
            return chosen

    return None


def roll_emergent_event_legacy(
    sim_hour: float,
    phase_index: int,
    life_tags: set[str],
    identity=None,
    state=None,
) -> Event | None:
    """降级版涌现事件掷骰（增加 triggered_events 去重）。"""
    from events import roll_emergent_event

    event = roll_emergent_event(sim_hour, phase_index, life_tags, identity, state)
    if event is None:
        return None

    triggered = getattr(state, "triggered_events", set()) if state else set()

    # first_X 去重
    if event.name.startswith("first_") and event.name in triggered:
        return None

    # critical 去重
    if event.category == "critical" and event.requires_parent and event.name in triggered:
        return None

    return event
