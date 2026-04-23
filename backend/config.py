"""
系统级全局配置——进程内单例，不持久化。

速率（time_scale）影响所有模块：子宫发育速度、摇篮模拟节奏、世界事件密度。
单租户假设：当前为单用户单实例，未来多用户需重构为 per-session。

[INPUT]: 无外部依赖
[OUTPUT]: get_time_scale(), set_time_scale(), VALID_TIME_SCALES
[POS]: 顶级配置模块，被 scheduler/womb/world/api 消费
[PROTOCOL]: 变更时更新此头部，然后检查 CLAUDE.md
"""

from __future__ import annotations

import logging
import os

logger = logging.getLogger(__name__)

VALID_TIME_SCALES = ("slow", "normal", "fast", "turbo")

_system_time_scale: str = "turbo"

def get_time_scale() -> str:
    """返回当前全局速率。"""
    return _system_time_scale


def set_time_scale(ts: str) -> None:
    """设置全局速率。影响所有模块（子宫/摇篮/世界）。值相同时 no-op，不打日志。"""
    global _system_time_scale
    if ts not in VALID_TIME_SCALES:
        raise ValueError(f"Invalid time_scale: {ts}. Must be one of {VALID_TIME_SCALES}")
    if ts == _system_time_scale:
        return
    old = _system_time_scale
    _system_time_scale = ts
    logger.info("全局速率切换: %s → %s", old, ts)
