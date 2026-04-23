"""
主动需求处理 + 保姆降级 + 规则引擎评估。

[INPUT]: 依赖 scheduler/events.py（信号）、initiative_needs、cradle/
[OUTPUT]: handle_need(), nanny_fallback(), rule_based_need(), force_emit_need()
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
        _evt = {
            "event": "need_responded",
            "need_id": need_id,
            "responder": "parent",
            "trigger": need["trigger"],
        }
        try:
            from scheduler import graph_hooks
            from cradle import graph_emit as ge
            from cradle import graph_story as gs
            phase_idx = getattr(state, "current_phase", 0)
            trig = need["trigger"]
            event_raw = f"event:need:{phase_idx}:{trig}"
            nodes = [
                ge.node_need_type(trig, **gs.hydrate_need(trig)),
                ge.node_event("need", phase_idx, seq=trig, result="resolved"),
            ]
            edges = [
                ge.edge_triggered_by(event_raw, trig, phase_idx,
                                     resolution="parent_response"),
                ge.edge_experiences(event_raw, phase_idx,
                                    description=f"need {trig} resolved"),
            ]
            graph_hooks.apply_and_attach(
                baby_id, ge.delta_add(nodes=nodes, edges=edges), _evt,
            )
        except Exception:
            logger.exception("need_responded graph_delta failed")
        append_event(baby_id, _evt)
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

    _evt = {
        "event": "need_responded",
        "need_id": need_id,
        "responder": template["role"],
        "trigger": need["trigger"],
        "nanny_text": template["text"],
        "stress_delta": -0.05,
        "attachment_change": attachment_change,
    }
    try:
        from scheduler import graph_hooks
        from cradle import graph_emit as ge
        from cradle import graph_story as gs
        phase_idx = getattr(state, "current_phase", 0)
        trig = need["trigger"]
        event_raw = f"event:need:{phase_idx}:{trig}"
        nodes = [
            ge.node_need_type(trig, **gs.hydrate_need(trig)),
            ge.node_event("need", phase_idx, seq=trig, result="fallback"),
        ]
        edges = [
            ge.edge_triggered_by(event_raw, trig, phase_idx,
                                 resolution="nanny_fallback"),
            ge.edge_experiences(event_raw, phase_idx,
                                description=f"need {trig} fallback"),
        ]
        graph_hooks.apply_and_attach(
            baby_id, ge.delta_add(nodes=nodes, edges=edges), _evt,
        )
    except Exception:
        logger.exception("nanny_fallback graph_delta failed")
    append_event(baby_id, _evt)

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
    zh = scene.localized("zh")
    en = scene.localized("en")
    # 主字段按 BabyState.lang 取——phase_04+ 场景主字段 expression/parent_hint
    # 混有中文对白，英文 baby 若直接用主字段会在 DM 聊天气泡里泄漏中文。
    loc = scene.localized(state.lang)

    return {
        "trigger": scene.trigger,
        "urgency": urgency,
        "timeout_sec": URGENCY_TIMEOUT[urgency],
        "expression": loc["expression"],
        "signal": loc["signal"],
        "facial": loc["facial"],
        "body": loc["body"],
        "behavior_type": behavior_type,
        "intent_id": f"rule-{day}-{scene.id}",
        "parent_hint": loc["parent_hint"] or TRIGGER_LABELS.get(scene.trigger, ""),
        # 透传默认 cause_tags 给 memory.record_moment（自动 phase 标注）
        "cause_tags": list(scene.default_tags),
        # 双语副字段：前端按语种取展示（不改主字段，保持向后兼容）
        "expression_zh": zh["expression"],
        "signal_zh": zh["signal"],
        "facial_zh": zh["facial"],
        "body_zh": zh["body"],
        "parent_hint_zh": zh["parent_hint"],
        "expression_en": en["expression"],
        "signal_en": en["signal"],
        "facial_en": en["facial"],
        "body_en": en["body"],
        "parent_hint_en": en["parent_hint"] or TRIGGER_LABELS.get(scene.trigger, ""),
    }


# ============================================================
# 强制兜底：每阶段 >= 1 次主动需求
# ============================================================

def force_emit_need(state, day: int) -> dict | None:
    """
    阶段收尾兜底：绕过 rule_based_need 的冷却/概率门，直接按 phase 挑场景。

    约束：
    - 若 pending_initiative_id 已占用 → 返回 None（视为"至少 1 次"已满足）
    - 场景库缺失阶段 → 用通用 trigger 兜底（hunger/curious），保证永不返回 None
    - cause_tags 带 forced:min_one_per_phase，前端/日志可区分自然 vs 兜底需求
    """
    from cradle.initiative_needs import (
        NeedUrgency, TRIGGER_URGENCY, URGENCY_TIMEOUT, TRIGGER_LABELS,
    )
    from scenes import pick_scene

    ini = state.initiative
    if ini.pending_initiative_id:
        return None

    phase = state.current_phase
    scene = pick_scene(phase=phase)
    behavior_type = "cry" if phase <= 1 else "verbal"

    if scene is None:
        trigger = "hunger" if phase <= 2 else "curious"
        urgency = TRIGGER_URGENCY.get(trigger, NeedUrgency.SOCIAL)
        return {
            "trigger": trigger,
            "urgency": urgency,
            "timeout_sec": URGENCY_TIMEOUT[urgency],
            "expression": "",
            "signal": "",
            "facial": "",
            "body": "",
            "behavior_type": behavior_type,
            "intent_id": f"force-{day}-{trigger}",
            "parent_hint": TRIGGER_LABELS.get(trigger, ""),
            "cause_tags": [f"phase:{phase}", "forced:min_one_per_phase"],
        }

    urgency = TRIGGER_URGENCY.get(scene.trigger, NeedUrgency.SOCIAL)
    zh = scene.localized("zh")
    en = scene.localized("en")
    # 主字段按 BabyState.lang 取（与 rule_based_need 同；避免英文 baby 的 DM
    # 聊天气泡里泄漏中文 phase_04+ 对白）。
    loc = scene.localized(state.lang)
    return {
        "trigger": scene.trigger,
        "urgency": urgency,
        "timeout_sec": URGENCY_TIMEOUT[urgency],
        "expression": loc["expression"],
        "signal": loc["signal"],
        "facial": loc["facial"],
        "body": loc["body"],
        "behavior_type": behavior_type,
        "intent_id": f"force-{day}-{scene.id}",
        "parent_hint": loc["parent_hint"] or TRIGGER_LABELS.get(scene.trigger, ""),
        "cause_tags": list(scene.default_tags) + ["forced:min_one_per_phase"],
        # 双语副字段（同 rule_based_need）
        "expression_zh": zh["expression"],
        "signal_zh": zh["signal"],
        "facial_zh": zh["facial"],
        "body_zh": zh["body"],
        "parent_hint_zh": zh["parent_hint"],
        "expression_en": en["expression"],
        "signal_en": en["signal"],
        "facial_en": en["facial"],
        "body_en": en["body"],
        "parent_hint_en": en["parent_hint"] or TRIGGER_LABELS.get(scene.trigger, ""),
    }
