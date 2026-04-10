"""
婴儿认知反应 + 保姆叙事系统。

处理事件→通过感官过滤→生成反应。
保姆作为日常照料者，叙述照料过程和结果。
每个阶段的表达形式不同（哭→咿呀→单词→句子）。

[INPUT]: 依赖 cradle/state.py, cradle/phases.py, llm.py 的 LLM 基础设施
[OUTPUT]: process_daily_with_nanny(), process_environment_events(), process_critical_event(), generate_phase_summary()
[POS]: cradle/ 的 LLM 调用层，被 nanny.py 消费
[PROTOCOL]: 变更时更新此头部，然后检查 CLAUDE.md
"""

from __future__ import annotations

import json
import logging
import os

from .state import BabyState, Memory
from .phases import PHASES, EXPRESSION_MODES
from .events import Event

logger = logging.getLogger(__name__)


def _get_llm():
    """获取 LLM 客户端。"""
    from llm import create_client, PROVIDERS, get_model
    provider = os.environ.get("LLM_PROVIDER", "deepseek")
    client = create_client(provider)
    model = get_model(provider)
    return client, model, provider


def _call_and_parse(prompt: str) -> dict | list | None:
    """调用 LLM 并解析 JSON。失败返回 None 而非脏数据。"""
    from llm import call_llm, parse_json
    try:
        client, model, provider = _get_llm()
        raw = call_llm(prompt, client, model, provider)
    except Exception as e:
        logger.error("LLM 调用失败: %s", e)
        return None
    try:
        return parse_json(raw)
    except Exception as e:
        logger.warning("LLM 返回无法解析为 JSON: %s (原始: %.200s)", e, raw)
        return None


# ============================================================
# 亲子对话：父母消息 → 婴儿反应（受 expression_mode 严格约束）
# ============================================================

# LLM 失败时的最小反应
_FALLBACK_REACTIONS = {
    "cry_only": "*Stirs slightly, a soft whimper escapes*",
    "coo_and_gaze": "*Turns head toward the sound, blinks slowly*",
    "babble_and_reach": "*Looks up, hands pause mid-motion, 'ba?'*",
    "gesture_and_point": "*Looks at you, tilts head*",
    "first_words": "*Pauses, looks at you*",
}


def generate_interaction_response(
    state: BabyState,
    parent_message: str,
    recent_interactions: list[dict],
) -> dict:
    """
    生成婴儿对父母消息的反应。

    严格受 expression_mode 约束——cry_only 不能用词，coo_and_gaze 不能形成音节。
    LLM 失败时降级为预设最小反应。
    """
    phase = PHASES[state.current_phase] if state.current_phase < len(PHASES) else PHASES[-1]
    expr = EXPRESSION_MODES.get(state.expression_mode, EXPRESSION_MODES["cry_only"])
    sp = state.identity.sensory_profile

    # 最近 3 条记忆
    recent_memories = state.memories[-3:] if state.memories else []
    memories_text = "\n".join(
        f"- [{m.emotional_valence}] {m.reaction}" for m in recent_memories
    ) or "No memories yet."

    # 最近对话历史
    conv_text = ""
    if recent_interactions:
        lines = []
        for r in recent_interactions[-5:]:
            lines.append(f"Parent: \"{r.get('parent_message', '')}\"")
            lines.append(f"Baby: {r.get('baby_response', '')}")
        conv_text = "\n".join(lines)

    # 约束列表
    constraints_text = "\n".join(f"- {c}" for c in state.identity.constraints) or "None"

    # 缺陷
    defects_text = ", ".join(state.identity.defects) if state.identity.defects else "None"

    # 统计重复主题（帮助 LLM 判断厌烦）
    topic_count = 0
    if recent_interactions:
        last_msg = parent_message.lower()
        for r in recent_interactions:
            prev = r.get("parent_message", "").lower()
            # 简单的重复检测：共享超过一半的词
            words_cur = set(last_msg.split())
            words_prev = set(prev.split())
            if words_cur and words_prev and len(words_cur & words_prev) / max(len(words_cur), 1) > 0.5:
                topic_count += 1

    repetition_note = ""
    if topic_count >= 3:
        repetition_note = f"\n⚠ The parent has repeated a similar topic {topic_count} times recently. The baby may be losing interest, getting bored, or becoming irritated depending on temperament."
    elif topic_count >= 1:
        repetition_note = f"\n(Parent has mentioned similar things {topic_count} time(s) before — the baby may be developing familiarity.)"

    prompt = f"""You are simulating a {state.species} infant's reaction to their parent talking to them.

## The Infant
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

## Recent Memories
{memories_text}

## Recent Conversation
{conv_text or '(first interaction)'}
{repetition_note}

## Parent Says
"{parent_message}"

## Task
Generate the infant's reaction AND any developmental effects. Rules:
1. MUST use the expression format above. Do NOT exceed developmental ability.
2. A cry_only baby CANNOT use words or syllables. A coo_and_gaze baby CANNOT form consonant syllables.
3. Reflect the baby's temperament, sensory profile, and current emotional state.
4. The baby is NOT a passive learner. It has its own arousal threshold, attention span, and preferences.
   - Repeated stimulation of the same topic may cause boredom, irritation, or avoidance (especially high-arousal babies).
   - Novel stimuli aligned with dominant senses are more engaging.
   - Comforting interactions during distress can build trust.
5. Keep baby_response concise (1-3 actions/sentences).

For state_changes, ONLY include fields that genuinely changed from this interaction. Use null for no change.
- new_preference: if the baby showed genuine sustained interest (not just momentary attention)
- new_comfort_source: if the baby was distressed and this interaction provided relief
- fear_reduced: if the baby was exposed to a known fear with parent support and showed reduced anxiety
- new_fear: if the interaction caused genuine distress or overstimulation

Output JSON:
{{
  "baby_response": "the reaction in correct expression format",
  "emotional_tone": "positive/negative/neutral/mixed",
  "state_changes": {{
    "new_preference": "string or null",
    "new_comfort_source": "string or null",
    "fear_reduced": "string or null",
    "new_fear": "string or null"
  }}
}}"""

    result = _call_and_parse(prompt)
    if result and isinstance(result, dict) and "baby_response" in result:
        return {
            "baby_response": result["baby_response"],
            "emotional_tone": result.get("emotional_tone", "neutral"),
            "state_changes": result.get("state_changes", {}),
        }

    # 降级
    fallback = _FALLBACK_REACTIONS.get(state.expression_mode, "*Pauses, looks at you*")
    return {"baby_response": fallback, "emotional_tone": "neutral", "state_changes": {}}


# ============================================================
# 感知过滤：事件 × 感官画像 → 感知权重
# ============================================================

def _perceptual_filter(event: Event, state: BabyState) -> dict:
    """
    感知过滤器。决定婴儿从事件中「感知到」了什么。

    返回 {"perceived_channels": {...}, "intensity_modifier": float, "dominant_channel": str}
    """
    sp = state.identity.sensory_profile
    perceived = {}

    for channel in event.sensory_channels:
        sensitivity = getattr(sp, channel, 0.5)
        perceived[channel] = round(event.intensity * sensitivity, 2)

    arousal_mod = {"high": 1.3, "moderate": 1.0, "low": 0.7}
    modifier = arousal_mod.get(state.identity.arousal_baseline, 1.0)
    total = sum(perceived.values()) * modifier if perceived else 0
    dominant_channel = max(perceived, key=perceived.get) if perceived else ""

    return {
        "perceived_channels": perceived,
        "intensity_modifier": modifier,
        "total_perceived_intensity": round(total, 2),
        "dominant_channel": dominant_channel,
    }


# ============================================================
# 统一叙事：保姆 + 婴儿 + 环境 → 连续时间线
# ============================================================

def narrate_phase_events(
    state: BabyState,
    all_events: list[Event],
) -> list[dict]:
    """
    一次 LLM 调用，生成整个阶段的连续叙事。

    保姆是叙述者和照料者。所有事件（日常+环境）被编织为
    有因果关系的连续场景，而非独立处理。

    返回 scene 列表，每个 scene 是一段连续叙事。
    """
    if not all_events:
        return []

    phase = PHASES[state.current_phase]
    expr_mode = EXPRESSION_MODES[phase.expression_mode]

    # 构建事件素材（含感知数据）
    events_material = ""
    for i, event in enumerate(all_events, 1):
        perception = _perceptual_filter(event, state)
        channels_str = ", ".join(
            f"{ch}: {v}" for ch, v in perception["perceived_channels"].items()
        )
        events_material += (
            f"### 素材 {i}: {event.display_name} ({event.category})\n"
            f"{event.description}\n"
            f"感官通道: {channels_str}\n"
            f"主导通道: {perception['dominant_channel']}\n"
            f"感知总强度: {perception['total_perceived_intensity']}\n"
            f"刺激强度: {event.intensity}\n\n"
        )

    recent_memories = state.memories[-3:]
    memory_text = ""
    if recent_memories:
        memory_text = "\n".join(
            f"- Day {m.age_days}: {m.event} → {m.reaction[:60]}..."
            for m in recent_memories
        )

    prompt = f"""You are a nanny narrating a day in the life of a {state.species} infant. You are experienced, observant, warm but not sentimental. You narrate in first person.

## The Infant
- Name: {state.name or '(还没有名字)'}
- Age: {state.age_days} days ({phase.age_range})
- Phase: {phase.display_name} — {phase.description}
- Expression: {expr_mode['description']}
- Expression format: {expr_mode['format']}

## Innate Identity (CANNOT be violated)
- Dominant sense: {state.identity.sensory_profile.dominant or 'none'}
- Weak sense: {state.identity.sensory_profile.weak or 'none'}
- Arousal baseline: {state.identity.arousal_baseline}
- Temperament: {state.identity.temperament[:150]}

## Behavioral Constraints (MUST follow)
{chr(10).join(f'- {c}' for c in state.identity.constraints)}

## Defects
{', '.join(state.identity.defects) if state.identity.defects else 'None'}

## Current State
- Capabilities: {', '.join(state.capabilities) if state.capabilities else 'Only primitive reflexes'}
- Fears: {', '.join(state.fears) if state.fears else 'None yet'}
- Preferences: {', '.join(state.preferences) if state.preferences else 'None yet'}
- Comfort sources: {', '.join(state.comfort_sources) if state.comfort_sources else 'None yet'}

## Recent Memories
{memory_text or 'No memories yet — this is early life.'}

## Event Materials (raw — YOU decide the order and causal connections)

{events_material}

## Task

Weave these events into a CONTINUOUS NARRATIVE of scenes. Rules:

1. **Causal chain**: Events must flow naturally. A baby doesn't jump from "sleep disruption" to "feeding difficulty" — maybe they woke up BECAUSE they were hungry. The thunderstorm might happen WHILE you're feeding. Find the causal logic.

2. **Each scene** must include:
   - `trigger`: 是什么引发了这个场景（上一个场景的延续，或新的刺激）
   - `nanny_observation`: 保姆（你）观察到了什么，用感官细节
   - `nanny_action`: 你具体做了什么（不是"安抚"，而是"把 ta 侧过来，手掌贴着后背以每秒一次的节奏轻拍"）
   - `baby_reaction`: 婴儿的反应，严格用 {expr_mode['format']} 格式
   - `outcome`: 这轮照料的结果
   - `transition`: 到下一个场景的过渡（最后一个场景留空）

3. **Baby reactions** MUST respect expression mode: {expr_mode['description']}

4. **All narration in English**, baby_reaction also in English.

5. You may split one event material into multiple scenes (e.g., nanny tries method A → fails → tries method B → works).

6. You may merge two event materials into one scene if they naturally overlap.

Output as JSON array:
[
  {{
    "scene": 1,
    "event_names": ["sleep_disruption"],
    "trigger": "凌晨三点，婴儿突然发出一声尖锐的哭喊",
    "nanny_observation": "我赶过去的时候...",
    "nanny_action": "我先检查了尿布...",
    "baby_reaction": "*描写婴儿的反应*",
    "outcome": "结果...",
    "transition": "刚安静下来，窗外突然...",
    "emotional_valence": "negative",
    "intensity": 0.6,
    "trace": "which innate constraint drove the baby's reaction",
    "growth_signal": "developmental significance if any (empty string if none)",
    "new_fear": "if a new fear formed (empty string if not)",
    "new_preference": "if a new preference formed (empty string if not)"
  }},
  ...
]
"""

    result = _call_and_parse(prompt)

    # LLM 失败降级：返回最小化场景，保证流程不断
    if result is None:
        logger.warning("Narration LLM failed, degrading to empty scene list")
        return []

    # 组装结果
    scenes = []
    items = result if isinstance(result, list) else [result]
    for item in items:
        if not isinstance(item, dict):
            continue

        # 构建记忆
        event_names = item.get("event_names", [])
        primary_event = event_names[0] if event_names else "unknown"

        memory = Memory(
            phase=state.current_phase,
            age_days=state.age_days,
            event=primary_event,
            stimulus=item.get("trigger", ""),
            reaction=item.get("baby_reaction", ""),
            trace=item.get("trace", ""),
            emotional_valence=item.get("emotional_valence", "neutral"),
            intensity=item.get("intensity", 0.5),
            growth_signal=item.get("growth_signal", ""),
        )

        scenes.append({
            "scene": item.get("scene", len(scenes) + 1),
            "event_names": event_names,
            "trigger": item.get("trigger", ""),
            "nanny_observation": item.get("nanny_observation", ""),
            "nanny_action": item.get("nanny_action", ""),
            "baby_reaction": item.get("baby_reaction", ""),
            "outcome": item.get("outcome", ""),
            "transition": item.get("transition", ""),
            "emotional_valence": item.get("emotional_valence", "neutral"),
            "intensity": item.get("intensity", 0.5),
            "trace": item.get("trace", ""),
            "growth_signal": item.get("growth_signal", ""),
            "new_fear": item.get("new_fear", ""),
            "new_preference": item.get("new_preference", ""),
            "memory": memory,
        })

    return scenes


# ============================================================
# 处理关键事件（单独调用，需要高质量）
# ============================================================

def process_critical_event(
    state: BabyState,
    event: Event,
    parent_action: str | None = None,
) -> dict:
    """
    处理单个关键事件。一次 LLM 调用。

    如果 parent_action 不为 None，表示父母已介入。
    """
    phase = PHASES[state.current_phase]
    expr_mode = EXPRESSION_MODES[phase.expression_mode]
    perception = _perceptual_filter(event, state)

    # 找到父母选择的描述
    parent_desc = ""
    parent_effect = ""
    if parent_action:
        for choice in event.parent_choices:
            if choice["action"] == parent_action:
                parent_desc = choice["display"]
                parent_effect = choice["effect"]
                break

    recent_memories = state.memories[-5:] if state.memories else []

    prompt = f"""You are simulating a {state.species} infant's reaction to a critical life event.

## Infant Profile
- Name: {state.name or '(unnamed)'}
- Age: {state.age_days} days ({phase.age_range})
- Phase: {phase.display_name} — {phase.description}
- Expression: {expr_mode['description']}
- Expression format: {expr_mode['format']}

## Innate Identity
- Dominant sense: {state.identity.sensory_profile.dominant or 'none'}
- Weak sense: {state.identity.sensory_profile.weak or 'none'}
- Arousal baseline: {state.identity.arousal_baseline}
- Temperament: {state.identity.temperament}
- Constraints: {json.dumps(state.identity.constraints, ensure_ascii=False)}
- Defects: {json.dumps(state.identity.defects, ensure_ascii=False) if state.identity.defects else 'None'}

## Current State
- Capabilities: {', '.join(state.capabilities)}
- Fears: {', '.join(state.fears) if state.fears else 'None'}
- Preferences: {', '.join(state.preferences) if state.preferences else 'None'}
- Attachment forming: {state.attachment_style}

## Recent Memories
{_format_recent_memories(recent_memories)}

## The Event
**{event.display_name}**: {event.description}
Perception: dominant channel = {perception['dominant_channel']}, total intensity = {perception['total_perceived_intensity']}

{"## Parent Response" if parent_action else "## No Parent Present"}
{f"Parent chose to: {parent_desc}" if parent_action else "The infant faces this alone (nanny present but not parent)."}
{f"Expected developmental effect: {parent_effect}" if parent_effect else ""}

## Task

Generate the infant's reaction to this event. Include:
1. The immediate physical/emotional reaction (in the correct expression format)
2. If parent intervened — the infant's response to the parent's action
3. What this event means for the infant's development

Output as JSON:
{{
  "reaction": "the infant's reaction in correct expression format — vivid, specific, sensory-rich",
  "parent_response_reaction": "how the infant reacted to the parent's action (empty if no parent)",
  "emotional_valence": "positive/negative/neutral/mixed",
  "intensity": 0.0-1.0,
  "trace": "which innate constraints shaped this reaction",
  "developmental_impact": "how this event affects future development",
  "new_fear": "new fear formed (empty if none)",
  "new_preference": "new preference formed (empty if none)",
  "new_comfort": "new comfort source discovered (empty if none)",
  "attachment_signal": "how this affected attachment formation (empty if n/a)",
  "milestone_candidate": "if this could be a milestone, which one (empty if not)"
}}
"""

    result = _call_and_parse(prompt)
    if not isinstance(result, dict):
        logger.warning("Critical event LLM failed, degrading to minimal reaction (event=%s)", event.name)
        result = {
            "reaction": f"({event.display_name} occurred. The baby reacted instinctively.)",
            "emotional_valence": "neutral",
            "intensity": 0.5,
        }

    memory = Memory(
        phase=state.current_phase,
        age_days=state.age_days,
        event=event.name,
        stimulus=event.description,
        reaction=result.get("reaction", ""),
        trace=result.get("trace", ""),
        emotional_valence=result.get("emotional_valence", "neutral"),
        intensity=result.get("intensity", 0.5),
        parent_involved=parent_action is not None,
        parent_action=parent_action or "",
        growth_signal=result.get("developmental_impact", ""),
    )

    return {
        "event": event.name,
        "event_display": event.display_name,
        "perception": perception,
        "memory": memory,
        **result,
    }


def _format_recent_memories(memories: list[Memory]) -> str:
    if not memories:
        return "No memories yet — this is early life."
    parts = []
    for m in memories:
        parts.append(f"- Day {m.age_days}: {m.event} → {m.reaction[:80]}... ({m.emotional_valence})")
    return "\n".join(parts)


# ============================================================
# 阶段总结（一次 LLM 调用）
# ============================================================

def generate_phase_summary(state: BabyState) -> dict:
    """
    生成一个阶段的发育总结。

    总结这个阶段的关键事件、能力变化、心理状态变化。
    包含亲子对话历史，影响依恋类型和能力发展评估。
    """
    from .state import load_interactions
    phase = PHASES[state.current_phase]
    phase_memories = [m for m in state.memories if m.phase == state.current_phase]

    # 加载本阶段的亲子对话
    all_interactions = load_interactions(state.baby_id, limit=50)
    phase_interactions = [r for r in all_interactions if r.get("phase") == state.current_phase]
    interaction_count = state.parent_profile.interaction_count

    interactions_text = ""
    if phase_interactions:
        lines = []
        for r in phase_interactions[-10:]:  # 最近 10 条
            lines.append(f'Parent: "{r.get("parent_message", "")}"')
            lines.append(f'Baby ({r.get("expression_mode", "")}): {r.get("baby_response", "")} [{r.get("emotional_tone", "")}]')
        interactions_text = "\n".join(lines)

    prompt = f"""You are writing a developmental summary for a {state.species} infant completing a growth phase.

## Phase: {phase.display_name} ({phase.age_range})
{phase.description}

## Infant: {state.name or '(unnamed)'}, {state.age_days} days old

## Identity Summary
- Dominant sense: {state.identity.sensory_profile.dominant}
- Arousal: {state.identity.arousal_baseline}
- Temperament: {state.identity.temperament[:100]}

## Events This Phase
{_format_phase_events(phase_memories)}

## Parent-Child Interactions This Phase
Total interactions: {len(phase_interactions)} (lifetime: {interaction_count})
{interactions_text or 'No direct interactions this phase.'}

## Current State
- Capabilities unlocked: {', '.join(state.capabilities)}
- Fears: {', '.join(state.fears) if state.fears else 'None'}
- Preferences: {', '.join(state.preferences) if state.preferences else 'None'}
- Attachment: {state.attachment_style}

## Task

Write a developmental summary (150-250 words) in English. Include:
1. What changed in this phase — specific, traceable to events
2. What new capabilities emerged and how they manifested
3. The infant's emotional arc through this phase
4. What patterns are forming (fears, preferences, coping strategies)
5. How parent interactions influenced development (if any) — teaching, bonding, stimulation
6. What to watch for in the next phase

Also update developmental metrics. Parent engagement level should factor into attachment assessment.

Output as JSON:
{{
  "summary": "developmental summary text",
  "capabilities_gained": ["new capabilities from this phase"],
  "personality_notes": ["observations about emerging personality"],
  "attachment_update": "secure/anxious/avoidant/forming — based on parent interactions and responsiveness",
  "next_phase_watch": "what to watch for in the next phase"
}}
"""

    result = _call_and_parse(prompt)
    if not isinstance(result, dict):
        logger.warning("Phase summary LLM failed, degrading to empty summary")
        result = {"summary": "(Phase summary generation failed. Data saved.)"}
    return result


def _format_phase_events(memories: list[Memory]) -> str:
    if not memories:
        return "No significant events recorded."
    parts = []
    for m in memories:
        parent = f" [父母介入: {m.parent_action}]" if m.parent_involved else ""
        parts.append(f"- Day {m.age_days} | {m.event}: {m.reaction[:100]}... "
                     f"({m.emotional_valence}, intensity {m.intensity}){parent}")
    return "\n".join(parts)
