"""
DES 事件原语 + 需求响应信号。

[INPUT]: 无
[OUTPUT]: SimEvent, signal_need_responded, get_or_create_respond_event
[POS]: scheduler/ 的事件基础设施
[PROTOCOL]: 变更时更新此头部，然后检查 scheduler/CLAUDE.md
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, field


# ============================================================
# DES 事件
# ============================================================

_event_counter = 0


def _next_seq() -> int:
    """全局单调递增序号，打破 heapq 同 sim_time 的平局。"""
    global _event_counter
    _event_counter += 1
    return _event_counter


@dataclass(order=True)
class SimEvent:
    """优先级队列元素。按 sim_time 排序，seq 打破平局（FIFO）。"""
    sim_time: float
    seq: int = field(default_factory=_next_seq)
    baby_id: str = field(compare=False, default="")
    event_type: str = field(compare=False, default="")
    payload: dict = field(compare=False, default_factory=dict)


# ============================================================
# 需求响应信号（interact 端点 → 需求等待唤醒）
# ============================================================

_respond_events: dict[str, asyncio.Event] = {}


def get_or_create_respond_event(baby_id: str) -> asyncio.Event:
    if baby_id not in _respond_events:
        _respond_events[baby_id] = asyncio.Event()
    return _respond_events[baby_id]


def signal_need_responded(baby_id: str) -> None:
    """被 api/cradle.py 的 interact 端点调用，唤醒等待中的 handle_need。"""
    evt = _respond_events.get(baby_id)
    if evt:
        evt.set()
