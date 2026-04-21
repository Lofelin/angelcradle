"""
DES 事件处理器：phase_start / day_tick / phase_complete。

所有函数接收 sched (LifelineScheduler 实例) 作为第一参数，
通过参数访问调度器内部状态，避免反向 import core.py。

[INPUT]: 依赖 scheduler/constants, events, naming, story, needs + cradle/ + world.py
[OUTPUT]: on_phase_start(), on_day_tick(), on_phase_complete(), process_story()
[POS]: scheduler/ 的事件分发目标，被 core.py 的 _dispatch 消费
[PROTOCOL]: 变更时更新此头部，然后检查 scheduler/CLAUDE.md
"""

from __future__ import annotations

import asyncio
import logging
import random
import time

from scheduler.constants import (
    CRADLE_EXIT_PHASE, NEED_EVAL_INTERVAL, STORY_BUDGET,
)
from scheduler.events import SimEvent

logger = logging.getLogger(__name__)


# ============================================================
# phase_start
# ============================================================

async def on_phase_start(sched, event: SimEvent) -> None:
    """初始化阶段，发射开始事件，调度第一天。重启恢复时跳过初始化。"""
    from cradle.state import load_state, save_state, append_event, get_baby_lock
    from cradle.phases import PHASES
    from cradle.nanny import _update_phase_state, _should_trigger_naming
    from events.definitions import get_event
    from scheduler.naming import auto_name

    baby_id = event.baby_id
    phase_idx = event.payload["phase_idx"]
    state_lock = get_baby_lock(baby_id)

    async with state_lock:
        state = load_state(baby_id)
    if state is None:
        return

    # 从全局配置同步速率（即时生效）
    from config import get_time_scale
    state.time_scale = get_time_scale()

    phase = PHASES[phase_idx]
    resume_day = max(phase.age_days[0], int(state.sim_time // 24))
    is_resume = resume_day > phase.age_days[0]

    # 初始化阶段追踪（首次和恢复都需要）
    sched._phase_story_count.setdefault(baby_id, {})[phase_idx] = 0
    sched._phase_llm_need_count.setdefault(baby_id, {})[phase_idx] = 0
    sched._quiet_start[baby_id] = None

    # ── 首次进入：完整初始化 ──
    if not is_resume:
        append_event(baby_id, {
            "event": "phase_start",
            "phase_index": phase_idx,
            "phase_name": phase.name,
            "phase_display": phase.display_name,
            "age_range": phase.age_range,
            "description": phase.description,
            "expression_mode": phase.expression_mode,
        })

        # 阶段状态自动更新（喂养/睡眠/情绪/体格，纯规则）
        phase_changes = _update_phase_state(state, phase_idx)
        if phase_changes:
            append_event(baby_id, {
                "event": "phase_state_update",
                "changes": phase_changes,
            })

        # 关键事件：命名仪式
        if _should_trigger_naming(state):
            naming = get_event("naming_ceremony")
            if naming:
                if state.time_scale == "turbo":
                    # turbo 模式：根据出生地文化习惯自动命名
                    state.name = auto_name(state)
                    # 将可能残留的待处理命名事件标记为已自动处理
                    for c in state.pending_criticals:
                        if c.get("event_name") == "naming_ceremony":
                            c["awaiting_parent"] = False
                            c["auto_resolved"] = True
                    entry = {
                        "event": "critical_event",
                        "event_name": "naming_ceremony",
                        "event_display": naming.display_name,
                        "description": naming.description,
                        "parent_choices": naming.parent_choices,
                        "awaiting_parent": False,
                        "auto_resolved": True,
                        "name": state.name,
                    }
                    append_event(baby_id, entry)
                    if not any(c.get("event_name") == "naming_ceremony" for c in state.pending_criticals):
                        state.pending_criticals.append(entry)
                else:
                    entry = {
                        "event": "critical_event",
                        "event_name": naming.name,
                        "event_display": naming.display_name,
                        "description": naming.description,
                        "parent_choices": naming.parent_choices,
                        "awaiting_parent": True,
                        "created_sim_day": int(state.sim_time // 24),
                    }
                    append_event(baby_id, entry)
                    state.pending_criticals.append(entry)

        async with state_lock:
            state.last_active_ts = time.time()
            save_state(state)

        logger.info(
            "开始阶段 %d (%s): day %d-%d, baby=%s",
            phase_idx, phase.name, phase.age_days[0], phase.age_days[1], baby_id,
        )
    # ── 必须事件：命名仪式（首次 + 恢复都检查）──
    has_pending_naming = any(
        c.get("event_name") == "naming_ceremony"
        for c in state.pending_criticals
    )
    if not is_resume:
        pass  # 首次进入时已在上面处理
    elif _should_trigger_naming(state) and not has_pending_naming:
        naming = get_event("naming_ceremony")
        if naming:
            entry = {
                "event": "critical_event",
                "event_name": naming.name,
                "event_display": naming.display_name,
                "description": naming.description,
                "parent_choices": naming.parent_choices,
                "awaiting_parent": True,
                "created_sim_day": int(state.sim_time // 24),
            }
            append_event(baby_id, entry)
            state.pending_criticals.append(entry)
            async with state_lock:
                save_state(state)
            logger.info("恢复时补发命名仪式: baby=%s", baby_id)

    if is_resume:
        logger.info(
            "恢复阶段 %d (%s): 从 day %d 继续（跳过 %d 天）, baby=%s",
            phase_idx, phase.name, resume_day,
            resume_day - phase.age_days[0], baby_id,
        )

    # 确保不超过阶段末尾
    if resume_day >= phase.age_days[1]:
        logger.info(
            "Agent %s phase %d 已跑完 (resume_day=%d >= end=%d)，直接完成",
            baby_id, phase_idx, resume_day, phase.age_days[1],
        )
        sched.push(SimEvent(
            sim_time=state.sim_time,
            baby_id=baby_id,
            event_type="phase_complete",
            payload={"phase_idx": phase_idx},
        ))
        return

    sched.push(SimEvent(
        sim_time=resume_day * 24.0,
        baby_id=baby_id,
        event_type="day_tick",
        payload={"day": resume_day, "phase_idx": phase_idx},
    ))


# ============================================================
# day_tick
# ============================================================

async def on_day_tick(sched, event: SimEvent) -> None:
    """处理一天：routine → snapshot → need → emergent → 调度下一天。"""
    from cradle.state import load_state, save_state, append_event, get_baby_lock
    from cradle.phases import PHASES
    from world import (
        generate_daily_schedule, process_event, is_story_worthy,
        template_reaction, generate_world_snapshot, pick_daily_event,
        snapshot_event_to_event, _needs_snapshot_refresh, SnapshotEvent,
    )
    from scheduler.story import generate_story, calc_skip_target, batch_skip_days
    from scheduler.needs import handle_need, rule_based_need

    baby_id = event.baby_id
    day = event.payload["day"]
    phase_idx = event.payload["phase_idx"]
    phase = PHASES[phase_idx]
    end_day = phase.age_days[1]
    state_lock = get_baby_lock(baby_id)

    async with state_lock:
        state = load_state(baby_id)
    if state is None:
        return

    # 从全局配置同步速率（即时生效，解决切换竞态）
    from config import get_time_scale
    state.time_scale = get_time_scale()

    # 每天都刷新活跃时间戳（内存），避免前端在 LLM 调用期间误判停滞
    state.last_active_ts = time.time()

    # ── 0a. 已命名婴儿：将残留的 naming_ceremony 标记为已处理 ──
    naming_fixed = False
    for c in state.pending_criticals:
        if c.get("event_name") == "naming_ceremony" and c.get("awaiting_parent"):
            if state.name:
                c["awaiting_parent"] = False
                c["auto_resolved"] = True
                naming_fixed = True
    if naming_fixed:
        append_event(baby_id, {
            "event": "critical_expired",
            "event_name": "naming_ceremony",
            "event_display": "Naming Ceremony",
            "default_action": "auto_named",
            "expired_after_days": 0,
        })
        logger.info("标记已命名婴儿的命名事件为已处理: baby=%s", baby_id)
        async with state_lock:
            save_state(state)

    # ── 0b. 关键事件自动过期（超过 30 sim_days 未回应 → 默认选项处理 + 标记已错过）──
    expired = [
        c for c in state.pending_criticals
        if c.get("awaiting_parent")                   # 只处理仍在等待的
        and c.get("event_name") != "naming_ceremony"  # 命名不自动过期
        and day - c.get("created_sim_day", day) >= 30
    ]
    if expired:
        from cradle.nanny import resolve_critical_event
        expired_names: set[str] = set()
        # 选择有效的 caregiver_id
        caregiver_id = (
            "primary_parent"
            if "primary_parent" in state.caregivers
            else next(iter(state.caregivers), "primary_parent")
        )
        for c in expired:
            choices = c.get("parent_choices", [])
            first_choice = choices[0] if choices else {}
            default_action = first_choice.get("action", "observe")
            resolve_critical_event(
                state,
                event_name=c["event_name"],
                parent_action=default_action,
                caregiver_id=caregiver_id,
            )
            expired_names.add(c["event_name"])
            append_event(baby_id, {
                "event": "critical_expired",
                "event_name": c["event_name"],
                "event_display": c.get("event_display", ""),
                "default_action": default_action,
                "expired_after_days": day - c.get("created_sim_day", day),
            })
            logger.info(
                "关键事件过期自动处理: %s → %s, baby=%s",
                c["event_name"], default_action, baby_id,
            )
        # 一次性标记所有过期事件为已处理
        for p in state.pending_criticals:
            if p.get("event_name") in expired_names:
                p["awaiting_parent"] = False
                p["expired"] = True
        async with state_lock:
            save_state(state)

    day_offset = day * 24

    # ── 1. 批量 routine（不调 LLM）──
    # routine 阶段修改 sim_time/stress 等字段，在 state_lock 内完成并保存，
    # 防止后续 LLM 调用期间 /interact 端点读到过期 state 或覆盖修改
    async with state_lock:
        schedule = generate_daily_schedule(phase_idx, state.life_tags, day_offset)
        for event_name, sim_time in schedule:
            state.sim_time = sim_time
            state.update_age_from_sim_time()
            process_event(event_name, state, sim_time % 24)

        # 推进到当天结束
        state.sim_time = day_offset + 24
        state.update_age_from_sim_time()
        save_state(state)

    is_turbo = state.time_scale == "turbo"

    # ── turbo 快车道：每阶段仅 1 次 LLM 叙事（保留收割），然后跳到阶段末 ──
    if is_turbo:
        state.turbo_generated = True

        # 从静态池抽一个 story-worthy 事件，做 1 次 LLM 叙事（收割 life_tag_hint）
        from events import roll_emergent_event
        roll_hour = random.uniform(8.0, 18.0)
        emergent_raw = roll_emergent_event(
            roll_hour, phase_idx, state.life_tags, state.identity, state,
        )
        if emergent_raw is not None:
            state.triggered_events.add(emergent_raw.name)
            # turbo 用 1 次 LLM 叙事保留因果链
            async with sched._llm_semaphore:
                result = await asyncio.to_thread(
                    generate_story, state, emergent_raw, roll_hour,
                )
            append_event(baby_id, {
                "event": "autonomous_event",
                "event_name": emergent_raw.name,
                "display_name": emergent_raw.display_name,
                "sim_day": day,
                "sim_hour": round(roll_hour, 1),
                "age_days": state.age_days,
                "summary": result.get("summary", ""),
                "changes": result.get("changes", {}),
            })

        # turbo 模式也触发一次主动需求，让父母有机会互动
        try:
            need = rule_based_need(state, day)
            if need:
                state.initiative.last_initiative_ts = float(day)
                await handle_need(sched, baby_id, state, need, state_lock)
        except Exception as e:
            logger.warning("turbo 需求评估异常: %s", e)

        # 直接跳到阶段末
        skip_to = end_day
        if day + 1 < skip_to:
            batch_skip_days(
                sched, baby_id, state, day + 1, skip_to, phase_idx,
            )
        state.sim_time = end_day * 24
        state.update_age_from_sim_time()

        # 保存并调度阶段完成
        async with state_lock:
            state.last_active_ts = time.time()
            save_state(state)
        sched.push(SimEvent(
            sim_time=state.sim_time,
            baby_id=baby_id,
            event_type="phase_complete",
            payload={"phase_idx": phase_idx},
        ))
        return

    # ── 2. 世界快照刷新 ──
    if _needs_snapshot_refresh(day, state):
        prev_snapshot = state.world_snapshot
        async with sched._llm_semaphore:
            snapshot = await asyncio.to_thread(
                generate_world_snapshot, state, prev_snapshot,
            )
        if snapshot:
            state.world_snapshot = snapshot
            append_event(baby_id, {
                "event": "world_snapshot",
                "weather": snapshot.weather_pattern,
                "family_arc": snapshot.family_arc,
                "mood": snapshot.ambient_mood,
                "event_count": len(snapshot.events),
                "surprise_count": len(snapshot.surprise_pool),
                "days": f"{snapshot.start_day}-{snapshot.end_day}",
            })
        else:
            state.world_snapshot = None
            append_event(baby_id, {
                "event": "world_snapshot_fallback",
                "reason": "LLM generation failed",
            })
        # 快照写入后立即持久化，防止崩溃丢失世界状态
        async with state_lock:
            save_state(state)

    # ── 2.5 主动需求评估 ──
    MIN_LLM_NEEDS_PER_PHASE = 2
    need_interval = NEED_EVAL_INTERVAL.get(state.time_scale, 3)
    if day % need_interval == 0:
        try:
            llm_count = sched._phase_llm_need_count.get(
                baby_id, {},
            ).get(phase_idx, 0)
            use_llm = (
                state.time_scale == "slow"
                or llm_count < MIN_LLM_NEEDS_PER_PHASE
            )
            if use_llm:
                from initiative_needs import evaluate_need
                need = await asyncio.to_thread(evaluate_need, state, day)
                counts = sched._phase_llm_need_count.setdefault(baby_id, {})
                counts[phase_idx] = counts.get(phase_idx, 0) + 1
            else:
                need = rule_based_need(state, day)
            if need:
                state.initiative.last_initiative_ts = float(day)
                await handle_need(sched, baby_id, state, need, state_lock)
        except Exception as e:
            logger.warning("需求评估异常: %s", e)

    # ── 3. 涌现事件 ──
    emergent_raw = pick_daily_event(state.world_snapshot, day, state)
    had_story = False

    if emergent_raw is not None:
        roll_hour = random.uniform(6.0, 20.0)
        emergent = (
            snapshot_event_to_event(emergent_raw)
            if isinstance(emergent_raw, SnapshotEvent)
            else emergent_raw
        )
        state.triggered_events.add(emergent.name)

        # 3b. 关键事件走 pending_criticals
        if emergent.category == "critical" and emergent.requires_parent:
            sched._last_critical_day[baby_id] = day
            entry = {
                "event": "critical_event",
                "event_name": emergent.name,
                "event_display": emergent.display_name,
                "description": emergent.description,
                "parent_choices": emergent.parent_choices,
                "awaiting_parent": True,
                "sim_day": day,
                "created_sim_day": day,
            }
            append_event(baby_id, entry)
            state.pending_criticals.append(entry)
        else:
            story_count = sched._phase_story_count.get(
                baby_id, {},
            ).get(phase_idx, 0)
            budget = STORY_BUDGET.get(state.time_scale, 5)
            remaining = budget - story_count

            if remaining > 0 and is_story_worthy(emergent, state):
                had_story = await process_story(
                    sched, baby_id, state, emergent, day, roll_hour,
                    phase_idx, state_lock,
                )
            else:
                reaction = template_reaction(
                    emergent, state, state.world_snapshot,
                )
                # 优先用事件自带描述（snapshot LLM 生成），fallback 到模板
                desc = getattr(emergent, "description", "")
                append_event(baby_id, {
                    "event": "autonomous_routine",
                    "event_name": emergent.name,
                    "display_name": emergent.display_name,
                    "sim_day": day,
                    "sim_hour": round(roll_hour, 1),
                    "age_days": state.age_days,
                    "summary": desc or reaction["summary"],
                    "changes": {"stress_delta": reaction["stress_delta"]},
                })

    # ── 3c. 强制注入关键事件（连续无 critical 超过阈值时触发）──
    active_criticals = [c for c in state.pending_criticals if c.get("awaiting_parent")]
    if not active_criticals:
        last_critical_day = sched._last_critical_day.get(baby_id, 0)
        critical_gap = day - last_critical_day
        # 阶段天数的 40% 无关键事件时强制注入
        phase_days = phase.age_days[1] - phase.age_days[0]
        inject_threshold = max(30, int(phase_days * 0.4))
        if critical_gap >= inject_threshold:
            from events.definitions import CRITICAL_EVENTS
            candidates = [
                e for e in CRITICAL_EVENTS
                if e.phase_range[0] <= phase_idx <= e.phase_range[1]
                and e.name not in state.triggered_events
                and e.weight > 0
            ]
            if candidates:
                weights = [e.weight for e in candidates]
                forced = random.choices(candidates, weights=weights, k=1)[0]
                state.triggered_events.add(forced.name)
                entry = {
                    "event": "critical_event",
                    "event_name": forced.name,
                    "event_display": forced.display_name,
                    "description": forced.description,
                    "parent_choices": forced.parent_choices,
                    "awaiting_parent": True,
                    "sim_day": day,
                    "created_sim_day": day,
                    "forced": True,
                }
                append_event(baby_id, entry)
                state.pending_criticals.append(entry)
                sched._last_critical_day[baby_id] = day

    # ── 4. 平静日追踪 ──
    if had_story:
        sched._quiet_start[baby_id] = None
    else:
        quiet_start = sched._quiet_start.get(baby_id)
        if quiet_start is None:
            sched._quiet_start[baby_id] = day
        elif day - quiet_start >= 30:
            sched.flush_quiet_days(
                baby_id, state, quiet_start, day, phase_idx,
            )
            sched._quiet_start[baby_id] = None

    # ── 5. 定期保存（fast 模式每天保存，其他每 N 天）──
    save_interval = {"turbo": 9999, "fast": 1, "normal": 5, "slow": 10}.get(state.time_scale, 10)
    if day % save_interval == 0:
        async with state_lock:
            state.last_active_ts = time.time()
            save_state(state)

    # ── 6. 节奏延迟 ──
    if had_story or emergent_raw is not None:
        await sched.pace(state)

    # ── 7. 批量跳天 + 调度下一天或阶段完成 ──
    next_day = day + 1

    # fast 模式：跳过无事件的日子
    if state.time_scale in ("fast", "normal") and next_day < end_day:
        skip_to = calc_skip_target(next_day, end_day, state)
        if skip_to > next_day:
            batch_skip_days(
                sched, baby_id, state, next_day, skip_to, phase_idx,
            )
            next_day = skip_to
            # 跳天后立即保存，防止重启回退
            async with state_lock:
                state.last_active_ts = time.time()
                save_state(state)

    if next_day >= end_day:
        # flush 尾部平静日
        quiet_start = sched._quiet_start.get(baby_id)
        if quiet_start is not None:
            sched.flush_quiet_days(
                baby_id, state, quiet_start, end_day - 1, phase_idx,
            )
            sched._quiet_start[baby_id] = None

        # 阶段末保存
        async with state_lock:
            state.last_active_ts = time.time()
            save_state(state)

        sched.push(SimEvent(
            sim_time=state.sim_time,
            baby_id=baby_id,
            event_type="phase_complete",
            payload={"phase_idx": phase_idx},
        ))
    else:
        sched.push(SimEvent(
            sim_time=next_day * 24.0,
            baby_id=baby_id,
            event_type="day_tick",
            payload={"day": next_day, "phase_idx": phase_idx},
        ))


# ============================================================
# Story 处理（从 day_tick 抽出）
# ============================================================

async def process_story(
    sched, baby_id: str, state, emergent, day: int,
    roll_hour: float, phase_idx: int, state_lock: asyncio.Lock,
) -> bool:
    """处理 story_worthy 涌现事件。返回 True 表示消耗了 story 预算。"""
    from cradle.state import append_event, save_state
    from scheduler.story import generate_story

    # flush 之前的平静日
    quiet_start = sched._quiet_start.get(baby_id)
    if quiet_start is not None:
        sched.flush_quiet_days(baby_id, state, quiet_start, day - 1, phase_idx)
        await sched.pace(state)
        sched._quiet_start[baby_id] = None

    append_event(baby_id, {
        "event": "autonomous_processing",
        "event_name": emergent.name,
        "display_name": emergent.display_name,
        "sim_day": day,
        "sim_hour": round(roll_hour, 1),
    })

    async with sched._llm_semaphore:
        result = await asyncio.to_thread(
            generate_story, state, emergent, roll_hour,
        )

    sse_event = {
        "event": "autonomous_event",
        "event_name": emergent.name,
        "display_name": emergent.display_name,
        "sim_day": day,
        "sim_hour": round(roll_hour, 1),
        "age_days": state.age_days,
        "changes": result.get("changes", {}),
        "summary": result.get("summary", ""),
    }
    if result.get("memory"):
        sse_event["memory"] = result["memory"]
    append_event(baby_id, sse_event)

    # 更新 story 计数
    counts = sched._phase_story_count.setdefault(baby_id, {})
    counts[phase_idx] = counts.get(phase_idx, 0) + 1

    async with state_lock:
        save_state(state)

    return True


# ============================================================
# phase_complete
# ============================================================

async def on_phase_complete(sched, event: SimEvent) -> None:
    """能力解锁 + 里程碑 + 压力回退/恢复 + LLM 总结 + 调度下一阶段。"""
    from cradle.state import load_state, save_state, append_event, get_baby_lock
    from cradle.nanny import (
        complete_phase, _check_capability_unlocks, _check_milestones,
        _check_stress_regression, _check_regression_recovery,
    )
    from cradle.phases import PHASES

    baby_id = event.baby_id
    phase_idx = event.payload["phase_idx"]
    state_lock = get_baby_lock(baby_id)

    async with state_lock:
        state = load_state(baby_id)
    if state is None:
        return

    # 从全局配置同步速率
    from config import get_time_scale
    state.time_scale = get_time_scale()

    # 阶段末：压力回退 / 恢复检测
    regressed = _check_stress_regression(state)
    if regressed:
        append_event(baby_id, {
            "event": "stress_regression",
            "regressed": regressed,
            "stress_level": round(state.stress.stress_level, 2),
        })
        # 里程碑：能力回退（负向里程碑，生命中值得记住）
        try:
            from memory import record_milestone
            for cap in regressed:
                _subject = cap if isinstance(cap, str) else cap.get("capability", "")
                record_milestone(
                    state, baby_id,
                    kind="capability_lost",
                    subject=str(_subject),
                    description=f"因压力回退失去能力: {_subject}",
                    intensity=0.7,
                    tags=[f"phase:{phase_idx}", f"capability:regress:{_subject}"],
                )
        except Exception as e:
            logger.warning("record_milestone(capability_lost) failed: %s", e)
    recovered = _check_regression_recovery(state)
    if recovered:
        append_event(baby_id, {
            "event": "regression_recovery",
            "recovered": [r["capability"] for r in recovered],
            "strengthened": [
                r["capability"] for r in recovered if r["strengthened"]
            ],
            "stress_level": round(state.stress.stress_level, 2),
        })
        # 里程碑：回退恢复（正向里程碑）
        try:
            from memory import record_milestone
            for r in recovered:
                _cap = r.get("capability", "")
                record_milestone(
                    state, baby_id,
                    kind="capability_recovered",
                    subject=str(_cap),
                    description=f"从压力回退中恢复能力: {_cap}",
                    intensity=0.75,
                    tags=[f"phase:{phase_idx}", f"capability:unlock:{_cap}"],
                )
        except Exception as e:
            logger.warning("record_milestone(capability_recovered) failed: %s", e)

    # 能力解锁
    new_caps = _check_capability_unlocks(state, phase_idx)
    if new_caps:
        append_event(baby_id, {
            "event": "capabilities_unlocked",
            "capabilities": new_caps,
        })
        # 里程碑：能力获得（正向高权重）
        try:
            from memory import record_milestone
            for cap in new_caps:
                record_milestone(
                    state, baby_id,
                    kind="capability_gained",
                    subject=str(cap),
                    description=f"解锁新能力: {cap}",
                    intensity=0.85,
                    tags=[f"phase:{phase_idx}", f"capability:unlock:{cap}"],
                )
        except Exception as e:
            logger.warning("record_milestone(capability_gained) failed: %s", e)

    # 里程碑
    milestones = _check_milestones(state, new_caps)
    if milestones:
        append_event(baby_id, {
            "event": "milestones",
            "milestones": [m.to_dict() for m in milestones],
        })
        # memory.Milestone：发育里程碑
        try:
            from memory import record_milestone
            for m in milestones:
                record_milestone(
                    state, baby_id,
                    kind="milestone_reached",
                    subject=getattr(m, "name", "") or "",
                    description=getattr(m, "description", "") or "",
                    intensity=0.8,
                    tags=[f"phase:{phase_idx}"],
                )
        except Exception as e:
            logger.warning("record_milestone(milestone_reached) failed: %s", e)

    # LLM 阶段总结
    append_event(baby_id, {
        "event": "phase_completing",
        "phase_index": phase_idx,
    })
    async with sched._llm_semaphore:
        summary = await asyncio.to_thread(complete_phase, state)

    next_phase_name = (
        PHASES[state.current_phase].display_name
        if state.current_phase < len(PHASES) else None
    )
    append_event(baby_id, {
        "event": "phase_completed",
        "phase_index": phase_idx,
        "phase_name": PHASES[phase_idx].name,
        "summary": summary,
        "next_phase": next_phase_name,
    })
    # 里程碑：阶段推进（生命结构性节点）
    try:
        from memory import record_milestone
        _summary_text = ""
        if isinstance(summary, dict):
            _summary_text = summary.get("summary", "") or ""
        elif isinstance(summary, str):
            _summary_text = summary
        record_milestone(
            state, baby_id,
            kind="phase_advanced",
            subject=PHASES[phase_idx].name,
            description=_summary_text[:200],
            intensity=0.9,
            tags=[f"phase:{phase_idx}"],
        )
    except Exception as e:
        logger.warning("record_milestone(phase_advanced) failed: %s", e)

    async with state_lock:
        state.last_active_ts = time.time()
        save_state(state)

    logger.info(
        "阶段完成: baby=%s phase=%d → %d",
        baby_id, phase_idx, state.current_phase,
    )

    # 肖像更新检查（每 5 岁触发）
    try:
        from portrait import should_update_portrait, generate_portrait
        target_age = should_update_portrait(state.age_days)
        if target_age is not None:
            await asyncio.to_thread(generate_portrait, state, target_age)
            append_event(baby_id, {
                "event": "portrait_updated",
                "age_years": target_age,
            })
    except Exception:
        logger.debug("Portrait update skipped", exc_info=True)

    # 调度下一阶段或摇篮完成
    end_phase = min(CRADLE_EXIT_PHASE, len(PHASES))
    next_phase = phase_idx + 1
    if next_phase < end_phase:
        sched.push(SimEvent(
            sim_time=state.sim_time,
            baby_id=baby_id,
            event_type="phase_start",
            payload={"phase_idx": next_phase},
        ))
    else:
        append_event(baby_id, {
            "event": "cradle_complete",
            "final_phase": end_phase - 1,
            "age_days": state.age_days,
        })
        logger.info(
            "Agent %s 摇篮完成 (phase 0-%d)", baby_id, end_phase - 1,
        )
        # 里程碑：摇篮完成（一生最重要节点之一）
        try:
            from memory import record_milestone
            record_milestone(
                state, baby_id,
                kind="cradle_complete",
                subject="cradle_complete",
                description=f"完成全部 {end_phase} 个摇篮阶段",
                intensity=1.0,
                tags=[f"phase:{end_phase - 1}"],
            )
        except Exception as e:
            logger.warning("record_milestone(cradle_complete) failed: %s", e)
