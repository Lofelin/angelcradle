"""
LLM 叙事生成 + 批量跳天加速。

[INPUT]: 依赖 cradle/mind.py（LLM）、cradle/state.py、cradle/identity.py
[OUTPUT]: generate_story(), calc_skip_target(), batch_skip_days()
[POS]: scheduler/ 的 LLM 调用模块，被 handlers.py 消费
[PROTOCOL]: 变更时更新此头部，然后检查 scheduler/CLAUDE.md
"""

from __future__ import annotations

import logging
import random

logger = logging.getLogger(__name__)


# ============================================================
# LLM 故事生成
# ============================================================

def generate_story(state, event, sim_hour: float) -> dict:
    """调用 LLM 生成时段总结。在线程池中执行（同步函数）。"""
    from cradle.mind import _call_and_parse
    from cradle.phases import EXPRESSION_MODES
    from cradle.state import Memory

    expression_mode = state.expression_mode
    constraints = EXPRESSION_MODES.get(
        expression_mode,
        EXPRESSION_MODES.get("cry_only", {}),
    )

    # 保姆视角叙事
    from cradle.identity import compute_interference
    identity_hints = ""
    if state.identity.constraints:
        identity_hints = "\n".join(
            f"- {c}" for c in state.identity.constraints[:3]
        )
    # 约束干涉：组合效应（代码预计算，权威性高于独立约束）
    interference = compute_interference(state.identity, state)

    prompt = (
        f"You are the nanny caring for a {state.species} infant "
        f"aged {state.age_days} days. You observe, act, and narrate "
        f"in first person.\n\n"
        f"Something just happened:\n"
        f"Event: {event.display_name}\n"
        f"Description: {event.description}\n"
        f"Time of day: {sim_hour:.0f}:00\n\n"
        f"The child:\n"
        f"- Stress: {state.stress.stress_level:.2f}\n"
        f"- Expression mode: {expression_mode}\n"
        f"- Attachment: {state.attachment_style}\n"
        f"- Fears: "
        f"{', '.join(state.fears[-3:]) if state.fears else 'none'}\n"
        f"- Preferences: "
        f"{', '.join(state.preferences[-3:]) if state.preferences else 'none'}\n"
    )
    if identity_hints:
        prompt += f"\nInnate traits:\n{identity_hints}\n"
    if interference:
        prompt += (
            f"\n## Combined trait effects (AUTHORITATIVE — code-computed):\n"
            f"{interference}\n"
        )

    # 注入已观察到的发育线索（trace/growth_signal 反哺）
    observed = set()
    for m in state.memories[-20:]:
        if hasattr(m, "trace") and m.trace:
            observed.add(m.trace)
        if hasattr(m, "growth_signal") and m.growth_signal:
            observed.add(m.growth_signal)
    if observed:
        prompt += "\nDevelopmental threads observed so far:\n"
        for t in list(observed)[:5]:
            prompt += f"- {t}\n"

    # 当前 life_tags（供 LLM 参考并可能扩展）
    if state.life_tags:
        prompt += f"\nLife context tags: {', '.join(list(state.life_tags)[:10])}\n"

    prompt += (
        f"\nNarrate what happened from YOUR perspective as the nanny. "
        f"Include what you observed, what you did, and the child's "
        f"reaction.\n\n"
        f"Rules:\n"
        f"1. Under 80 Chinese characters / 40 English words.\n"
        f"2. Child's expression must conform to mode: "
        f"{constraints.get('format', '')}\n"
        f"3. ANTI-AI: no literary language. Real, messy, immediate.\n"
        f"4. Respond in English.\n"
        f"5. Inside JSON string values, NEVER use ASCII double quotes "
        f"(\"). For quoted speech or emphasis use \u300c\u300d or \u300e\u300f instead. "
        f"Any \" inside a value breaks JSON parsing.\n\n"
        f"Output JSON:\n"
        f'{{\n'
        f'  "summary": "nanny narration of what happened",\n'
        f'  "emotional_tone": "positive/negative/neutral",\n'
        f'  "new_preference": null or "discovered preference",\n'
        f'  "new_fear": null or "new fear",\n'
        f'  "stress_delta": -0.05 to 0.1,\n'
        f'  "trace": "which innate trait shaped this reaction (short)",\n'
        f'  "life_tag_hint": null or "a_behavioral_tag"\n'
        f'}}'
    )

    parsed = _call_and_parse(prompt, metadata={
        "baby_id": state.baby_id, "phase": state.current_phase,
        "callsite": "generate_story",
    })
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

    # 叙事收割：life_tag_hint → state.life_tags
    tag_hint = parsed.get("life_tag_hint")
    if tag_hint and isinstance(tag_hint, str) and len(state.life_tags) < 50:
        state.life_tags.add(tag_hint)

    # 创建记忆（含 trace）
    # 保留 Memory 对象构造：trace 来自 LLM 英文句子，语义不可由 record_moment 自动降级生成
    trace = parsed.get("trace", "") or ""
    memory = Memory(
        phase=state.current_phase,
        age_days=state.age_days,
        event=event.display_name,
        stimulus=event.description,
        reaction=parsed.get("summary", ""),
        trace=trace,
        emotional_valence=parsed.get("emotional_tone", "neutral"),
        intensity=event.intensity,
    )
    # 统一通过 memory.record_moment 写入（jsonl 真相源 + state.memories 降级回写守契约）
    from memory import record_moment
    from cradle.causality import generate_cause_tags, generate_effect_tags
    _event_data = {
        "sensory_channels": getattr(event, "sensory_channels", []),
        "intensity": getattr(event, "intensity", 0.5),
        "category": getattr(event, "category", ""),
    }
    _cause_tags = generate_cause_tags(_event_data, state.identity, state)
    record_moment(
        state, state.baby_id,
        actor="world", target="self",
        trigger=event.name if hasattr(event, "name") else event.display_name,
        action=event.description,
        response=parsed.get("summary", ""),
        outcome="neutral",
        valence=parsed.get("emotional_tone", "neutral"),
        intensity=event.intensity,
        cause_tags=_cause_tags,
        effect_tags=[],
        _legacy_memory_override=memory,  # 保留 LLM trace 原文等旧字段
    )
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
                "life_tag_hint": tag_hint,
            }.items() if v
        },
    }


# ============================================================
# 批量跳天���fast 模式加速）
# ============================================================

def calc_skip_target(from_day: int, end_day: int, state) -> int:
    """
    计算可以跳到的���标天。跳过没有 snapshot 事件的安静���。

    停在以下边界：
    1. 有 snapshot 事件的天
    2. snapshot 刷新边界
    3. 最多跳 30 天（保留 surprise 机会）
    """
    snapshot = state.world_snapshot
    if snapshot is None:
        return from_day  # 无快照无法预测

    # 上���：snapshot 边界 / 阶段边界 / 最多跳 30 天
    ceiling = min(end_day, snapshot.end_day, from_day + 30)

    for d in range(from_day, ceiling):
        day_in_snap = d - snapshot.start_day
        for evt in snapshot.events:
            if (
                evt.day_index == day_in_snap
                and evt.name not in snapshot.used_events
            ):
                return d  # 这天有事件，停在这

    return ceiling


def batch_skip_days(
    sched, baby_id: str, state,
    from_day: int, to_day: int, phase_idx: int,
) -> None:
    """
    批量处理 [from_day, to_day) 的安静日：
    - 批量应��� routine 状态变化
    - 随机 surprise 掷骰
    - 推进 sim_time
    """
    from cradle.state import append_event
    from world import template_reaction, snapshot_event_to_event, SnapshotEvent

    days = to_day - from_day
    if days <= 0:
        return

    # 批量 routine 效果：每天 ~4 餐 * -0.02 + ~2 睡 * -0.05 = -0.18 stress
    if state.stress:
        total_reduction = 0.18 * days
        state.stress.stress_level = max(
            0.0, state.stress.stress_level - total_reduction,
        )

    # surprise 掷骰：P(至少一次) = 1 - 0.85^days
    snapshot = state.world_snapshot
    if snapshot and snapshot.surprise_pool:
        prob_at_least_one = 1.0 - (0.85 ** days)
        if random.random() < prob_at_least_one:
            available = [
                e for e in snapshot.surprise_pool
                if e.name not in snapshot.used_events
            ]
            if available:
                chosen = random.choice(available)
                snapshot.used_events.add(chosen.name)
                state.triggered_events.add(chosen.name)
                evt_obj = (
                    snapshot_event_to_event(chosen)
                    if isinstance(chosen, SnapshotEvent)
                    else chosen
                )
                reaction = template_reaction(evt_obj, state, snapshot)
                roll_day = from_day + random.randint(0, days - 1)
                desc = getattr(chosen, "description", "")
                append_event(baby_id, {
                    "event": "autonomous_routine",
                    "event_name": chosen.name,
                    "display_name": chosen.display_name,
                    "sim_day": roll_day,
                    "age_days": state.age_days,
                    "summary": desc or reaction["summary"],
                    "changes": {"stress_delta": reaction["stress_delta"]},
                })

    # 推进时间
    state.sim_time = to_day * 24
    state.update_age_from_sim_time()

    # 发射压缩摘要
    sched.flush_quiet_days(baby_id, state, from_day, to_day - 1, phase_idx)

    logger.debug(
        "批量跳过 %d 天: baby=%s day %d→%d",
        days, baby_id, from_day, to_day,
    )
