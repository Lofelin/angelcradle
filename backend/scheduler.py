"""
DES 调度器 -- 离散事件模拟驱动的 Agent 生命线管理器。

常驻进程，管理所有 Agent 的自驱动生命。
通过优先级队列按模拟时间排序执行事件，
日常事件用规则引擎，有"事"事件用 LLM，
事件处理后动态生成后续事件（边活边长）。

[INPUT]: 依赖 world.py（日程+事件处理）、events/（事件路由）、cradle/state.py（状态）、cradle/mind.py（LLM）
[OUTPUT]: EventScheduler 单例（register/unregister/run/subscribe/catchup）
[POS]: 顶级模块，被 api/cradle.py 和 FastAPI lifespan 消费
[PROTOCOL]: 变更时更新此头部，然后检查 CLAUDE.md
"""

from __future__ import annotations

import asyncio
import heapq
import logging
import time
from dataclasses import dataclass, field

logger = logging.getLogger(__name__)


# ============================================================
# 时间比例：1 现实秒 = N 模拟小时
# ============================================================

TIME_SCALES: dict[str, float] = {
    "slow":   24.0 / 3600,     # 1 real hour = 1 sim day (24h)
    "normal": 168.0 / 3600,    # 1 real hour = 7 sim days (168h)
    "fast":   720.0 / 3600,    # 1 real hour = 30 sim days (720h)
}


# ============================================================
# 调度事件条目
# ============================================================

@dataclass(order=True)
class ScheduledEvent:
    """优先级队列中的事件条目。"""
    sim_time: float                                    # 排序键
    baby_id: str = field(compare=False)
    event_name: str = field(compare=False)


# ============================================================
# 调度器主类
# ============================================================

class EventScheduler:
    """DES 调度器——管理所有宝宝的自驱动生命循环。"""

    def __init__(self) -> None:
        self._queue: list[ScheduledEvent] = []         # heapq 优先级队列
        self._agents: dict[str, str] = {}              # baby_id -> baby_id（轻量引用）
        self._running: bool = False
        self._llm_semaphore: asyncio.Semaphore = asyncio.Semaphore(3)
        self._subscribers: dict[str, list[asyncio.Queue]] = {}  # baby_id -> SSE 队列列表
        self._lock: asyncio.Lock = asyncio.Lock()

    # ============================================================
    # Agent 注册 / 注销
    # ============================================================

    async def register(self, baby_id: str) -> None:
        """注册 Agent，加载状态，生成首日日程。"""
        from cradle.state import load_state, save_state
        from world import generate_daily_schedule

        state = load_state(baby_id)
        if state is None:
            return

        # 初始化 last_active_ts
        if state.last_active_ts == 0.0:
            state.last_active_ts = time.time()
            save_state(state)

        self._agents[baby_id] = baby_id

        # 生成当前日的日程
        day_start = (state.sim_time // 24) * 24  # 当天起始
        schedule = generate_daily_schedule(
            state.current_phase, state.life_tags, day_start,
        )

        # 只插入未来的事件
        async with self._lock:
            for event_name, event_sim_time in schedule:
                if event_sim_time > state.sim_time:
                    heapq.heappush(
                        self._queue,
                        ScheduledEvent(event_sim_time, baby_id, event_name),
                    )

        logger.info("已注册 Agent %s (sim_time=%.1f)", baby_id, state.sim_time)

    def unregister(self, baby_id: str) -> None:
        """注销 Agent。队列中残留事件在处理时跳过。"""
        self._agents.pop(baby_id, None)
        logger.info("已注销 Agent %s", baby_id)

    # ============================================================
    # 主循环
    # ============================================================

    async def run(self) -> None:
        """DES 主循环。"""
        self._running = True
        logger.info("调度器启动")

        while self._running:
            wait_real = 1.0  # 默认等待 1 秒（队列空时）

            async with self._lock:
                if self._queue:
                    # peek 队首
                    next_event = self._queue[0]
                    baby_id = next_event.baby_id

                    # Agent 已注销，丢弃事件
                    if baby_id not in self._agents:
                        heapq.heappop(self._queue)
                        continue

                    # 加载状态计算等待时间
                    from cradle.state import load_state
                    state = load_state(baby_id)
                    if state is None:
                        heapq.heappop(self._queue)
                        self._agents.pop(baby_id, None)
                        continue

                    wait_real = self._sim_to_real(
                        state, next_event.sim_time - state.sim_time,
                    )

                    if wait_real <= 0:
                        # 时间到，取出事件处理
                        heapq.heappop(self._queue)
                        await self._process(state, next_event)
                        continue

                    # 需要等待，限制最长 30 秒
                    wait_real = min(wait_real, 30.0)

            # 队列为空或需要等待
            await asyncio.sleep(wait_real)

    def stop(self) -> None:
        """停止主循环。"""
        self._running = False
        logger.info("调度器停止")

    # ============================================================
    # 时间转换
    # ============================================================

    def _sim_to_real(self, state, sim_hours: float) -> float:
        """模拟时间差 -> 现实秒数。"""
        rate = TIME_SCALES.get(state.time_scale, TIME_SCALES["normal"])
        if rate <= 0:
            return 0.0
        return sim_hours / rate

    def _real_to_sim(self, state, real_seconds: float) -> float:
        """现实秒数 -> 模拟时间差（小时）。"""
        rate = TIME_SCALES.get(state.time_scale, TIME_SCALES["normal"])
        return real_seconds * rate

    # ============================================================
    # 事件处理
    # ============================================================

    async def _process(self, state, scheduled: ScheduledEvent) -> None:
        """处理一个调度事件。"""
        from cradle.state import save_state, append_event
        from world import process_event, generate_daily_schedule
        from events import roll_emergent_event

        baby_id = scheduled.baby_id

        # 推进模拟时间
        state.sim_time = scheduled.sim_time
        state.update_age_from_sim_time()
        state.last_active_ts = time.time()

        # 处理事件（规则引擎 or 标记需要 LLM）
        result = process_event(
            scheduled.event_name, state, scheduled.sim_time % 24,
        )

        if result["needs_llm"]:
            # LLM 处理（受 semaphore 限流）
            async with self._llm_semaphore:
                llm_result = await asyncio.to_thread(
                    self._generate_story, state, result,
                )
                if llm_result:
                    result.update(llm_result)

        # 构造 SSE 事件
        sim_hour = scheduled.sim_time % 24
        sse_event: dict = {
            "event": (
                "autonomous_event" if result["needs_llm"]
                else "autonomous_routine"
            ),
            "event_name": result["event_name"],
            "display_name": result["display_name"],
            "sim_hour": round(sim_hour, 1),
            "sim_day": int(scheduled.sim_time // 24),
            "age_days": state.age_days,
            "changes": result.get("changes", {}),
        }
        if result.get("summary"):
            sse_event["summary"] = result["summary"]
        if result.get("memory"):
            sse_event["memory"] = result["memory"]

        # 持久化 + 推送
        append_event(baby_id, sse_event)
        save_state(state)
        await self._push(baby_id, sse_event)

        # ---- 生成后续事件 ----

        # 1. 涌现事件掷骰
        emergent = roll_emergent_event(
            sim_hour, state.current_phase, state.life_tags,
            state.identity, state,
        )
        if emergent:
            async with self._lock:
                heapq.heappush(
                    self._queue,
                    ScheduledEvent(
                        scheduled.sim_time + 0.5, baby_id, emergent.name,
                    ),
                )

        # 2. sleep 事件 -> 生成次日日程
        if scheduled.event_name == "sleep":
            next_day_start = ((scheduled.sim_time // 24) + 1) * 24
            schedule = generate_daily_schedule(
                state.current_phase, state.life_tags, next_day_start,
            )
            async with self._lock:
                for event_name, event_sim_time in schedule:
                    heapq.heappush(
                        self._queue,
                        ScheduledEvent(event_sim_time, baby_id, event_name),
                    )

    # ============================================================
    # SSE 订阅 / 推送
    # ============================================================

    def subscribe(self, baby_id: str) -> asyncio.Queue:
        """前端 SSE 订阅，返回事件队列。"""
        q: asyncio.Queue = asyncio.Queue()
        if baby_id not in self._subscribers:
            self._subscribers[baby_id] = []
        self._subscribers[baby_id].append(q)
        return q

    def unsubscribe(self, baby_id: str, q: asyncio.Queue) -> None:
        """取消 SSE 订阅。"""
        if baby_id in self._subscribers:
            self._subscribers[baby_id] = [
                x for x in self._subscribers[baby_id] if x is not q
            ]

    async def _push(self, baby_id: str, event: dict) -> None:
        """推送事件给所有订阅者。"""
        for q in self._subscribers.get(baby_id, []):
            try:
                q.put_nowait(event)
            except asyncio.QueueFull:
                pass  # 跳过慢消费者

    # ============================================================
    # 追赶模式
    # ============================================================

    async def catchup(self, baby_id: str) -> list[dict]:
        """
        追赶模式：补跑离线期间的事件。

        至少间隔 1 模拟天才触发，上限 90 天。
        返回追赶期间的有"事"事件列表。
        """
        from cradle.state import load_state, save_state, append_event
        from world import generate_daily_schedule, process_event
        from events import roll_emergent_event

        state = load_state(baby_id)
        if state is None or state.last_active_ts == 0.0:
            return []

        elapsed_real = time.time() - state.last_active_ts
        elapsed_sim_hours = self._real_to_sim(state, elapsed_real)

        # 至少 1 模拟天才触发追赶
        if elapsed_sim_hours < 24:
            return []

        # 上限 90 天
        max_sim_hours = 90 * 24
        elapsed_sim_hours = min(elapsed_sim_hours, max_sim_hours)
        target_sim_time = state.sim_time + elapsed_sim_hours

        catchup_events: list[dict] = []
        days_processed = 0

        while state.sim_time < target_sim_time and days_processed < 90:
            day_start = (state.sim_time // 24) * 24
            schedule = generate_daily_schedule(
                state.current_phase, state.life_tags, day_start,
            )

            for event_name, event_sim_time in schedule:
                if event_sim_time <= state.sim_time:
                    continue
                if event_sim_time > target_sim_time:
                    break

                state.sim_time = event_sim_time
                state.update_age_from_sim_time()

                result = process_event(event_name, state, event_sim_time % 24)

                if result["needs_llm"]:
                    # 追赶模式也调 LLM（受限流控制）
                    async with self._llm_semaphore:
                        llm_result = await asyncio.to_thread(
                            self._generate_story, state, result,
                        )
                        if llm_result:
                            result.update(llm_result)

                    evt = {
                        "event": "autonomous_event",
                        "event_name": result["event_name"],
                        "display_name": result["display_name"],
                        "sim_day": int(event_sim_time // 24),
                        "age_days": state.age_days,
                        "summary": result.get("summary", ""),
                    }
                    catchup_events.append(evt)
                    append_event(baby_id, evt)

                # 涌现事件掷骰
                emergent = roll_emergent_event(
                    event_sim_time % 24, state.current_phase,
                    state.life_tags, state.identity, state,
                )
                if emergent:
                    emergent_result = process_event(
                        emergent.name, state, event_sim_time % 24,
                    )
                    if emergent_result["needs_llm"]:
                        async with self._llm_semaphore:
                            llm_r = await asyncio.to_thread(
                                self._generate_story, state, emergent_result,
                            )
                            if llm_r:
                                emergent_result.update(llm_r)
                        evt = {
                            "event": "autonomous_event",
                            "event_name": emergent_result["event_name"],
                            "display_name": emergent_result["display_name"],
                            "sim_day": int(event_sim_time // 24),
                            "age_days": state.age_days,
                            "summary": emergent_result.get("summary", ""),
                        }
                        catchup_events.append(evt)
                        append_event(baby_id, evt)

            days_processed += 1
            # 推进到下一天
            state.sim_time = day_start + 24

        state.last_active_ts = time.time()
        save_state(state)

        return catchup_events

    # ============================================================
    # LLM 时段总结生成
    # ============================================================

    def _generate_story(self, state, result: dict) -> dict | None:
        """调用 LLM 生成时段总结。在线程池中执行。"""
        from cradle.mind import _call_and_parse
        from cradle.phases import EXPRESSION_MODES
        from cradle.state import Memory

        event = result.get("event")
        if not event:
            return None

        expression_mode = state.expression_mode
        constraints = EXPRESSION_MODES.get(
            expression_mode,
            EXPRESSION_MODES.get("cry_only", {}),
        )

        prompt = (
            f"You are simulating the inner life of a {state.species} child "
            f"aged {state.age_days} days.\n\n"
            f"An event just happened in the child's day:\n"
            f"Event: {event.display_name}\n"
            f"Description: {event.description}\n"
            f"Time of day: {result.get('sim_hour', 0):.0f}:00\n\n"
            f"Current state:\n"
            f"- Stress: {state.stress.stress_level:.2f}\n"
            f"- Expression mode: {expression_mode}\n"
            f"- Attachment: {state.attachment_style}\n"
            f"- Recent fears: "
            f"{', '.join(state.fears[-3:]) if state.fears else 'none'}\n"
            f"- Recent preferences: "
            f"{', '.join(state.preferences[-3:]) if state.preferences else 'none'}\n\n"
            f"Generate a brief summary of what happened and how the child "
            f"experienced it.\n\n"
            f"Rules:\n"
            f"1. Under 80 Chinese characters / 40 English words.\n"
            f"2. Expression must conform to mode: "
            f"{constraints.get('format', '')}\n"
            f"3. ANTI-AI: no literary language. Real child experience, messy "
            f"and immediate.\n"
            f"4. Respond in Chinese if context suggests Chinese-speaking "
            f"family.\n\n"
            f"Output JSON:\n"
            f'{{\n'
            f'  "summary": "what happened and child\'s reaction",\n'
            f'  "emotional_tone": "positive/negative/neutral",\n'
            f'  "new_preference": null or "discovered preference",\n'
            f'  "new_fear": null or "new fear",\n'
            f'  "stress_delta": -0.05 to 0.1\n'
            f'}}'
        )

        parsed = _call_and_parse(prompt)
        if not parsed or not isinstance(parsed, dict):
            return {"summary": f"{event.display_name} happened."}

        # 应用状态变化
        if parsed.get("stress_delta"):
            state.stress.stress_level = max(0.0, min(
                1.0, state.stress.stress_level + parsed["stress_delta"],
            ))
        if (
            parsed.get("new_preference")
            and parsed["new_preference"] not in state.preferences
        ):
            state.preferences.append(parsed["new_preference"])
        if (
            parsed.get("new_fear")
            and parsed["new_fear"] not in state.fears
        ):
            state.fears.append(parsed["new_fear"])

        # 创建记忆
        memory = Memory(
            phase=state.current_phase,
            age_days=state.age_days,
            event=event.display_name,
            stimulus=event.description,
            reaction=parsed.get("summary", ""),
            trace="",
            emotional_valence=parsed.get("emotional_tone", "neutral"),
            intensity=event.intensity,
        )
        state.memories.append(memory)
        # 限制记忆数量
        if len(state.memories) > 50:
            state.memories = state.memories[-50:]

        return {
            "summary": parsed.get("summary", ""),
            "emotional_tone": parsed.get("emotional_tone", "neutral"),
            "memory": memory.to_dict(),
            "changes": {
                k: v for k, v in {
                    "new_preference": parsed.get("new_preference"),
                    "new_fear": parsed.get("new_fear"),
                    "stress_delta": parsed.get("stress_delta"),
                }.items() if v
            },
        }


# ============================================================
# 模块级单例
# ============================================================

scheduler = EventScheduler()
