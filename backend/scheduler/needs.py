"""
主动需求处理 + 保姆降级 + 规则引擎评估。

[INPUT]: 依赖 scheduler/events.py（信号）、initiative_needs、cradle/
[OUTPUT]: handle_need(), nanny_fallback(), rule_based_need()
[POS]: scheduler/ 的需求处理模块，被 handlers.py 消费
[PROTOCOL]: 变更时更新此头部，然后检查 scheduler/CLAUDE.md
"""

from __future__ import annotations

import asyncio
import logging
import random
import time

from scheduler.events import get_or_create_respond_event

logger = logging.getLogger(__name__)


# ============================================================
# 主���需求处理
# ============================================================

async def handle_need(
    sched, baby_id: str, state, need: dict, state_lock: asyncio.Lock,
) -> None:
    """处理一次宝宝需求：写事件 → 等待用户响应 → 超时保姆降级。"""
    from cradle.state import append_event, save_state

    need_id = need.get("intent_id") or f"need-{int(time.time())}"
    ini = state.initiative

    ini.pending_initiative_id = need_id

    # 按速度缩放超时（快速模式下不让模拟长时间阻塞）
    need_timeout = {"slow": 300, "normal": 15, "fast": 1, "turbo": 2}
    real_timeout = need_timeout.get(state.time_scale, 15)

    from cradle.initiative_needs import TRIGGER_LABELS
    trigger_label = TRIGGER_LABELS.get(need["trigger"], need["trigger"])
    append_event(baby_id, {
        "event": "baby_need",
        "need_id": need_id,
        "trigger": need["trigger"],
        "trigger_label": trigger_label,
        "urgency": need["urgency"].value,
        "timeout_sec": int(real_timeout),
        "expression": need.get("expression", ""),
        "signal": need.get("signal", ""),
        "facial": need.get("facial", ""),
        "body": need.get("body", ""),
        "behavior_type": need.get("behavior_type", "verbal"),
        "parent_hint": need.get("parent_hint", ""),
        "age_days": state.age_days,
        "sim_day": int(state.sim_time // 24),
    })

    # 将需求作为 baby 消息推送到 DM 会话（供前端聊天窗口展示）
    try:
        await _publish_need_to_dm(baby_id, need, need_id, trigger_label)
    except Exception as e:
        logger.warning("Failed to publish need %s to DM conversation: %s", need_id, e)

    async with state_lock:
        save_state(state)

    # 等待用户响应或超时
    respond_event = get_or_create_respond_event(baby_id)
    respond_event.clear()

    try:
        await asyncio.wait_for(
            respond_event.wait(),
            timeout=real_timeout,
        )
        append_event(baby_id, {
            "event": "need_responded",
            "need_id": need_id,
            "responder": "parent",
            "trigger": need["trigger"],
        })
        logger.info(
            "需求 %s 被用户响应: baby=%s trigger=%s",
            need_id, baby_id, need["trigger"],
        )
    except asyncio.TimeoutError:
        await nanny_fallback(
            sched, baby_id, state, need, need_id, state_lock,
        )


async def _publish_need_to_dm(
    baby_id: str, need: dict, need_id: str, trigger_label: str,
) -> None:
    """
    将主动需求推入 baby 的 DM 会话。幂等：DM 不存在则创建。

    消息 content 优先使用 expression（宝宝的表达）；缺失时降级为 trigger_label。
    subtype="need" + urgency 让前端区分渲染。
    """
    from cradle import get_or_create_conversation, make_conv_id, post_baby_message

    get_or_create_conversation([baby_id], "dm")
    dm_id = make_conv_id([baby_id], "dm")

    content = need.get("expression") or need.get("signal") or trigger_label
    await post_baby_message(
        dm_id, baby_id, content,
        subtype="need",
        urgency=need["urgency"].value,
    )


async def nanny_fallback(
    sched, baby_id: str, state, need: dict,
    need_id: str, state_lock: asyncio.Lock,
) -> None:
    """保姆降级处理：纯规则模板，不调 LLM。"""
    from cradle.state import append_event, save_state
    from cradle.initiative_needs import pick_nanny_response
    from cradle.heartbeat_provider import shift_attachment_toward_avoidant

    ini = state.initiative

    template = pick_nanny_response(need["trigger"], state.caregivers)

    state.stress.stress_level = max(0.0, state.stress.stress_level - 0.05)

    ini.consecutive_ignores += 1
    ini.total_ignored += 1
    ini.pending_initiative_id = ""
    ini.pending_initiative_type = ""
    ini.pending_behavior_type = ""

    # 连续忽略 >= 3 次：依恋向 avoidant 偏移
    attachment_change = "none"
    if ini.consecutive_ignores >= 3:
        shift_attachment_toward_avoidant(state)
        attachment_change = "toward_avoidant"

    append_event(baby_id, {
        "event": "need_responded",
        "need_id": need_id,
        "responder": template["role"],
        "trigger": need["trigger"],
        "nanny_text": template["text"],
        "stress_delta": -0.05,
        "attachment_change": attachment_change,
    })

    # 记忆：主动需求被保姆降级响应（非 parent 响应，价值较低但仍是生命经验）
    try:
        from memory import record_moment
        record_moment(
            state, baby_id,
            actor=f"caregiver:{template['role']}",
            target="self",
            trigger=f"need_fallback:{need['trigger']}",
            action=template["text"],
            response="",
            outcome="fallback",
            valence="neutral",
            intensity=0.4,
            cause_tags=[f"phase:{state.current_phase}"],
            effect_tags=["memory:neutral"] if attachment_change == "none"
                        else ["memory:negative", "attachment:toward_avoidant"],
        )
    except Exception as e:
        logger.warning("record_moment for nanny_fallback failed: %s", e)

    async with state_lock:
        save_state(state)

    logger.info(
        "需求 %s 超时，%s 代替处理: baby=%s trigger=%s",
        need_id, template["role"], baby_id, need["trigger"],
    )


# ============================================================
# 规则引擎需求评估（fast 模式，不调 LLM）
# ============================================================

def rule_based_need(state, day: int) -> dict | None:
    """
    纯规则判断宝宝是否发起需求。
    基于压力、年龄、随机因子，不调 LLM。
    """
    from cradle.initiative_needs import NeedUrgency, TRIGGER_URGENCY, URGENCY_TIMEOUT

    ini = state.initiative
    if ini.pending_initiative_id:
        return None

    # 冷却
    if ini.last_initiative_ts > 0 and day - int(ini.last_initiative_ts) < 3:
        return None

    stress = state.stress.stress_level if state.stress else 0
    phase = state.current_phase

    # 概率 = base + stress_boost（压力越高越可能发起需求）
    base_prob = 0.08
    stress_boost = stress * 0.3
    if random.random() > base_prob + stress_boost:
        return None

    # 从场景库按 phase 采样（阶段匹配：每阶段 ≥ 50 条 phase 特定场景，
    # 表达严格符合对应 expression_mode——见 specs/initiative-scene-library/）
    from scenes import pick_scene
    from cradle.initiative_needs import TRIGGER_LABELS

    # 高压力时优先负向 trigger，通过场景库的 trigger 过滤实现
    if stress > 0.4:
        preferred_triggers = ["fear", "pain", "lonely", "gas_colic", "overstimulated"]
        scene = None
        random.shuffle(preferred_triggers)
        for t in preferred_triggers:
            scene = pick_scene(phase=phase, trigger=t)
            if scene is not None:
                break
        if scene is None:
            scene = pick_scene(phase=phase)
    else:
        scene = pick_scene(phase=phase)

    if scene is None:
        return None

    urgency = TRIGGER_URGENCY.get(scene.trigger, NeedUrgency.SOCIAL)
    # behavior_type：phase<=1 纯哭，之后 verbal
    behavior_type = "cry" if phase <= 1 else "verbal"

    return {
        "trigger": scene.trigger,
        "urgency": urgency,
        "timeout_sec": URGENCY_TIMEOUT[urgency],
        "expression": scene.expression,
        "signal": scene.signal,
        "facial": scene.facial,
        "body": scene.body,
        "behavior_type": behavior_type,
        "intent_id": f"rule-{day}-{scene.id}",
        "parent_hint": scene.parent_hint or TRIGGER_LABELS.get(scene.trigger, ""),
        # 透传默认 cause_tags 给 memory.record_moment（自动 phase 标注）
        "cause_tags": list(scene.default_tags),
    }
