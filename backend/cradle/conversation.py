"""
会话编排：1v1 亲子（DM）与多宝宝群聊（group）同构。

核心语义：
- conv_id 确定性（同组宝宝复用同一 conv_id）
- 家长发消息 → 持久化 → 触发宝宝回应（破冰一次性 or round-robin）
- 宝宝主动发言（heartbeat / baby_need）由后端直接调用 post_baby_message
- 消息即时应用 state_changes（preference/comfort_source/fear），无"end_session"结算

[INPUT]: 依赖 cradle/conversation_store.py（持久化）、cradle/mind.py（DM LLM）、llm.py（群聊 LLM）
[OUTPUT]: make_conv_id, get_or_create_conversation, post_parent_message, post_baby_message,
          rename_conversation, get_conversation, list_messages, list_conversations
[POS]: cradle/ 会话编排层，被 api/conversations.py 消费；已替代旧 cradle/social.py（已删除）
[PROTOCOL]: 变更时更新此头部，然后检查 CLAUDE.md
"""

from __future__ import annotations

import asyncio
import logging
import os
import time as _time
from typing import Optional

from .state import (
    BabyState, load_state, save_state, append_event, get_baby_lock,
)
from .conversation_store import (
    validate_conv_id,
    ensure_conversation,
    load_conversation_meta,
    save_conversation_meta,
    append_conv_message,
    load_conv_messages,
    load_conv_messages_after,
    list_conversations as _store_list_conversations,
    get_conv_lock,
)
from .phases import PHASES, EXPRESSION_MODES

logger = logging.getLogger(__name__)


# ============================================================
# conv_id 规则
# ============================================================

def make_conv_id(participants: list[str], kind: str) -> str:
    """
    生成确定性 conv_id：
    - dm:    participants = [baby_id]           → "dm:{baby_id}"
    - group: participants = [baby_id_1, ...]    → "gp:{sorted_joined_by_underscore}"
    """
    if kind == "dm":
        if len(participants) != 1:
            raise ValueError("DM requires exactly 1 baby participant")
        return f"dm:{participants[0]}"
    if kind == "group":
        uniq = sorted(set(participants))
        if len(uniq) < 2:
            raise ValueError("Group requires at least 2 distinct baby participants")
        return f"gp:{'_'.join(uniq)}"
    raise ValueError(f"Invalid kind: {kind!r}")


# ============================================================
# 读 API（薄封装）
# ============================================================

def get_conversation(conv_id: str) -> Optional[dict]:
    return load_conversation_meta(conv_id)


def list_conversations(baby_id: Optional[str] = None) -> list[dict]:
    return _store_list_conversations(baby_id)


def list_messages(conv_id: str, after_seq: int = 0) -> list[dict]:
    if after_seq > 0:
        return load_conv_messages_after(conv_id, after_seq)
    return load_conv_messages(conv_id)


# ============================================================
# 创建 / 重命名
# ============================================================

def get_or_create_conversation(
    participants: list[str],
    kind: str,
    display_name: Optional[str] = None,
) -> dict:
    """
    幂等：同组宝宝总是复用同一 conv_id。

    display_name:
    - group 必填
    - dm 可省略，自动生成 "和 {baby.name} 的对话"
    """
    uniq = sorted(set(participants))
    for bid in uniq:
        if load_state(bid) is None:
            raise ValueError(f"Baby '{bid}' not found in cradle")

    conv_id = make_conv_id(uniq, kind)

    # 已存在：直接返回（复用）
    existing = load_conversation_meta(conv_id)
    if existing is not None:
        return existing

    # 初次创建：构造 display_name
    if kind == "dm":
        if not display_name:
            st = load_state(uniq[0])
            nm = (st.name if st and st.name else uniq[0])
            display_name = f"和 {nm} 的对话"
    else:  # group
        if not display_name:
            raise ValueError("Group conversation requires display_name")

    return ensure_conversation(conv_id, uniq, kind, display_name)


def rename_conversation(conv_id: str, display_name: str) -> dict:
    validate_conv_id(conv_id)
    if not display_name or not display_name.strip():
        raise ValueError("display_name must be non-empty")
    meta = load_conversation_meta(conv_id)
    if meta is None:
        raise ValueError(f"Conversation '{conv_id}' not found")
    meta["display_name"] = display_name.strip()
    save_conversation_meta(conv_id, meta)
    return meta


# ============================================================
# 写 API：家长发言
# ============================================================

async def post_parent_message(
    conv_id: str,
    content: str,
    action_type: str = "message",
    touch_key: Optional[str] = None,
) -> dict:
    """
    家长发消息 → 持久化 → 触发宝宝回应。

    流程：
    1. （DM 且 touch）校验 touch_key 是否存在且符合当前阶段
    2. 写家长消息（messages.jsonl + 每个 baby events.jsonl 薄索引）
    3. 群聊且首次 → 串行破冰（每宝宝各 1 句）；否则 P1 round-robin
    4. DM：调 mind.generate_interaction_response（支持 touch）
    5. 群聊：调 _call_group_agent（多 agent 共享历史）
    6. DM：触发主动需求响应副作用（signal_need_responded + 压力/依恋/counter++）

    返回 {"seq": parent_seq, "triggered_babies": [...]}。
    """
    meta = load_conversation_meta(conv_id)
    if meta is None:
        raise ValueError(f"Conversation '{conv_id}' not found")

    if meta["kind"] == "dm" and action_type == "touch" and touch_key:
        _validate_dm_touch(meta["participants"][0], touch_key)

    lock = get_conv_lock(conv_id)
    async with lock:
        parent_seq = _write_parent_message(conv_id, meta, content, action_type, touch_key)

        if meta["kind"] == "group" and not meta.get("icebreaker_done", False):
            triggered = await _run_icebreaker(conv_id, meta)
            meta["icebreaker_done"] = True
            save_conversation_meta(conv_id, meta)
        else:
            triggered = await _run_round_robin(
                conv_id, meta, content, action_type, touch_key,
            )

        if meta["kind"] == "dm":
            await _apply_dm_parent_side_effects(meta["participants"][0])

        return {"seq": parent_seq, "triggered_babies": triggered}


def _validate_dm_touch(baby_id: str, touch_key: str) -> None:
    """校验 touch_key 存在且当前阶段允许（与旧 /interact 端点同契约）。"""
    from .touch import TOUCH_ACTIONS
    act = next((a for a in TOUCH_ACTIONS if a.key == touch_key), None)
    if act is None:
        raise ValueError(f"Unknown touch action: {touch_key}")
    st = load_state(baby_id)
    if st is None:
        raise ValueError(f"Baby '{baby_id}' not found in cradle")
    lo, hi = act.phase_range
    if not (lo <= st.current_phase <= hi):
        raise ValueError(
            f"Touch action '{touch_key}' not available at phase {st.current_phase}"
        )


async def _apply_dm_parent_side_effects(baby_id: str) -> None:
    """
    DM 家长发言后的状态副作用（迁移自旧 /interact 端点）：
    - mark_responded：心跳系统标记主动行为已被响应
    - interaction_count++
    - last_interact_ts 更新
    - 若有 pending need：额外 stress 降 0.1 + 依恋向 secure 偏移 + signal_need_responded
    """
    from heartbeat import mark_responded
    from scheduler import signal_need_responded

    lock = get_baby_lock(baby_id)
    async with lock:
        state = load_state(baby_id)
        if state is None:
            return
        now = _time.time()
        state.last_active_ts = now

        mark_responded(state.initiative, state.caregivers, state=state,
                       responder_key="primary_parent",
                       response_text="")
        state.initiative.last_interact_ts = now

        primary = state.caregivers.get("primary_parent")
        if primary:
            primary.interaction_count += 1
        elif state.caregivers:
            next(iter(state.caregivers.values())).interaction_count += 1

        had_pending = bool(state.initiative.pending_initiative_id)
        if had_pending:
            state.stress.stress_level = max(0.0, state.stress.stress_level - 0.1)
            _toward_secure = {
                "forming": "secure", "anxious": "forming", "avoidant": "anxious",
            }
            state.attachment_style = _toward_secure.get(
                state.attachment_style, state.attachment_style,
            )
            state.initiative.consecutive_ignores = 0

        save_state(state)

    if had_pending:
        signal_need_responded(baby_id)


def _write_parent_message(
    conv_id: str, meta: dict,
    content: str, action_type: str, touch_key: Optional[str],
) -> int:
    """同步持久化家长消息 + 各 baby 薄索引。"""
    record = {
        "role": "parent",
        "baby_id": None,
        "name": "Parent",
        "content": content,
        "action_type": action_type,
        "touch_key": touch_key,
        "emotional_tone": None,
        "state_changes": None,
        "subtype": None,
        "urgency": None,
    }
    seq = append_conv_message(conv_id, record)
    for bid in meta["participants"]:
        append_event(bid, {
            "event": "conversation_message",
            "conv_id": conv_id,
            "conv_seq": seq,
            "role": "parent",
            "summary": content[:80],
        })
    return seq


# ============================================================
# 写 API：宝宝主动发言（heartbeat / baby_need 触发）
# ============================================================

async def post_baby_message(
    conv_id: str,
    baby_id: str,
    content: str,
    *,
    subtype: Optional[str] = None,
    urgency: Optional[str] = None,
    emotional_tone: Optional[str] = None,
    state_changes: Optional[dict] = None,
) -> dict:
    """
    宝宝主动发言（后端 scheduler/heartbeat 直接调用）。

    不触发其他宝宝回应（家长介入后才进入 round-robin）。
    """
    meta = load_conversation_meta(conv_id)
    if meta is None:
        raise ValueError(f"Conversation '{conv_id}' not found")
    if baby_id not in meta["participants"]:
        raise ValueError(f"Baby '{baby_id}' is not a participant of {conv_id}")

    st = load_state(baby_id)
    name = (st.name if st and st.name else baby_id)

    record = {
        "role": "baby",
        "baby_id": baby_id,
        "name": name,
        "content": content,
        "action_type": "message",
        "touch_key": None,
        "emotional_tone": emotional_tone,
        "state_changes": state_changes or None,
        "subtype": subtype,
        "urgency": urgency,
    }
    seq = append_conv_message(conv_id, record)
    append_event(baby_id, {
        "event": "conversation_message",
        "conv_id": conv_id,
        "conv_seq": seq,
        "role": "baby",
        "summary": content[:80],
        "subtype": subtype,
    })

    # 记忆：宝宝主动发言（用户强调的"主动行为进记忆"核心场景）
    # subtype="need" 表示主动需求；否则是一般自发表达
    try:
        from memory import record_moment
        if st is not None:
            _trigger = "baby_need" if subtype == "need" else "baby_speak"
            _intensity = 0.7 if urgency == "high" else (0.6 if urgency == "medium" else 0.5)
            record_moment(
                st, baby_id,
                actor="self",
                target="caregiver:primary_parent",  # 对话总是有 caregiver 作为受众
                trigger=_trigger,
                action=content,
                response="",
                outcome="pending",   # 等待家长响应，companion_seq 由 mark_responded 链接
                valence=emotional_tone or "neutral",
                intensity=_intensity,
                cause_tags=[f"phase:{st.current_phase}"],
                effect_tags=[],
            )
            save_state(st)
    except Exception as e:
        logger.warning("record_moment for baby speak failed: %s", e)

    return {"seq": seq}


# ============================================================
# 破冰 & round-robin
# ============================================================

async def _run_icebreaker(conv_id: str, meta: dict) -> list[str]:
    """群聊首次家长发言后，每宝宝串行说一句（感知彼此的回应）。"""
    _write_system_marker(conv_id, "icebreaker_start")
    triggered: list[str] = []
    for bid in meta["participants"]:
        st = load_state(bid)
        if st is None:
            continue
        result = await asyncio.to_thread(_call_group_agent, conv_id, st, meta)
        await _persist_baby_response(conv_id, st, result)
        triggered.append(bid)
    _write_system_marker(conv_id, "icebreaker_done")
    return triggered


async def _run_round_robin(
    conv_id: str, meta: dict,
    parent_message: str, action_type: str, touch_key: Optional[str],
) -> list[str]:
    """家长发言后，每宝宝串行响应一次（DM 只有 1 个宝宝）。"""
    triggered: list[str] = []
    for bid in meta["participants"]:
        st = load_state(bid)
        if st is None:
            continue
        if meta["kind"] == "dm":
            result = await asyncio.to_thread(
                _call_dm_agent, st, parent_message, action_type, touch_key,
            )
        else:
            result = await asyncio.to_thread(_call_group_agent, conv_id, st, meta)
        await _persist_baby_response(conv_id, st, result)
        triggered.append(bid)
    return triggered


def _write_system_marker(conv_id: str, kind: str) -> None:
    """写入系统标记消息（icebreaker_start / icebreaker_done）。"""
    append_conv_message(conv_id, {
        "role": "system",
        "baby_id": None,
        "name": "",
        "content": "",
        "action_type": kind,
        "touch_key": None,
        "emotional_tone": None,
        "state_changes": None,
        "subtype": kind,
        "urgency": None,
    })


# ============================================================
# LLM 调用：DM / Group
# ============================================================

def _call_dm_agent(
    state: BabyState, parent_message: str,
    action_type: str, touch_key: Optional[str],
) -> dict:
    """DM 场景：复用 mind.generate_interaction_response（带 touch 支持）。"""
    from .mind import generate_interaction_response
    from .touch import TOUCH_ACTIONS

    touch_desc = None
    if action_type == "touch" and touch_key:
        act = next((a for a in TOUCH_ACTIONS if a.key == touch_key), None)
        if act is not None:
            touch_desc = act.description

    # 上下文：近 5 条会话历史（按 interact API 原约定）
    recent = _recent_interactions_from_conv(
        make_conv_id([state.baby_id], "dm"), state.baby_id, limit=5,
    )

    return generate_interaction_response(
        state, parent_message, recent,
        action_type=action_type, touch_description=touch_desc,
    )


def _recent_interactions_from_conv(conv_id: str, baby_id: str, limit: int) -> list[dict]:
    """
    从 messages.jsonl 提取近 N 条 (parent, baby) 对话对，供 mind 层注入上下文。

    返回 [{parent_message, baby_response}, ...]（最近在前），与旧 interactions.jsonl 同构。
    """
    msgs = load_conv_messages(conv_id)
    pairs: list[dict] = []
    last_parent: Optional[str] = None
    for m in msgs:
        atype = m.get("action_type", "message")
        if atype in ("icebreaker_start", "icebreaker_done"):
            continue
        if m.get("role") == "parent":
            last_parent = m.get("content", "")
        elif m.get("role") == "baby" and m.get("baby_id") == baby_id:
            if last_parent is not None:
                pairs.append({
                    "parent_message": last_parent,
                    "baby_response": m.get("content", ""),
                })
                last_parent = None
    return pairs[-limit:]


def _call_group_agent(conv_id: str, state: BabyState, meta: dict) -> dict:
    """群聊多 agent：共享历史，各自视角 chat messages。"""
    from llm import create_client, call_llm_chat, parse_json, get_model

    others = _collect_others(state.baby_id, meta["participants"])
    system = _build_group_system_prompt(state, others, meta.get("display_name", ""))
    chat_messages = _build_chat_messages(conv_id, state.baby_id)

    provider = os.environ.get("LLM_PROVIDER", "deepseek")
    client = create_client(provider)
    model = get_model(provider)

    try:
        raw = call_llm_chat(
            system, chat_messages, client, model, provider,
            metadata={"baby_id": state.baby_id, "callsite": "conversation_group"},
        )
        result = parse_json(raw)
        if isinstance(result, dict) and "baby_response" in result:
            return {
                "baby_response": result["baby_response"],
                "emotional_tone": result.get("emotional_tone", "neutral"),
                "state_changes": result.get("state_changes", {}),
            }
    except Exception as e:
        logger.error("Group agent call failed for %s: %s", state.baby_id, e)

    return _group_fallback(state)


def _collect_others(me: str, participants: list[str]) -> list[dict]:
    others = []
    for bid in participants:
        if bid == me:
            continue
        other = load_state(bid)
        if other is None:
            continue
        others.append({
            "name": other.name or other.baby_id,
            "age_days": other.age_days,
            "temperament_summary": (
                other.identity.temperament[:80]
                if other.identity.temperament else "unknown"
            ),
            "expression_mode": other.expression_mode,
        })
    return others


def _build_chat_messages(conv_id: str, current_baby_id: str) -> list[dict]:
    """共享历史 → 当前宝宝视角的 chat messages。"""
    msgs = []
    for m in load_conv_messages(conv_id):
        atype = m.get("action_type", "message")
        if atype in ("icebreaker_start", "icebreaker_done"):
            continue
        role = m.get("role")
        if role == "parent":
            msgs.append({"role": "user", "content": f"[Parent]: {m.get('content', '')}"})
        elif role == "baby" and m.get("baby_id") == current_baby_id:
            msgs.append({"role": "assistant", "content": m.get("content", "")})
        elif role == "baby":
            nm = m.get("name", "peer")
            msgs.append({"role": "user", "content": f"[{nm}]: {m.get('content', '')}"})
    msgs.append({"role": "user", "content": "(Your turn to respond. What do you do/say?)"})
    return msgs


def _group_fallback(state: BabyState) -> dict:
    fallbacks = {
        "cry_only": "*Stirs, whimpers softly*",
        "coo_and_gaze": "*Looks around, blinks*",
        "babble_and_reach": "*Looks up, 'ba?'*",
        "gesture_and_point": "*Tilts head, looks at the others*",
        "first_words": "*Pauses, looks*",
    }
    return {
        "baby_response": fallbacks.get(state.expression_mode, "*Looks at the others quietly*"),
        "emotional_tone": "neutral",
        "state_changes": {},
    }


def _build_group_system_prompt(
    state: BabyState, others: list[dict], display_name: str,
) -> str:
    phase = PHASES[state.current_phase] if state.current_phase < len(PHASES) else PHASES[-1]
    expr = EXPRESSION_MODES.get(state.expression_mode, EXPRESSION_MODES["cry_only"])
    sp = state.identity.sensory_profile

    constraints_text = "\n".join(f"- {c}" for c in state.identity.constraints) or "None"
    defects_text = ", ".join(state.identity.defects) if state.identity.defects else "None"
    others_text = "\n".join(
        f"- {o['name']}: {o['age_days']} days, {o['temperament_summary']}, {o['expression_mode']}"
        for o in others
    ) or "No other children."

    return f"""You are simulating a {state.species} child in a group chat "{display_name}" with peers and a parent.

## Your Identity
- Name: {state.name or '(unnamed)'}
- Age: {state.age_days} days ({phase.age_range(state.lang)})
- Phase: {phase.display_name} — {phase.description}

## Expression Mode (STRICTLY ENFORCED)
- Description: {expr['description']}
- Output format: {expr['format']}
- Example: {expr['example']}

## Innate Identity (CANNOT be violated)
- Dominant sense: {sp.dominant or 'none determined'}
- Weak sense: {sp.weak or 'none'}
- Arousal baseline: {state.identity.arousal_baseline}
- Temperament: {state.identity.temperament[:200] if state.identity.temperament else 'unknown'}

## Behavioral Constraints (MUST follow)
{constraints_text}

## Defects: {defects_text}

## Current State
- Capabilities: {', '.join(state.capabilities) or 'None yet'}
- Fears: {', '.join(state.fears) or 'None'}
- Preferences: {', '.join(state.preferences) or 'None'}

## Other Children Present
{others_text}

## Rules
1. MUST use your expression format. Do NOT exceed developmental ability.
2. Reflect your temperament, sensory profile, and arousal baseline.
3. You are interacting with PEERS (and possibly a parent). Social dynamics apply.
4. Keep response concise (1-3 sentences).
5. For state_changes, ONLY include genuinely triggered changes. Use null for no change.

Output JSON:
{{"baby_response": "...", "emotional_tone": "positive/negative/neutral/mixed", "state_changes": {{"new_preference": "string or null", "new_comfort_source": "string or null", "fear_reduced": "string or null", "new_fear": "string or null"}}}}"""


# ============================================================
# 宝宝回应持久化 + state_changes 即时结算
# ============================================================

async def _persist_baby_response(
    conv_id: str, state: BabyState, result: dict,
) -> None:
    """
    持久化宝宝回应：
    - 应用 state_changes（preference / comfort_source / fear）
    - 写 messages.jsonl
    - 写 baby events.jsonl（薄索引）
    - 更新 last_active_ts
    """
    changes = result.get("state_changes") or {}
    applied: dict = {}
    baby_name = state.name or state.baby_id

    lock = get_baby_lock(state.baby_id)
    async with lock:
        fresh = load_state(state.baby_id)
        if fresh is None:
            return
        applied = _apply_state_changes(fresh, changes)
        fresh.last_active_ts = _time.time()
        save_state(fresh)
        if fresh.name:
            baby_name = fresh.name

    record = {
        "role": "baby",
        "baby_id": state.baby_id,
        "name": baby_name,
        "content": result.get("baby_response", ""),
        "action_type": "message",
        "touch_key": None,
        "emotional_tone": result.get("emotional_tone", "neutral"),
        "state_changes": applied or None,
        "subtype": None,
        "urgency": None,
    }
    seq = append_conv_message(conv_id, record)
    append_event(state.baby_id, {
        "event": "conversation_message",
        "conv_id": conv_id,
        "conv_seq": seq,
        "role": "baby",
        "summary": record["content"][:80],
    })

    # 记忆：baby 对家长消息的回应（主动参与 interaction）
    # 这是用户强调的"主动行为进记忆"的核心场景之一
    try:
        from memory import record_moment
        _baby_response = result.get("baby_response", "") or ""
        if _baby_response and fresh is not None:
            record_moment(
                fresh, state.baby_id,
                actor="self",
                target="caregiver:primary_parent",   # DM 场景默认 primary_parent
                trigger="conversation_reply",
                action=_baby_response,
                response="",
                outcome="succeeded",
                valence=result.get("emotional_tone", "neutral"),
                intensity=0.55,
                cause_tags=[f"phase:{fresh.current_phase}"],
                effect_tags=["memory:interaction"],
            )
            save_state(fresh)
    except Exception as e:
        logger.warning("record_moment for baby conversation reply failed: %s", e)


def _apply_state_changes(fresh: BabyState, changes: dict) -> dict:
    """原地应用 LLM 产出的 state_changes，返回实际生效的部分。"""
    applied: dict = {}
    pref = changes.get("new_preference")
    if pref and pref not in fresh.preferences:
        fresh.preferences.append(pref)
        applied["new_preference"] = pref
    src = changes.get("new_comfort_source")
    if src and src not in fresh.comfort_sources:
        fresh.comfort_sources.append(src)
        applied["new_comfort_source"] = src
    reduced = changes.get("fear_reduced")
    if reduced and reduced in fresh.fears:
        fresh.fears.remove(reduced)
        applied["fear_reduced"] = reduced
    new_fear = changes.get("new_fear")
    if new_fear and new_fear not in fresh.fears:
        fresh.fears.append(new_fear)
        applied["new_fear"] = new_fear
    return applied
