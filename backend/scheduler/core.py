"""
LifelineScheduler -- DES 调度器核心类。

全局优先级队列，单一主循环，per-baby dispatch lock 保证同 baby 串行。
事件处理委托给 scheduler.handlers 模块的独立函数。

[INPUT]: 依赖 scheduler/events.py、scheduler/constants.py
[OUTPUT]: LifelineScheduler 类
[POS]: scheduler/ 的核心模块
[PROTOCOL]: 变更时更新此头部，然后检查 scheduler/CLAUDE.md
"""

from __future__ import annotations

import asyncio
import heapq
import logging

from scheduler.constants import CRADLE_EXIT_PHASE, EVENT_PACE
from scheduler.events import SimEvent

logger = logging.getLogger(__name__)


class LifelineScheduler:
    """
    DES 调度器。全局优先级队列，单一主循环。

    - register: 向队列插入 baby 的首个 phase_start 事件
    - run: 主循环，pop → dispatch（per-baby lock 保证串行）
    - inject: 外部注入事件（跨 baby 社交、世界事件等）
    """

    def __init__(self) -> None:
        self._queue: list[SimEvent] = []
        self._registered: set[str] = set()       # 活跃 baby 集合
        self._dispatch_locks: dict[str, asyncio.Lock] = {}
        self._llm_semaphore: asyncio.Semaphore = asyncio.Semaphore(3)
        self._running: bool = False
        self._wakeup: asyncio.Event = asyncio.Event()
        # per-baby 阶段内追踪（生命周期 = 一个阶段）
        self._phase_story_count: dict[str, dict[int, int]] = {}
        self._phase_llm_need_count: dict[str, dict[int, int]] = {}
        self._quiet_start: dict[str, int | None] = {}
        self._last_critical_day: dict[str, int] = {}

    # ============================================================
    # 公共接口
    # ============================================================

    async def register(self, baby_id: str) -> None:
        """注册 baby，向队列插入 phase_start。已注册则跳过。"""
        if baby_id in self._registered:
            logger.info("Agent %s 已注册，跳过", baby_id)
            return

        from cradle.state import load_state
        from cradle.phases import PHASES

        state = load_state(baby_id)
        if state is None:
            logger.error("Agent %s 状态不存在，跳过注册", baby_id)
            return

        self._registered.add(baby_id)

        end_phase = min(CRADLE_EXIT_PHASE, len(PHASES))
        if state.current_phase >= end_phase:
            logger.info("Agent %s 已完成摇篮 (phase=%d)，跳过", baby_id, state.current_phase)
            return

        self.push(SimEvent(
            sim_time=state.sim_time,
            baby_id=baby_id,
            event_type="phase_start",
            payload={"phase_idx": state.current_phase},
        ))
        logger.info(
            "已注册 Agent %s, phase=%d, sim_time=%.1f",
            baby_id, state.current_phase, state.sim_time,
        )

    def unregister(self, baby_id: str) -> None:
        """注销 baby。队列中残留事件通过懒清理跳过。"""
        self._registered.discard(baby_id)
        self._dispatch_locks.pop(baby_id, None)
        self._phase_story_count.pop(baby_id, None)
        self._quiet_start.pop(baby_id, None)
        logger.info("已注销 Agent %s", baby_id)

    def stop(self) -> None:
        """停止所有 agent。"""
        self._running = False
        self._registered.clear()
        self._queue.clear()
        self._wakeup.set()
        logger.info("调度器停止")

    def inject(self, baby_id: str, event_type: str,
               sim_time: float = 0, **payload) -> None:
        """外部注入事件（跨 baby 社交、世界事件等）。"""
        self.push(SimEvent(
            sim_time=sim_time,
            baby_id=baby_id,
            event_type=event_type,
            payload=payload,
        ))

    async def run(self) -> None:
        """DES 主循环：pop 事件 → dispatch（fire-and-forget task）。"""
        self._running = True
        logger.info("DES 调度器启动")

        while self._running:
            if not self._queue:
                self._wakeup.clear()
                try:
                    await asyncio.wait_for(self._wakeup.wait(), timeout=1.0)
                except asyncio.TimeoutError:
                    pass
                continue

            event = heapq.heappop(self._queue)

            # 懒清理：已注销的 baby 跳过
            if event.baby_id and event.baby_id not in self._registered:
                continue

            # fire-and-forget：per-baby lock 保证同 baby 串行，不同 baby 并发
            asyncio.create_task(self._safe_dispatch(event))
            await asyncio.sleep(0)  # 让出控制权

    # ============================================================
    # 内部：队列 + 分发
    # ============================================================

    def push(self, event: SimEvent) -> None:
        """向优先级队列插入事件。handlers 通过 sched.push() 调用。"""
        heapq.heappush(self._queue, event)
        self._wakeup.set()

    def _get_dispatch_lock(self, baby_id: str) -> asyncio.Lock:
        if baby_id not in self._dispatch_locks:
            self._dispatch_locks[baby_id] = asyncio.Lock()
        return self._dispatch_locks[baby_id]

    async def _safe_dispatch(self, event: SimEvent) -> None:
        """带 per-baby lock 的安全分发。"""
        lock = self._get_dispatch_lock(event.baby_id)
        async with lock:
            if event.baby_id not in self._registered:
                return
            try:
                await self._dispatch(event)
            except asyncio.CancelledError:
                logger.info("事件被取消: %s %s", event.baby_id, event.event_type)
            except Exception:
                logger.exception(
                    "事件处理异常: baby=%s type=%s",
                    event.baby_id, event.event_type,
                )

    async def _dispatch(self, event: SimEvent) -> None:
        """事件分发到对应处理器（延迟 import 避免循环依赖）。"""
        from scheduler.handlers import on_phase_start, on_day_tick, on_phase_complete

        _handlers = {
            "phase_start": on_phase_start,
            "day_tick": on_day_tick,
            "phase_complete": on_phase_complete,
        }
        handler = _handlers.get(event.event_type)
        if handler:
            await handler(self, event)
        else:
            logger.warning("未知事件类型: %s", event.event_type)

    # ============================================================
    # 辅助方法（handlers 通过 sched.xxx() 调用）
    # ============================================================

    def flush_quiet_days(
        self, baby_id: str, state,
        from_day: int, to_day: int, phase_idx: int,
    ) -> None:
        """将一段平静日压缩为一条摘要日志。"""
        from cradle.state import append_event

        days = to_day - from_day + 1
        if days <= 0:
            return

        append_event(baby_id, {
            "event": "day_summary",
            "from_day": from_day + 1,
            "to_day": to_day + 1,
            "days": days,
            "age_days_start": from_day + 1,
            "age_days_end": to_day + 1,
            "phase_index": phase_idx,
        })

    async def pace(self, state) -> None:
        """根据 time_scale 在可见事件之间插入延迟，让生命线有呼吸感。"""
        delay = EVENT_PACE.get(state.time_scale, EVENT_PACE["normal"])
        if delay > 0:
            await asyncio.sleep(delay)
