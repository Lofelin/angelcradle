"""
共享事件系统——供摇篮和世界层共用的事件基础设施。

事件模型支持时间窗口、生活上下文标签、排斥标签、持续时长和链式后续事件。
route_events() 按时间 + 阶段 + 标签三重过滤，roll_emergent_event() 概率触发涌现事件。

[INPUT]: 无外部模块依赖（纯数据模型 + 过滤逻辑）
[OUTPUT]: Event, route_events, roll_emergent_event
[POS]: 共享事件基础设施，被 cradle/events.py、world.py、scheduler.py 消费
[PROTOCOL]: 变更时更新此头部，然后检查 CLAUDE.md
"""

from __future__ import annotations

import random
from dataclasses import dataclass, field


@dataclass
class Event:
    """成长事件数据模型。

    基础字段兼容原 cradle/events.py，新增字段用于时间窗口过滤和日程链。
    """
    name: str
    category: str                   # daily / environment / critical / schedule
    display_name: str
    description: str
    sensory_channels: list[str]     # 涉及的感官通道
    intensity: float                # 0-1，刺激强度
    requires_parent: bool           # 是否需要父母介入
    phase_range: tuple[int, int]    # 可发生的阶段范围（inclusive）
    weight: float = 1.0             # 概率权重
    parent_choices: list[dict] = field(default_factory=list)  # 父母干预选项

    # ---- 新增字段：时间窗口 + 生活上下文 + 日程链 ----
    hour_range: tuple[int, int] = (0, 24)       # 可发生的小时范围
    requires_tags: list[str] = field(default_factory=list)   # 前置条件标签
    excludes_tags: list[str] = field(default_factory=list)   # 排斥标签
    duration_hours: float = 1.0                 # 事件持续时长（模拟小时）
    generates_next: str | None = None           # 链式后续事件名


def route_events(
    sim_hour: float,
    phase_index: int,
    life_tags: set[str],
    identity=None,
    state=None,
    category: str = "all",
) -> list[Event]:
    """按时间 + 阶段 + 标签三重过滤，返回符合条件的事件列表。

    过滤流程：
    1. category 过滤（all 返回全部类别）
    2. phase_range 过滤（inclusive）
    3. hour_range 过滤（sim_hour 在范围内）
    4. requires_tags 过滤（agent 必须有所有标签）
    5. excludes_tags 过滤（agent 不能有任何排斥标签）
    """
    # 延迟导入，避免循环依赖
    from events.definitions import (
        DAILY_EVENTS, ENVIRONMENT_EVENTS, CRITICAL_EVENTS, SCHEDULE_EVENTS,
    )

    # 按 category 选择事件池
    if category == "all":
        pool = DAILY_EVENTS + ENVIRONMENT_EVENTS + CRITICAL_EVENTS + SCHEDULE_EVENTS
    elif category == "daily":
        pool = DAILY_EVENTS
    elif category == "environment":
        pool = ENVIRONMENT_EVENTS
    elif category == "critical":
        pool = CRITICAL_EVENTS
    elif category == "schedule":
        pool = SCHEDULE_EVENTS
    else:
        pool = []

    result = []
    for event in pool:
        # 阶段过滤
        if not (event.phase_range[0] <= phase_index <= event.phase_range[1]):
            continue
        # 时间窗口过滤
        if not (event.hour_range[0] <= sim_hour < event.hour_range[1]):
            continue
        # 前置标签过滤：agent 必须拥有所有 requires_tags
        if event.requires_tags and not all(
            tag in life_tags for tag in event.requires_tags
        ):
            continue
        # 排斥标签过滤：agent 不能有任何 excludes_tags
        if event.excludes_tags and any(
            tag in life_tags for tag in event.excludes_tags
        ):
            continue
        result.append(event)

    return result


def roll_emergent_event(
    sim_hour: float,
    phase_index: int,
    life_tags: set[str],
    identity=None,
    state=None,
) -> Event | None:
    """概率触发涌现事件——从 environment + critical 池中加权随机选一个。

    逻辑：
    1. 调用 route_events 获取当前可用的 environment + critical 事件
    2. 基础概率 25%
    3. 如果 state 有 stress 且 stress_level > 0.5，负面事件概率 +30%
    4. 加权随机选一个，或返回 None
    """
    # 合并 environment 和 critical 候选
    candidates = []
    for cat in ("environment", "critical"):
        candidates.extend(
            route_events(sim_hour, phase_index, life_tags, identity, state, cat)
        )

    if not candidates:
        return None

    # 基础触发概率
    base_prob = 0.25

    # 压力调制
    stress_boost = 0.0
    if state is not None:
        stress = getattr(state, "stress", None)
        if stress and getattr(stress, "stress_level", 0) > 0.5:
            stress_boost = 0.30

    # 判定是否触发
    trigger_prob = min(base_prob + stress_boost, 0.95)
    if random.random() > trigger_prob:
        return None

    # 构建权重：高压时负面事件（intensity > 0.5）权重 +30%
    weights = []
    for event in candidates:
        w = event.weight
        if stress_boost > 0 and event.intensity > 0.5:
            w *= 1.3
        weights.append(w)

    chosen = random.choices(candidates, weights=weights, k=1)
    return chosen[0]
