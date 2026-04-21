"""
婴儿认知反应 + 保姆叙事系统。

处理事件→通过感官过滤→生成反应。
保姆作为日常照料者，叙述照料过程和结果。
每个阶段的表达形式不同（哭→咿呀→单词→句子）。

[INPUT]: 依赖 cradle/state.py, cradle/phases.py, cradle/causality.py, llm.py 的 LLM 基础设施
[OUTPUT]: generate_interaction_response(action_type/touch_description), generate_heartbeat_evaluation(), generate_ignored_reaction(), process_daily_with_nanny(), process_environment_events(), process_critical_event(), generate_phase_summary()
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
from .causality import generate_cause_tags, generate_effect_tags
from memory import build_memory_prompt_block, is_v2_enabled, recall

logger = logging.getLogger(__name__)


# ============================================================
# 表达模式后验证：校验 LLM 输出是否符合当前 expression_mode
# ============================================================

# 常见真实词汇模式（中英文），用于检测非拟声词
# 排除拟声词(ah, oo, mm, ba, da, ma 等)和动作描述中的*...*
import re as _re

# 婴儿咿呀声/拟声词白名单（不算"真实词汇"）
_BABBLE_WORDS = {
    "ah", "aah", "ahhh", "oo", "ooh", "oooh", "mm", "mmm", "hmm",
    "ba", "da", "ma", "pa", "ga", "na", "wa", "la", "ta",
    "baba", "dada", "mama", "papa", "gaga", "nana", "wawa",
    "ba-ba", "da-da", "ma-ma", "pa-pa", "ga-ga",
    "ba-da", "da-ba", "ba-da-ba", "da-da-da", "ba-ba-ba",
    "ah", "oh", "uh", "eh", "oo", "ee", "aah", "ooh",
    "goo", "coo", "boo", "moo", "wah", "gah", "dah",
}


def _extract_speech_from_response(response: str) -> str:
    """从 baby_response 中提取非动作描述的文本（即去掉 *...* 标记内的内容）。"""
    # 移除 *动作描述* 部分
    no_actions = _re.sub(r'\*[^*]*\*', '', response)
    return no_actions.strip()


def _has_real_words(text: str) -> bool:
    """检测文本中是否包含真实词汇（非拟声词/非标点）。"""
    if not text:
        return False
    # 提取所有中文字符
    chinese_chars = _re.findall(r'[\u4e00-\u9fff]', text)
    # 提取所有英文单词
    english_words = _re.findall(r'[a-zA-Z]+', text)

    # 检查英文单词是否有非拟声词
    for word in english_words:
        if word.lower() not in _BABBLE_WORDS:
            return True
    # 任何中文字符（非拟声词白名单）都算真实词汇
    babble_cn = set()  # 后端统一英文，无中文拟声词
    for ch in chinese_chars:
        if ch not in babble_cn:
            return True
    return False


def _count_word_units(text: str) -> int:
    """计算"词单元"数量（英文单词数 + 中文连续片段数）。"""
    if not text:
        return 0
    english_words = [w for w in _re.findall(r'[a-zA-Z]+', text)
                     if w.lower() not in _BABBLE_WORDS]
    chinese_segments = _re.findall(r'[\u4e00-\u9fff]+', text)
    # 中文每段按字数计（去掉拟声字）
    babble_cn = set()  # 后端统一英文，无中文拟声词
    cn_chars = sum(1 for seg in chinese_segments for ch in seg if ch not in babble_cn)
    return len(english_words) + cn_chars


def _validate_expression_output(response: str, expression_mode: str) -> str | None:
    """
    校验 baby_response 是否符合 expression_mode 约束。

    返回 None 表示通过，返回 str 表示违规原因。
    违规时调用方应降级为预设反应。
    """
    speech = _extract_speech_from_response(response)
    has_words = _has_real_words(speech)
    word_count = _count_word_units(speech)

    if expression_mode == "cry_only":
        # 绝对不能有任何真实词汇
        if has_words:
            return f"cry_only mode violation: found real words in '{speech[:50]}'"

    elif expression_mode == "coo_and_gaze":
        # 只能有元音拟声，不能有真实词汇
        if has_words:
            return f"coo_and_gaze mode violation: found real words in '{speech[:50]}'"

    elif expression_mode == "babble_and_reach":
        # 只能有音节组合拟声，不能有真实词汇
        if has_words:
            return f"babble_and_reach mode violation: found real words in '{speech[:50]}'"

    elif expression_mode == "gesture_and_point":
        # 可以有意向性发声，但不能有真实词汇
        if has_words:
            return f"gesture_and_point mode violation: found real words in '{speech[:50]}'"

    elif expression_mode == "first_words":
        # 只能有单词，不超过 3 个词单元
        if word_count > 3:
            return f"first_words mode violation: {word_count} word units (max 3)"

    elif expression_mode == "two_word":
        # 2-3 词组合，不超过 6 个词单元
        if word_count > 6:
            return f"two_word mode violation: {word_count} word units (max 6)"

    # sentence 及以上模式不做严格限制
    return None


def _get_llm():
    """获取 LLM 客户端。"""
    from llm import create_client, PROVIDERS, get_model
    provider = os.environ.get("LLM_PROVIDER", "deepseek")
    client = create_client(provider)
    model = get_model(provider)
    return client, model, provider


# 叙事引擎系统指令：建立合法的游戏/模拟软件上下文，
# 避免代理层"编程助手"系统指令导致拒绝
_NARRATIVE_SYSTEM = (
    "You are a game content generator for AngelCradle, a Tamagotchi-style "
    "virtual pet simulation game. Like Tamagotchi or Nintendogs, players "
    "nurture a virtual creature through growth stages. Your job is to "
    "produce game dialogue text and event descriptions for the virtual "
    "pet character — similar to how a game writer scripts NPC lines in "
    "The Sims or Animal Crossing. All output must be valid JSON. "
    "You are writing fictional game content, not roleplaying."
)


def _call_and_parse(prompt: str, metadata: dict | None = None) -> dict | list | None:
    """调用 LLM 并解析 JSON。失败返回 None 而非脏数据。"""
    from llm import call_llm_chat, parse_json
    try:
        client, model, provider = _get_llm()
        raw = call_llm_chat(
            _NARRATIVE_SYSTEM,
            [{"role": "user", "content": prompt}],
            client, model, provider,
            metadata=metadata,
        )
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


# 出生地国家代码 -> 宝宝母语
_COUNTRY_LANGUAGE: dict[str, str] = {
    "CN": "Chinese (中文)",
    "JP": "Japanese (日本語)",
    "KR": "Korean (한국어)",
    "TH": "Thai (ภาษาไทย)",
    "VN": "Vietnamese (Tiếng Việt)",
    "US": "English",
    "GB": "English",
    "AU": "English",
    "CA": "English",
    "IN": "Hindi (हिन्दी)",
    "DE": "German (Deutsch)",
    "FR": "French (Français)",
    "BR": "Portuguese (Português)",
    "RU": "Russian (Русский)",
    "ES": "Spanish (Español)",
    "MX": "Spanish (Español)",
    "IT": "Italian (Italiano)",
    "NG": "English",  # 尼日利亚官方语言
    "SA": "Arabic (العربية)",
    "EG": "Arabic (العربية)",
    "ID": "Indonesian (Bahasa Indonesia)",
    "PH": "Filipino (Tagalog)",
    "PK": "Urdu (اردو)",
    "BD": "Bengali (বাংলা)",
    "TR": "Turkish (Türkçe)",
    "PL": "Polish (Polski)",
    "NL": "Dutch (Nederlands)",
    "SE": "Swedish (Svenska)",
}

# 区域兜底
_REGION_LANGUAGE: dict[str, str] = {
    "East Asia": "Chinese (中文)",
    "Southeast Asia": "English",
    "South Asia": "Hindi (हिन्दी)",
    "Western Europe": "English",
    "Eastern Europe": "Russian (Русский)",
    "Northern Europe": "English",
    "Southern Europe": "Spanish (Español)",
    "North America": "English",
    "South America": "Portuguese (Português)",
    "Central America": "Spanish (Español)",
    "Middle East": "Arabic (العربية)",
    "North Africa": "Arabic (العربية)",
    "Sub-Saharan Africa": "English",
    "Oceania": "English",
}


def _birthplace_language(state) -> str:
    """根据出生地国家代码返回语言名称。"""
    bp = getattr(state, "birthplace", None) or {}
    code = bp.get("code", "")
    region = bp.get("region", "")
    lang = _COUNTRY_LANGUAGE.get(code)
    if not lang and region:
        lang = _REGION_LANGUAGE.get(region)
    return lang or "English"


def _detect_message_language(message: str) -> str | None:
    """检测父母消息的语言。返回语言名称或 None。"""
    # 日文假名优先检测（日文也含汉字，但有假名就是日文）
    if any("\u3040" <= c <= "\u309f" or "\u30a0" <= c <= "\u30ff" for c in message):
        return "Japanese (日本語)"
    if any("\uac00" <= c <= "\ud7af" for c in message):
        return "Korean (한국어)"
    if any("\u4e00" <= c <= "\u9fff" for c in message):
        return "Chinese (中文)"
    if any("\u0e01" <= c <= "\u0e5b" for c in message):
        return "Thai (ภาษาไทย)"
    if any("\u0400" <= c <= "\u04ff" for c in message):
        return "Russian (Русский)"
    if any("\u0600" <= c <= "\u06ff" for c in message):
        return "Arabic (العربية)"
    if any("\u0900" <= c <= "\u097f" for c in message):
        return "Hindi (हिन्दी)"
    return None  # 拉丁字母系无法可靠区分，回退到出生地语言


def _baby_language_instruction(state, parent_message: str | None = None) -> str:
    """确定宝宝回复语言。

    对话场景（有 parent_message）：父母用什么语言说→宝宝用什么语言回（家庭语言 L1）。
    叙事场景（无 parent_message）：用出生地语言（环境语言）。
    """
    env_lang = _birthplace_language(state)

    if parent_message is not None:
        # 对话：家庭语言 = 父母的语言
        family_lang = _detect_message_language(parent_message) or env_lang
        if family_lang == env_lang:
            return f"Respond in {family_lang}."
        return (
            f"Respond in {family_lang} (the family's home language). "
            f"The baby also has exposure to {env_lang} from the local environment, "
            f"but primarily speaks the family language at this age."
        )

    # 叙事：环境语言
    return f"Respond in {env_lang}. This is the local language of the baby's environment."


def generate_interaction_response(
    state: BabyState,
    parent_message: str,
    recent_interactions: list[dict],
    action_type: str = "message",
    touch_description: str | None = None,
) -> dict:
    """
    生成婴儿对父母消息的反应。

    严格受 expression_mode 约束——cry_only 不能用词，coo_and_gaze 不能形成音节。
    LLM 失败时降级为预设最小反应。
    """
    phase = PHASES[state.current_phase] if state.current_phase < len(PHASES) else PHASES[-1]
    expr = EXPRESSION_MODES.get(state.expression_mode, EXPRESSION_MODES["cry_only"])
    sp = state.identity.sensory_profile

    # 记忆注入：V2=on 走三层金字塔 + token_budget；V2=off 完全等同旧行为
    if is_v2_enabled():
        _rc = recall(state, context=parent_message or "", current_tags=set(), token_budget=1500)
        memories_text = build_memory_prompt_block(_rc, empty_fallback="No memories yet.")
    else:
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

    # 对话声音画像（阶段转换时持久化，同一阶段内稳定）
    voice_profile = state.voice_profile or "No distinctive voice yet — newborn."

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

    # 宝宝回复语言：对话时跟家庭语言（父母说什么就回什么）
    lang_instruction = _baby_language_instruction(state, parent_message)

    # 构造父母动作描述
    if action_type == "touch" and touch_description:
        parent_action_text = "[PHYSICAL TOUCH] " + touch_description
        if parent_message:
            parent_action_text += f' (parent also says: "{parent_message}")'
    else:
        parent_action_text = f'[SPEECH] "{parent_message}"'

    prompt = f"""You are a game dialogue writer for Angel Cradle, a Tamagotchi-style virtual pet simulation.
Write the in-game dialogue line for a virtual pet character reacting to the player's action, based on the character sheet below.
This is like scripting NPC dialogue in The Sims — you produce game text, not real child output.

## Dialogue Style Rules
- Write age-appropriate game dialogue for a {state.age_days}-day-old virtual {state.species} character.
- HARD LIMIT: baby_response must be under 80 Chinese characters (or 40 English words).
- AVOID: literary metaphors, self-analytical statements, adult vocabulary, sensory self-narration.
- Grammar quirks and abrupt topic changes add character authenticity.
- {lang_instruction}

## Conversational Voice (THIS IS THE CHARACTER'S UNIQUE PERSONALITY — follow it closely)
{voice_profile}
The voice profile above defines HOW this specific child talks. Two children with different profiles MUST sound different even when answering the same question. A high-arousal hearing-dominant child might yell excitedly with sound effects, while a low-arousal touch-dominant child might whisper and reach for your hand.

## The Child
- Name: {state.name or '(unnamed)'}
- Age: {state.age_days} days ({phase.age_range})
- Phase: {phase.display_name} — {phase.description}

## Expression Mode (STRICTLY ENFORCED)
- Mode: {state.expression_mode}
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
- Stress level: {state.stress.stress_level:.1f}
{f"- REGRESSED capabilities (temporarily lost): {', '.join(r['capability'] for r in state.stress.regressed_capabilities)}" if state.stress.regressed_capabilities else ""}
- Emotional vocabulary: {', '.join(state.emotional.emotional_vocabulary) or 'None'}
- Empathy level: {state.emotional.empathy_level}
{f"- Imaginary friend: {state.emotional.imaginary_friend} (a pretend companion — only bring up during play or when lonely, NEVER when asked about the baby's own name/identity)" if state.emotional.imaginary_friend else ""}
{f"- Transitional object: {state.nutrition_sleep.transitional_object} (a comfort item like a toy/blanket — only mention when stressed or seeking comfort, NOT as a person)" if state.nutrition_sleep.transitional_object else ""}

## Recent Memories
{memories_text}

## Recent Conversation
{conv_text or '(first interaction)'}
{repetition_note}

## Parent Action
{parent_action_text}

## Task
Write the game character's dialogue line. Rules:
1. HARD CHARACTER LIMIT: Under 80 Chinese characters / 40 English words. No exceptions.
2. Expression mode is law. A cry_only character CANNOT use words. An "independent" 7yo-stage character gets 2-3 SHORT sentences max.
3. Traits show through BEHAVIOR in the dialogue, not self-narration. WRONG: "我的耳朵不喜欢这个". RIGHT: *捂住耳朵* "太吵了！"
4. The character has its own agenda. Repeated topics → boredom. Novel things → curiosity. Distress + comfort → trust.
5. Write natural, age-appropriate game dialogue: messy, self-centered, abrupt.
6. For PHYSICAL TOUCH actions: react with body language, sounds, and physical sensations FIRST. Describe squirming, giggling, reaching, relaxing, or resisting. Verbal response is secondary (if any at the current expression_mode).

For state_changes, ONLY include fields that genuinely changed. Use null for no change.
- new_preference: if the child showed genuine sustained interest (not just momentary attention)
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

    result = _call_and_parse(prompt, metadata={
        "baby_id": state.baby_id, "phase": state.current_phase,
        "callsite": "generate_interaction_response",
    })
    if result and isinstance(result, dict) and "baby_response" in result:
        # 表达模式后验证：检查 LLM 输出是否符合当前 expression_mode
        violation = _validate_expression_output(result["baby_response"], state.expression_mode)
        if violation:
            logger.warning("Expression mode violation: %s — falling back to preset", violation)
            fallback = _FALLBACK_REACTIONS.get(state.expression_mode, "*Pauses, looks at you*")
            return {"baby_response": fallback, "emotional_tone": "neutral", "state_changes": {}}
        return {
            "baby_response": result["baby_response"],
            "emotional_tone": result.get("emotional_tone", "neutral"),
            "state_changes": result.get("state_changes", {}),
        }

    # LLM 调用失败降级
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

    # 预计算每个事件的因果标签（cause_tags 在 LLM 调用前生成）
    cause_tags_by_event: dict[str, list[str]] = {}
    for event in all_events:
        event_data = {
            "sensory_channels": event.sensory_channels,
            "intensity": event.intensity,
            "category": event.category,
        }
        cause_tags_by_event[event.name] = generate_cause_tags(
            event_data, state.identity, state,
        )

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

    # 记忆注入：V2=on 走三层金字塔（含 tag 一跳扩展）；V2=off 完全等同旧行为
    if is_v2_enabled():
        _ctx = "; ".join(e.display_name for e in all_events[:5])
        # 聚合事件 cause_tags 作为检索 tags
        _tags: set[str] = set()
        for _t_list in cause_tags_by_event.values():
            _tags.update(_t_list)
        _rc = recall(state, context=_ctx, current_tags=_tags, token_budget=1500)
        memory_text = build_memory_prompt_block(_rc, empty_fallback="")
    else:
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

## Physical State
- Height: {state.physical.height_cm}cm, Weight: {state.physical.weight_kg}kg, Teeth: {state.physical.teeth_count}
- Feeding mode: {state.nutrition_sleep.feeding_mode}
- Sleep quality: {state.nutrition_sleep.sleep_quality}, Night wakings: {state.nutrition_sleep.night_waking_frequency}
{"- Sleep regression ACTIVE" if state.nutrition_sleep.sleep_regression_active else ""}
{f"- Transitional object: {state.nutrition_sleep.transitional_object}" if state.nutrition_sleep.transitional_object else ""}

## Stress & Regression
- Stress level: {state.stress.stress_level:.1f}
- Regressed capabilities: {', '.join(r['capability'] for r in state.stress.regressed_capabilities) or 'None'}
- Resilience strengths: {', '.join(state.stress.resilience_bonus) or 'None'}

## Emotional Development
- Tantrum frequency: {state.emotional.tantrum_frequency}
- Empathy level: {state.emotional.empathy_level}
- Emotional vocabulary: {', '.join(state.emotional.emotional_vocabulary) or 'None yet'}
- Play type: {state.emotional.play_type}
{f"- Imaginary friend: {state.emotional.imaginary_friend}" if state.emotional.imaginary_friend else ""}

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
    "new_preference": "if a new preference formed (empty string if not)",
    "life_tag_hint": "a lasting behavioral tag if this event changed the child, e.g. noise_sensitive, visual_learner (null if not)"
  }},
  ...
]
"""

    result = _call_and_parse(prompt, metadata={
        "baby_id": state.baby_id, "phase": state.current_phase,
        "callsite": "narrate_phase_events",
    })

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

        # 因果标签：合并场景涉及的所有事件的 cause_tags
        scene_cause_tags: list[str] = []
        for en in event_names:
            scene_cause_tags.extend(cause_tags_by_event.get(en, []))

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
            "life_tag_hint": item.get("life_tag_hint"),
            "cause_tags": scene_cause_tags,
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

    # 因果标签：LLM 调用前生成 cause_tags
    event_data = {
        "sensory_channels": event.sensory_channels,
        "intensity": event.intensity,
        "category": event.category,
    }
    cause_tags = generate_cause_tags(event_data, state.identity, state)

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
    # 记忆注入：V2=on 用 recall 替换 _format_recent_memories；V2=off 完全等同旧行为
    if is_v2_enabled():
        _ctx = f"{event.display_name}: {event.description}"
        _rc = recall(state, context=_ctx, current_tags=set(cause_tags), token_budget=1500)
        _memories_block = build_memory_prompt_block(
            _rc, empty_fallback="No memories yet — this is early life."
        )
    else:
        _memories_block = _format_recent_memories(recent_memories)

    prompt = f"""You are a game content generator for Angel Cradle, a Tamagotchi-style virtual pet simulation game.
Generate a simulated {state.species} infant's reaction to a significant developmental event.

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
- Stress level: {state.stress.stress_level:.1f}
- Regressed capabilities: {', '.join(r['capability'] for r in state.stress.regressed_capabilities) or 'None'}
- Physical: {state.physical.height_cm}cm, {state.physical.weight_kg}kg, {state.physical.teeth_count} teeth
- Feeding: {state.nutrition_sleep.feeding_mode}
- Emotional vocabulary: {', '.join(state.emotional.emotional_vocabulary) or 'None'}
- Empathy level: {state.emotional.empathy_level}
{f"- Imaginary friend: {state.emotional.imaginary_friend}" if state.emotional.imaginary_friend else ""}

## Recent Memories
{_memories_block}

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

    result = _call_and_parse(prompt, metadata={
        "baby_id": state.baby_id, "phase": state.current_phase,
        "callsite": "process_critical_event",
    })
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
        "cause_tags": cause_tags,
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
    # 所有照护者的交互总计
    interaction_count = sum(c.interaction_count for c in state.caregivers.values()) if state.caregivers else 0

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

## Physical & Physiological
- Height: {state.physical.height_cm}cm, Weight: {state.physical.weight_kg}kg, Teeth: {state.physical.teeth_count}
- Feeding: {state.nutrition_sleep.feeding_mode}
- Sleep quality: {state.nutrition_sleep.sleep_quality}, Night wakings: {state.nutrition_sleep.night_waking_frequency}
{"- Sleep regression ACTIVE" if state.nutrition_sleep.sleep_regression_active else ""}
{f"- Transitional object: {state.nutrition_sleep.transitional_object}" if state.nutrition_sleep.transitional_object else ""}

## Stress & Regression
- Stress level: {state.stress.stress_level:.1f}
- Regressed capabilities: {', '.join(r['capability'] for r in state.stress.regressed_capabilities) or 'None'}
- Resilience bonus: {', '.join(state.stress.resilience_bonus) or 'None'}

## Emotional Development
- Tantrum frequency: {state.emotional.tantrum_frequency}
- Empathy level: {state.emotional.empathy_level}
- Emotional vocabulary: {', '.join(state.emotional.emotional_vocabulary) or 'None yet'}
- Play type: {state.emotional.play_type}
{f"- Imaginary friend: {state.emotional.imaginary_friend}" if state.emotional.imaginary_friend else ""}

## Task

Write a developmental summary (150-250 words) in English. Include:
1. What changed in this phase — specific, traceable to events
2. What new capabilities emerged and how they manifested
3. The infant's emotional arc through this phase (stress, regression, recovery)
4. Physical growth milestones (feeding transitions, teething, growth)
5. What patterns are forming (fears, preferences, coping strategies)
6. How caregiver interactions influenced development — teaching, bonding, stimulation
7. What to watch for in the next phase

Also update developmental metrics. Caregiver engagement level should factor into attachment assessment.

Output as JSON:
{{
  "summary": "developmental summary text",
  "capabilities_gained": ["new capabilities from this phase"],
  "personality_notes": ["observations about emerging personality"],
  "attachment_update": "secure/anxious/avoidant/forming — based on caregiver interactions and responsiveness",
  "stress_note": "stress and regression observations this phase",
  "physical_note": "physical growth observations this phase",
  "next_phase_watch": "what to watch for in the next phase"
}}
"""

    result = _call_and_parse(prompt, metadata={
        "baby_id": state.baby_id, "phase": state.current_phase,
        "callsite": "generate_phase_summary",
    })
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


# ============================================================
# 心跳主动行为：LLM 作为生命体的潜意识
# ============================================================


# 心跳降级预设（LLM 失败时使用）
_HEARTBEAT_FALLBACKS = {
    "cry_only": {"expression": "*Stirs, a soft whimper*", "behavior_type": "verbal",
                 "type": "urgent", "trigger": "discomfort", "parent_hint": "The baby seems uneasy"},
    "coo_and_gaze": {"expression": "*Looks around, soft 'ahh'*", "behavior_type": "verbal",
                     "type": "exploratory", "trigger": "curious", "parent_hint": "The baby wants attention"},
    "babble_and_reach": {"expression": "*'Ba-ba!' reaching out*", "behavior_type": "physical",
                         "type": "exploratory", "trigger": "play", "parent_hint": "The baby wants something"},
    "gesture_and_point": {"expression": "*Points at you, urgent 'ah!'*", "behavior_type": "physical",
                          "type": "exploratory", "trigger": "curious", "parent_hint": "The baby wants your attention"},
    "first_words": {"expression": "*'Mama!' looks at you*", "behavior_type": "verbal",
                    "type": "exploratory", "trigger": "share", "parent_hint": "The baby is calling you"},
    "two_word": {"expression": "*'Come here!'*", "behavior_type": "verbal",
                 "type": "exploratory", "trigger": "play", "parent_hint": "The baby wants you"},
    "sentence": {"expression": "*'Mommy! Why is sky blue?'*", "behavior_type": "verbal",
                 "type": "exploratory", "trigger": "curious", "parent_hint": "The child has a question"},
    "narrative": {"expression": "*'Mommy! Guess what!'*", "behavior_type": "verbal",
                  "type": "exploratory", "trigger": "share", "parent_hint": "The baby wants to share"},
    "reasoning": {"expression": "*'Mom, I was thinking...'*", "behavior_type": "verbal",
                  "type": "exploratory", "trigger": "share", "parent_hint": "The child wants to share a thought"},
    "independent": {"expression": "*'Mom, I need to talk to you.'*", "behavior_type": "verbal",
                    "type": "exploratory", "trigger": "share", "parent_hint": "The child wants to discuss something"},
}

# 忽略反应降级预设
_IGNORED_FALLBACKS = {
    ("cry_only", "forming"): {"reaction": "*Whimpers grow louder, fists clench*", "emotional_tone": "negative"},
    ("cry_only", "secure"): {"reaction": "*Fussy cry, then self-soothes with thumb*", "emotional_tone": "negative"},
    ("cry_only", "anxious"): {"reaction": "*Wailing intensifies, body arches*", "emotional_tone": "negative"},
    ("cry_only", "avoidant"): {"reaction": "*Crying fades, turns head away*", "emotional_tone": "negative"},
    ("coo_and_gaze", "forming"): {"reaction": "*Stares at door, 'ahh...' fading*", "emotional_tone": "negative"},
    ("coo_and_gaze", "secure"): {"reaction": "*Looks away, finds own hand to suck*", "emotional_tone": "neutral"},
    ("coo_and_gaze", "anxious"): {"reaction": "*Whimpers louder, arms flailing*", "emotional_tone": "negative"},
    ("coo_and_gaze", "avoidant"): {"reaction": "*Goes quiet, stares at ceiling*", "emotional_tone": "neutral"},
}


def generate_heartbeat_evaluation(
    state: BabyState,
    provider,
    monologue: str,
    behavior_space,
    expression_mode: str,
    expression_constraints: dict,
    ini_state,
) -> dict | None:
    """
    LLM 作为生命体潜意识，判断此刻是否要主动发起行为。
    返回 initiative dict 或 None。
    """
    species = provider.get_species(state)
    age_days = provider.get_age_days(state)

    # Few-shot：从场景库抽 3-5 条当前 phase 的真实场景注入 prompt
    # 让 LLM 看到 phase 应有的表达风格，降低违规率
    few_shot_block = ""
    try:
        from scenes import pick_scene, load_scenes_for_phase
        phase_scenes = load_scenes_for_phase(state.current_phase)
        if phase_scenes:
            import random as _rnd
            sample = _rnd.sample(phase_scenes, min(4, len(phase_scenes)))
            shots = []
            for s in sample:
                shots.append(
                    f"- Trigger: {s.trigger} | Context: {s.context}\n"
                    f"  Expression: {s.expression}\n"
                    f"  Intent: {s.intent}"
                )
            few_shot_block = (
                "\n## Example Scenes for This Phase (few-shot — follow this style)\n"
                + "\n".join(shots) + "\n"
            )
    except Exception:
        few_shot_block = ""

    prompt = f"""You are a game content generator for Angel Cradle, a Tamagotchi-style virtual pet simulation game.
Model the simulated internal state of a {species} individual aged {age_days} days.

Based on the individual's current internal state, decide: does this simulated child
want to reach out to (or actively avoid) their caregiver RIGHT NOW?

## Rules
1. Most of the time, the answer is NO. Children are not constantly seeking
   attention. Silence is the default. Return initiative: false for ~70% of calls.
2. Only say YES if there is a genuine, developmentally appropriate reason:
   real discomfort, genuine curiosity, wanting to share something specific,
   genuine boredom after a long idle period, or a need for distance/privacy.
3. BEHAVIOR TYPES:
   - "verbal": speaking, calling, crying, babbling, or DELIBERATE silence
   - "physical": body actions — reaching, pointing, pulling, pushing, hiding
   - "avoidance": actively creating distance — dodging questions, refusing
     interaction, hiding secrets, seeking solitude
4. Avoidance IS initiative. A child who locks their door is making a choice.
5. Expression MUST conform to expression_mode constraints:
   Mode: {expression_mode}
   Description: {expression_constraints.get('description', '')}
   Format: {expression_constraints.get('format', '')}
6. ANTI-AI RULES: No literary language, no self-analysis, no metaphors.
   Real children, messy and immediate.
7. If YES, expression must be SHORT: under 30 English words.
8. ALWAYS respond in English. All expressions, hints, and output must be in English.
{few_shot_block}
{behavior_space.to_prompt_section()}

## The Child's Inner State
{monologue}

## Output
Return JSON only:
{{
  "initiative": true/false,
  "type": "urgent" | "exploratory" | null,
  "behavior_type": "verbal" | "physical" | "avoidance" | null,
  "trigger": "hunger|sleepy|wet_diaper|soiled_diaper|gas_colic|teething|too_hot|too_cold|hiccup|pain|fear|lonely|boundary|overstimulated|curious|bored|play|share|secret|autonomy" | null,
  "expression": {{
    "vocalization": "the sound the child makes (cry type, babble, words) — short",
    "facial": "facial expression (scrunched face, wide eyes, lip tremble, etc.)",
    "body": "body action (kicking, arching, reaching, curling up, etc.)",
    "signal": "the observable cue a caregiver would notice first"
  }} | null,
  "parent_hint": "brief hint for the parent explaining what the child needs" | null
}}

If initiative is false, set all other fields to null."""

    result = _call_and_parse(prompt, metadata={
        "baby_id": state.baby_id, "phase": state.current_phase,
        "callsite": "generate_heartbeat_evaluation",
    })
    if result and isinstance(result, dict):
        if result.get("initiative"):
            return result
        return None  # 静默

    # LLM 失败 → 默认静默（不应因 LLM 故障而触发主动行为）
    logger.warning("Heartbeat LLM failed, defaulting to silence for mode=%s", expression_mode)
    return None


def generate_ignored_reaction(
    state: BabyState,
    provider,
    ini_state,
    initiative_type: str,
    behavior_type: str,
) -> dict:
    """
    LLM 生成宝宝被忽略后的情绪反应。
    """
    expression_mode = provider.get_expression_mode(state)
    attachment = provider.get_attachment_style(state)
    expression_constraints = provider.get_expression_constraints(state)
    species = provider.get_species(state)
    age_days = provider.get_age_days(state)

    prompt = f"""You are a game content generator for Angel Cradle, a Tamagotchi-style virtual pet simulation game.
A simulated {species} individual aged {age_days} days just tried to get their caregiver's attention
({initiative_type}, {behavior_type}) but received no response. Generate the simulated emotional reaction.

## Reaction patterns (by attachment style: {attachment})
- secure: brief disappointment → self-soothe → find something else
- anxious: louder crying → clingy → persistent attention-seeking
- avoidant: quiet withdrawal → self-play → stops trying
- forming: confusion → retry → may cry

## Expression constraints
Mode: {expression_mode}
Format: {expression_constraints.get('format', '')}

## Context
- Consecutive ignores: {ini_state.consecutive_ignores}
- Stress level: {provider.get_stress_state(state).stress_level:.1f}

## Rules
1. Under 25 English words.
2. ANTI-AI: no literary language. Real child reactions.
3. ALWAYS respond in English.

Output JSON:
{{
  "reaction": "the child's reaction",
  "emotional_tone": "positive/negative/neutral"
}}"""

    result = _call_and_parse(prompt, metadata={
        "baby_id": state.baby_id, "phase": state.current_phase,
        "callsite": "generate_ignored_reaction",
    })
    if result and isinstance(result, dict) and "reaction" in result:
        return result

    # 降级
    key = (expression_mode, attachment)
    fallback = _IGNORED_FALLBACKS.get(key, {"reaction": "*Looks away quietly*", "emotional_tone": "negative"})
    return fallback
