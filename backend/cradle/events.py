"""
Cradle event system — thin wrapper over shared events infrastructure.

保持 roll_events() 原签名不变，供 nanny.py 消费。
底层数据和逻辑已迁移至 events/ 包：
  - events.Event: 事件数据类
  - events.definitions: 事件定义常量
  - events.modifiers: 权重调制函数

[INPUT]: events.Event, events.definitions.*, events.modifiers.*
[OUTPUT]: roll_events, Event, DAILY_EVENTS, ENVIRONMENT_EVENTS, CRITICAL_EVENTS, ALL_EVENTS, get_event
[POS]: cradle/ 事件系统入口，被 nanny.py 消费；委托 events/ 包实现
[PROTOCOL]: 变更时更新此头部，然后检查 CLAUDE.md
"""

from __future__ import annotations

import random

from events import Event
from events.definitions import (
    DAILY_EVENTS, ENVIRONMENT_EVENTS, CRITICAL_EVENTS,
    ALL_EVENTS, get_event,
)
from events.modifiers import _compute_affinity, _phase_weight_modifier

# 重导出，保持向后兼容
__all__ = [
    "Event", "DAILY_EVENTS", "ENVIRONMENT_EVENTS", "CRITICAL_EVENTS",
    "ALL_EVENTS", "get_event", "roll_events",
]

_EVENT_MAP = {e.name: e for e in ALL_EVENTS}


def roll_events(phase_index: int, identity=None, state=None,
                count_daily: int = 3, count_env: int = 2) -> dict:
    """
    Generate events for a phase, with identity-modulated weights.

    Returns:
        {"daily": [...], "environment": [...], "critical": [...],
         "traces": [...]}

    traces record each event's selection/rejection process for frontend display.
    """
    result: dict = {"daily": [], "environment": [], "critical": [], "traces": []}

    # Daily events: identity-modulated weights + phase modifier
    available_daily = [e for e in DAILY_EVENTS
                       if e.phase_range[0] <= phase_index <= e.phase_range[1]]
    if available_daily:
        if identity:
            weights = [e.weight * _compute_affinity(e, identity)
                       * _phase_weight_modifier(e, phase_index, state)
                       for e in available_daily]
        else:
            weights = [e.weight * _phase_weight_modifier(e, phase_index, state)
                       for e in available_daily]
        chosen = random.choices(available_daily, weights=weights,
                                k=min(count_daily, len(available_daily)))
        result["daily"] = chosen

        for e in available_daily:
            affinity = _compute_affinity(e, identity) if identity else 1.0
            phase_mod = _phase_weight_modifier(e, phase_index, state)
            result["traces"].append({
                "category": "daily",
                "event_name": e.name,
                "event_display": e.display_name,
                "base_weight": e.weight,
                "affinity": affinity,
                "phase_modifier": round(phase_mod, 3),
                "final_weight": round(e.weight * affinity * phase_mod, 3),
                "selected": e in chosen,
            })

    # Environment events: identity-modulated weights + phase modifier
    available_env = [e for e in ENVIRONMENT_EVENTS
                     if e.phase_range[0] <= phase_index <= e.phase_range[1]]
    if available_env:
        if identity:
            weights = [e.weight * _compute_affinity(e, identity)
                       * _phase_weight_modifier(e, phase_index, state)
                       for e in available_env]
        else:
            weights = [e.weight * _phase_weight_modifier(e, phase_index, state)
                       for e in available_env]
        chosen = random.choices(available_env, weights=weights,
                                k=min(count_env, len(available_env)))
        result["environment"] = chosen

        for e in available_env:
            affinity = _compute_affinity(e, identity) if identity else 1.0
            phase_mod = _phase_weight_modifier(e, phase_index, state)
            result["traces"].append({
                "category": "environment",
                "event_name": e.name,
                "event_display": e.display_name,
                "base_weight": e.weight,
                "affinity": affinity,
                "phase_modifier": round(phase_mod, 3),
                "final_weight": round(e.weight * affinity * phase_mod, 3),
                "selected": e in chosen,
            })

    # Critical events: independent roll, identity-modulated probability + phase modifier
    available_critical = [e for e in CRITICAL_EVENTS
                         if e.phase_range[0] <= phase_index <= e.phase_range[1]
                         and e.weight > 0]
    for event in available_critical:
        affinity = _compute_affinity(event, identity) if identity else 1.0
        phase_mod = _phase_weight_modifier(event, phase_index, state)
        prob = min(event.weight * 0.3 * affinity * phase_mod, 0.95)
        roll = random.random()
        hit = roll < prob
        if hit:
            result["critical"].append(event)
        result["traces"].append({
            "category": "critical",
            "event_name": event.name,
            "event_display": event.display_name,
            "base_weight": event.weight,
            "affinity": affinity,
            "phase_modifier": round(phase_mod, 3),
            "probability": round(prob, 3),
            "roll": round(roll, 3),
            "selected": hit,
        })

    return result
