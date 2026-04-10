"""
多婴儿社交会话：多 Agent 多轮对话。

每个婴儿 = 1 个独立 agent（自己的 system prompt + identity constraints）。
社交会话维护共享对话历史，每轮 1 个 agent 发言 = 1 次 LLM 调用。
家长可随时插入消息。state_changes 延迟到会话结束时统一结算。

[INPUT]: 依赖 cradle/state.py, cradle/phases.py, llm.py
[OUTPUT]: SocialSession, start_session, advance_turn, parent_message, end_session, get_history
[POS]: cradle/ 的社交子系统，被 api/cradle.py 消费
[PROTOCOL]: 变更时更新此头部，然后检查 CLAUDE.md
"""

from __future__ import annotations

import logging
import time as _time
import uuid
from dataclasses import dataclass, field

from .state import BabyState, save_state, append_interaction, append_event
from .phases import PHASES, EXPRESSION_MODES

logger = logging.getLogger(__name__)

# 会话超时（秒）
SESSION_TIMEOUT = 30 * 60  # 30 分钟

# ============================================================
# 数据模型
# ============================================================

@dataclass
class SocialMessage:
    role: str               # "baby" or "parent"
    baby_id: str | None     # None for parent
    name: str
    content: str
    emotional_tone: str     # positive/negative/neutral/mixed, empty for parent
    state_changes: dict     # raw state_changes from LLM, empty for parent
    timestamp: float = 0.0

    def to_dict(self) -> dict:
        return {
            "role": self.role, "baby_id": self.baby_id, "name": self.name,
            "content": self.content, "emotional_tone": self.emotional_tone,
            "state_changes": self.state_changes, "timestamp": self.timestamp,
        }


@dataclass
class SocialSession:
    session_id: str
    participant_ids: list[str]
    participant_states: dict[str, BabyState]
    context: str
    history: list[SocialMessage] = field(default_factory=list)
    pending_changes: dict[str, list[dict]] = field(default_factory=dict)
    turn_index: int = 0
    created_at: float = 0.0
    last_activity: float = 0.0

    # 每个婴儿的 system prompt（session start 时构建，缓存）
    _system_prompts: dict[str, str] = field(default_factory=dict)


# ============================================================
# 会话存储（内存级）
# ============================================================

_social_sessions: dict[str, SocialSession] = {}
_baby_session_map: dict[str, str] = {}  # baby_id -> session_id (1:1)


def is_in_session(baby_id: str) -> str | None:
    """检查婴儿是否在社交会话中，返回 session_id 或 None。"""
    return _baby_session_map.get(baby_id)


# ============================================================
# 构建 system prompt
# ============================================================

def _build_system_prompt(state: BabyState, others: list[dict], context: str) -> str:
    """为单个婴儿构建社交 system prompt。"""
    phase = PHASES[state.current_phase] if state.current_phase < len(PHASES) else PHASES[-1]
    expr = EXPRESSION_MODES.get(state.expression_mode, EXPRESSION_MODES["cry_only"])
    sp = state.identity.sensory_profile

    constraints_text = "\n".join(f"- {c}" for c in state.identity.constraints) or "None"
    defects_text = ", ".join(state.identity.defects) if state.identity.defects else "None"

    others_text = "\n".join(
        f"- {o['name']}: {o['age_days']} days, {o['temperament_summary']}, {o['expression_mode']}"
        for o in others
    ) or "No other children."

    return f"""You are simulating a {state.species} child in a social interaction with other children.

## Your Identity
- Name: {state.name or '(unnamed)'}
- Age: {state.age_days} days ({phase.age_range})
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
- Comfort sources: {', '.join(state.comfort_sources) or 'None'}

## Other Children Present
{others_text}

## Scene
{context or 'free play with other children'}

## Rules
1. MUST use your expression format. Do NOT exceed developmental ability.
2. Reflect your temperament, sensory profile, and arousal baseline.
3. You are interacting with PEERS, not a parent. Social dynamics apply:
   - You may imitate, compete, share, conflict, or ignore others.
   - Your arousal baseline affects how readily you engage.
   - Your fears and preferences influence what topics/activities interest you.
4. Keep response concise (1-3 sentences in your expression format).
5. For state_changes, ONLY include genuinely triggered changes. Use null for no change.

Output JSON:
{{"baby_response": "your response in correct expression format", "emotional_tone": "positive/negative/neutral/mixed", "state_changes": {{"new_preference": "string or null", "new_comfort_source": "string or null", "fear_reduced": "string or null", "new_fear": "string or null"}}}}"""


def _build_chat_messages(session: SocialSession, current_baby_id: str) -> list[dict]:
    """将共享历史转换为 LLM chat messages（当前婴儿视角）。"""
    messages = []
    for msg in session.history:
        if msg.role == "parent":
            messages.append({"role": "user", "content": f"[Parent]: {msg.content}"})
        elif msg.baby_id == current_baby_id:
            messages.append({"role": "assistant", "content": msg.content})
        else:
            messages.append({"role": "user", "content": f"[{msg.name}]: {msg.content}"})
    # 提示当前婴儿回应
    messages.append({"role": "user", "content": "(Your turn to respond. What do you do/say?)"})
    return messages


# ============================================================
# LLM agent 调用
# ============================================================

def _call_agent(session: SocialSession, baby_id: str) -> dict:
    """调用单个婴儿 agent，返回 {baby_response, emotional_tone, state_changes}。"""
    from llm import create_client, call_llm_chat, parse_json, get_model
    import os

    system = session._system_prompts.get(baby_id, "")
    messages = _build_chat_messages(session, baby_id)

    provider = os.environ.get("LLM_PROVIDER", "deepseek")
    client = create_client(provider)
    model = get_model(provider)

    try:
        raw = call_llm_chat(system, messages, client, model, provider)
        result = parse_json(raw)
        if isinstance(result, dict) and "baby_response" in result:
            return {
                "baby_response": result["baby_response"],
                "emotional_tone": result.get("emotional_tone", "neutral"),
                "state_changes": result.get("state_changes", {}),
            }
    except Exception as e:
        logger.error("Social agent call failed for %s: %s", baby_id, e)

    # 降级
    expr_mode = session.participant_states[baby_id].expression_mode
    fallbacks = {
        "cry_only": "*Stirs, whimpers softly*",
        "coo_and_gaze": "*Looks around, blinks*",
        "babble_and_reach": "*Looks up, 'ba?'*",
        "gesture_and_point": "*Tilts head, looks at the others*",
        "first_words": "*Pauses, looks*",
    }
    return {
        "baby_response": fallbacks.get(expr_mode, "*Looks at the other children quietly*"),
        "emotional_tone": "neutral",
        "state_changes": {},
    }


# ============================================================
# 会话生命周期
# ============================================================

def start_session(states: list[BabyState], context: str = "") -> SocialSession:
    """创建社交会话。states 已经过 phase 验证。"""
    session_id = str(uuid.uuid4())[:8]
    now = _time.time()

    participant_states = {s.baby_id: s for s in states}
    participant_ids = [s.baby_id for s in states]

    session = SocialSession(
        session_id=session_id,
        participant_ids=participant_ids,
        participant_states=participant_states,
        context=context,
        pending_changes={bid: [] for bid in participant_ids},
        created_at=now,
        last_activity=now,
    )

    # 构建并缓存每个婴儿的 system prompt
    for state in states:
        others = []
        for other in states:
            if other.baby_id == state.baby_id:
                continue
            others.append({
                "name": other.name or other.baby_id,
                "age_days": other.age_days,
                "temperament_summary": other.identity.temperament[:80] if other.identity.temperament else "unknown",
                "expression_mode": other.expression_mode,
            })
        session._system_prompts[state.baby_id] = _build_system_prompt(state, others, context)

    # 注册
    _social_sessions[session_id] = session
    for bid in participant_ids:
        _baby_session_map[bid] = session_id

    return session


def _check_expired(session: SocialSession) -> bool:
    """检查会话是否超时。"""
    return (_time.time() - session.last_activity) > SESSION_TIMEOUT


def advance_turn(session_id: str) -> dict:
    """推进一轮：选择下一个发言者，调用 agent，返回结果。"""
    session = _social_sessions.get(session_id)
    if session is None:
        raise ValueError(f"Session '{session_id}' not found")
    if _check_expired(session):
        _cleanup_session(session_id)
        raise ValueError(f"Session '{session_id}' expired")

    # 选择发言者（round-robin）
    baby_id = session.participant_ids[session.turn_index % len(session.participant_ids)]
    state = session.participant_states[baby_id]

    # 调用 agent
    result = _call_agent(session, baby_id)

    # 记录到共享历史
    msg = SocialMessage(
        role="baby", baby_id=baby_id, name=state.name or baby_id,
        content=result["baby_response"],
        emotional_tone=result["emotional_tone"],
        state_changes=result.get("state_changes", {}),
        timestamp=_time.time(),
    )
    session.history.append(msg)

    # 累积 state_changes
    if result.get("state_changes"):
        session.pending_changes[baby_id].append(result["state_changes"])

    session.turn_index += 1
    session.last_activity = _time.time()

    return {
        "baby_id": baby_id,
        "name": state.name or baby_id,
        "baby_response": result["baby_response"],
        "emotional_tone": result["emotional_tone"],
        "expression_mode": state.expression_mode,
        "state_changes": result.get("state_changes", {}),
        "turn_number": len(session.history),
    }


def add_parent_message(session_id: str, message: str) -> dict:
    """家长发言 + 自动触发下一个婴儿回应。"""
    session = _social_sessions.get(session_id)
    if session is None:
        raise ValueError(f"Session '{session_id}' not found")
    if _check_expired(session):
        _cleanup_session(session_id)
        raise ValueError(f"Session '{session_id}' expired")

    # 家长消息追加到历史
    parent_msg = SocialMessage(
        role="parent", baby_id=None, name="Parent",
        content=message, emotional_tone="", state_changes={},
        timestamp=_time.time(),
    )
    session.history.append(parent_msg)
    session.last_activity = _time.time()

    # 选择回应者：如果消息提到某个婴儿名字，优先选它；否则 round-robin
    responder_id = None
    msg_lower = message.lower()
    for bid, state in session.participant_states.items():
        if state.name and state.name.lower() in msg_lower:
            responder_id = bid
            break
    if responder_id is None:
        responder_id = session.participant_ids[session.turn_index % len(session.participant_ids)]

    # 临时调整 turn_index 让选定的婴儿回应
    old_idx = session.turn_index
    target_idx = session.participant_ids.index(responder_id)
    session.turn_index = target_idx

    response = advance_turn(session_id)

    return {
        "parent_message": message,
        "response": response,
    }


def get_session_history(session_id: str) -> dict:
    """获取会话历史。"""
    session = _social_sessions.get(session_id)
    if session is None:
        raise ValueError(f"Session '{session_id}' not found")

    return {
        "session_id": session_id,
        "participants": [
            {"baby_id": bid, "name": session.participant_states[bid].name or bid}
            for bid in session.participant_ids
        ],
        "context": session.context,
        "history": [m.to_dict() for m in session.history],
    }


def end_session(session_id: str) -> dict:
    """结束会话：结算 state_changes，持久化，清理。"""
    session = _social_sessions.get(session_id)
    if session is None:
        raise ValueError(f"Session '{session_id}' not found")

    per_baby_results = []

    for baby_id in session.participant_ids:
        state = session.participant_states[baby_id]
        changes_list = session.pending_changes.get(baby_id, [])

        # 聚合所有轮次的 state_changes
        applied = {"new_preferences": [], "new_comfort_sources": [], "fears_reduced": [], "new_fears": []}
        for ch in changes_list:
            if ch.get("new_preference"):
                applied["new_preferences"].append(ch["new_preference"])
            if ch.get("new_comfort_source"):
                applied["new_comfort_sources"].append(ch["new_comfort_source"])
            if ch.get("fear_reduced"):
                applied["fears_reduced"].append(ch["fear_reduced"])
            if ch.get("new_fear"):
                applied["new_fears"].append(ch["new_fear"])

        # 应用到状态（去重）
        for pref in applied["new_preferences"]:
            if pref not in state.preferences:
                state.preferences.append(pref)
        for src in applied["new_comfort_sources"]:
            if src not in state.comfort_sources:
                state.comfort_sources.append(src)
        for fear in applied["fears_reduced"]:
            if fear in state.fears:
                state.fears.remove(fear)
        for fear in applied["new_fears"]:
            if fear not in state.fears:
                state.fears.append(fear)

        # 更新交互计数
        my_turns = sum(1 for m in session.history if m.baby_id == baby_id)
        state.parent_profile.interaction_count += my_turns

        # 保存状态
        save_state(state)

        # 持久化记录
        my_responses = [m.content for m in session.history if m.baby_id == baby_id]
        record = {
            "type": "social_session",
            "session_id": session_id,
            "participants": session.participant_ids,
            "context": session.context,
            "total_turns": len(session.history),
            "my_turns": my_turns,
            "my_responses": my_responses,
            "applied_changes": applied,
            "phase": state.current_phase,
            "age_days": state.age_days,
        }
        append_interaction(baby_id, record)
        append_event(baby_id, {"event": "social_session", "session_id": session_id,
                               "participants": session.participant_ids, "total_turns": len(session.history)})

        per_baby_results.append({
            "baby_id": baby_id,
            "name": state.name or baby_id,
            "applied_changes": applied,
        })

    total_turns = len(session.history)
    _cleanup_session(session_id)

    return {
        "total_turns": total_turns,
        "per_baby_changes": per_baby_results,
    }


def _cleanup_session(session_id: str):
    """清理会话。"""
    session = _social_sessions.pop(session_id, None)
    if session:
        for bid in session.participant_ids:
            _baby_session_map.pop(bid, None)
