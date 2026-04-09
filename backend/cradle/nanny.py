"""
保姆：自动模拟引擎。

每个阶段运行一次，产出日常事件摘要、环境事件反应、关键事件（等待父母）。
保姆不是 NPC，是系统内核。

[INPUT]: 依赖 cradle/state.py, cradle/events.py, cradle/mind.py, cradle/phases.py
[OUTPUT]: simulate_phase(), SimulationResult
[POS]: cradle/ 的核心引擎，被 API 层调用
[PROTOCOL]: 变更时更新此头部，然后检查 CLAUDE.md
"""

from __future__ import annotations

import logging
import random
from concurrent.futures import ThreadPoolExecutor, Future, TimeoutError
from dataclasses import dataclass, field

logger = logging.getLogger(__name__)

# LLM 调用超时（秒）
LLM_TIMEOUT = 120

from .state import BabyState, Memory, Milestone, save_state
from .phases import PHASES, EXPRESSION_MODES
from .events import roll_events, Event, get_event
from .mind import narrate_phase_events, process_critical_event, generate_phase_summary, _perceptual_filter


@dataclass
class PhaseResult:
    """一个阶段的模拟结果。"""
    phase_index: int
    phase_name: str
    phase_display: str
    age_range: str

    # 日常事件摘要（不需要 LLM）
    daily_summary: list[dict] = field(default_factory=list)

    # 环境事件反应（LLM 生成）
    environment_reactions: list[dict] = field(default_factory=list)

    # 关键事件（需要父母介入的）
    critical_events: list[dict] = field(default_factory=list)

    # 阶段总结
    summary: dict = field(default_factory=dict)

    # 新解锁的能力
    new_capabilities: list[str] = field(default_factory=list)

    # 新里程碑
    new_milestones: list[dict] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "phase_index": self.phase_index,
            "phase_name": self.phase_name,
            "phase_display": self.phase_display,
            "age_range": self.age_range,
            "daily_summary": self.daily_summary,
            "environment_reactions": [
                {k: v for k, v in r.items() if k != "memory"}
                for r in self.environment_reactions
            ],
            "critical_events": [
                {k: v for k, v in r.items() if k != "memory"}
                for r in self.critical_events
            ],
            "summary": self.summary,
            "new_capabilities": self.new_capabilities,
            "new_milestones": self.new_milestones,
        }



# ============================================================
# 缺陷→受阻能力映射
# ============================================================

# 缺陷名（子宫 complications 输出）→ 永远无法解锁的能力列表
DEFECT_BLOCKED_CAPABILITIES: dict[str, list[str]] = {
    # 听觉缺陷
    "hearing_loss": ["sound_localization", "babbling_syllables"],
    "congenital_deafness": ["sound_localization", "babbling_syllables"],
    # 视觉缺陷
    "vision_impairment": ["visual_tracking"],
    "congenital_blindness": ["visual_tracking", "self_recognition", "reading_readiness"],
    # 运动缺陷
    "limb_malformation": ["crawling", "walking", "running"],
    "motor_deficit": ["crawling", "walking", "running", "grasping"],
    "neural_tube_defect": ["crawling", "walking", "running"],
    # 认知缺陷
    "cognitive_delay": ["hypothetical_thinking", "analogy", "reading_readiness"],
}

# 缺陷→延迟解锁（延迟 N 个阶段才能解锁）
DEFECT_DELAYED_CAPABILITIES: dict[str, dict[str, int]] = {
    "hearing_loss": {"first_words": 2, "two_word_sentences": 2, "full_sentences": 2},
    "congenital_deafness": {"first_words": 3, "two_word_sentences": 3, "full_sentences": 3},
    "cognitive_delay": {"first_words": 1, "object_permanence": 1, "self_recognition": 2},
}


def _blocked_capabilities(state: BabyState) -> set[str]:
    """根据先天缺陷，计算永远不能解锁的能力集合。"""
    blocked = set()
    for defect in state.identity.defects:
        # 精确匹配 + 关键词模糊匹配
        defect_key = defect.lower().replace(" ", "_")
        for pattern, caps in DEFECT_BLOCKED_CAPABILITIES.items():
            if pattern in defect_key or defect_key in pattern:
                blocked.update(caps)
    return blocked


def _delayed_capability_phase(state: BabyState, cap: str, normal_phase: int) -> int:
    """返回某能力因缺陷延迟后的最早解锁阶段。"""
    max_delay = 0
    for defect in state.identity.defects:
        defect_key = defect.lower().replace(" ", "_")
        for pattern, delays in DEFECT_DELAYED_CAPABILITIES.items():
            if pattern in defect_key or defect_key in pattern:
                max_delay = max(max_delay, delays.get(cap, 0))
    return normal_phase + max_delay


# ============================================================
# 能力解锁检查
# ============================================================

def _check_capability_unlocks(state: BabyState, phase_index: int) -> list[str]:
    """检查当前阶段应解锁的能力，尊重先天缺陷约束。"""
    phase = PHASES[phase_index]
    blocked = _blocked_capabilities(state)
    new_caps = []
    for cap in phase.capabilities:
        if cap in state.capabilities:
            continue
        # 永久受阻
        if cap in blocked:
            logger.info("Capability '%s' permanently blocked by congenital defect", cap)
            continue
        # 延迟解锁
        required_phase = _delayed_capability_phase(state, cap, phase_index)
        if phase_index < required_phase:
            logger.info("Capability '%s' delayed to phase %d by congenital defect", cap, required_phase)
            continue
        new_caps.append(cap)
        state.capabilities.append(cap)
    return new_caps


# ============================================================
# 里程碑检测
# ============================================================

MILESTONE_DEFINITIONS = {
    "first_smile": {
        "trigger_capabilities": ["social_smile"],
        "description": "First social smile",
        "min_phase": 1,
    },
    "first_grasp": {
        "trigger_capabilities": ["grasping"],
        "description": "First intentional grasp",
        "min_phase": 2,
    },
    "first_laugh": {
        "trigger_capabilities": ["laugh"],
        "description": "First laugh out loud",
        "min_phase": 2,
    },
    "object_permanence": {
        "trigger_capabilities": ["object_permanence"],
        "description": "Understands objects persist after disappearing",
        "min_phase": 3,
    },
    "first_crawl": {
        "trigger_capabilities": ["crawling"],
        "description": "First independent crawl",
        "min_phase": 4,
    },
    "first_point": {
        "trigger_capabilities": ["pointing"],
        "description": "First pointing with index finger",
        "min_phase": 4,
    },
    "first_word": {
        "trigger_capabilities": ["first_words"],
        "description": "First meaningful word",
        "min_phase": 5,
    },
    "first_step": {
        "trigger_capabilities": ["walking"],
        "description": "First independent step",
        "min_phase": 5,
    },
    "self_recognition": {
        "trigger_capabilities": ["self_recognition"],
        "description": "Recognizes self in mirror",
        "min_phase": 6,
    },
    "first_sentence": {
        "trigger_capabilities": ["full_sentences"],
        "description": "First complete sentence",
        "min_phase": 7,
    },
    "first_why": {
        "trigger_capabilities": ["why_questions"],
        "description": "First 'why' question",
        "min_phase": 7,
    },
    "first_pretend": {
        "trigger_capabilities": ["pretend_play"],
        "description": "First pretend play",
        "min_phase": 6,
    },
    "moral_awareness": {
        "trigger_capabilities": ["moral_sense"],
        "description": "First moral awareness ('unfair', 'wrong')",
        "min_phase": 8,
    },
    "independent_opinion": {
        "trigger_capabilities": ["independent_opinion"],
        "description": "First independent opinion held firmly",
        "min_phase": 11,
    },
}


def _check_milestones(state: BabyState, new_capabilities: list[str]) -> list[Milestone]:
    """检查新能力是否触发里程碑。"""
    achieved_names = {m.name for m in state.milestones}
    new_milestones = []

    for name, defn in MILESTONE_DEFINITIONS.items():
        if name in achieved_names:
            continue
        if state.current_phase < defn["min_phase"]:
            continue
        # 检查触发能力是否已解锁
        if all(cap in state.capabilities for cap in defn["trigger_capabilities"]):
            milestone = Milestone(
                name=name,
                phase=state.current_phase,
                age_days=state.age_days,
                trigger_event="capability_unlock",
                description=defn["description"],
            )
            new_milestones.append(milestone)
            state.milestones.append(milestone)

    return new_milestones


# ============================================================
# 命名事件触发（在合适的阶段自动加入）
# ============================================================

def _should_trigger_naming(state: BabyState) -> bool:
    """判断是否该触发命名事件。"""
    if state.name:
        return False  # 已命名
    # 在感知觉醒到语言爆发之间的任意阶段
    return 1 <= state.current_phase <= 6


# ============================================================
# 核心模拟函数
# ============================================================

def simulate_phase(state: BabyState) -> PhaseResult:
    """同步版，内部消费生成器。"""
    result = None
    for step in simulate_phase_stream(state):
        if step.get("event") == "phase_simulated":
            result = step["_result"]
    if result is None:
        raise RuntimeError("simulate_phase_stream did not produce a final result")
    return result


def simulate_phase_stream(state: BabyState):
    """
    流式模拟一个成长阶段。

    事件流：
    - {"event": "phase_start", ...}
    - {"event": "rolling_events", ...}        — 掷骰子
    - {"event": "daily_events", ...}          — 日常事件（规则引擎，即时）
    - {"event": "environment_processing", ...} — 环境事件 LLM 处理开始
    - {"event": "environment_reaction", ...}   — 单个环境事件反应
    - {"event": "critical_event", ...}         — 关键事件（等父母）
    - {"event": "capabilities_unlocked", ...}
    - {"event": "milestones", ...}
    - {"event": "phase_simulated", ...}        — 完成
    """
    phase_index = state.current_phase
    phase = PHASES[phase_index]

    # 幂等性：如果此阶段已模拟过（断连重连），跳过重复模拟
    if phase_index in state.simulated_phases:
        logger.info("Phase %d already simulated, skipping (idempotency protection)", phase_index)
        yield {
            "event": "phase_resumed",
            "phase_index": phase_index,
            "phase_display": phase.display_name,
            "message": "Phase already simulated, resuming to critical events.",
        }
        # 只重新发送未处理的关键事件
        yield {
            "event": "phase_simulated",
            "phase_index": phase.index,
            "has_critical_events": False,
            "critical_count": 0,
            "_result": PhaseResult(
                phase_index=phase_index,
                phase_name=phase.name,
                phase_display=phase.display_name,
                age_range=phase.age_range,
            ),
        }
        return

    result = PhaseResult(
        phase_index=phase_index,
        phase_name=phase.name,
        phase_display=phase.display_name,
        age_range=phase.age_range,
    )

    # 阶段开始
    state.age_days = phase.age_days[1]
    state.expression_mode = phase.expression_mode

    yield {
        "event": "phase_start",
        "phase_index": phase.index,
        "phase_name": phase.name,
        "phase_display": phase.display_name,
        "age_range": phase.age_range,
        "description": phase.description,
        "expression_mode": phase.expression_mode,
    }

    # 1. 事件生成（身份调制权重）
    events = roll_events(phase_index, identity=state.identity)
    all_events = events["daily"] + events["environment"]

    yield {
        "event": "fate_weaving",
        "traces": events["traces"],
    }

    # 2. 提交统一叙事 LLM（后台线程）
    executor = ThreadPoolExecutor(max_workers=1)
    narrative_future: Future | None = None
    if all_events:
        narrative_future = executor.submit(
            narrate_phase_events, state, all_events,
        )

    # 3. 感知过滤（纯计算，逐个推送）— LLM 同时在跑
    for ev in all_events:
        perception = _perceptual_filter(ev, state)
        yield {
            "event": "perceiving",
            "event_name": ev.name,
            "event_display": ev.display_name,
            "category": ev.category,
            "description": ev.description,
            "sensory_channels": ev.sensory_channels,
            "stimulus_intensity": ev.intensity,
            "perceived_channels": perception["perceived_channels"],
            "dominant_channel": perception["dominant_channel"],
            "total_perceived_intensity": perception["total_perceived_intensity"],
            "arousal_modifier": perception["intensity_modifier"],
        }

    # 4. 等待叙事 LLM 返回，逐个场景推送
    if narrative_future:
        yield {
            "event": "narrating",
            "message": "A day in the life is unfolding...",
        }

        import time as _time
        _elapsed = 0
        scenes = None
        try:
            while not narrative_future.done():
                _time.sleep(1)
                _elapsed += 1
                if _elapsed > LLM_TIMEOUT:
                    narrative_future.cancel()
                    logger.error("Narration LLM timeout (%ds), phase %d", LLM_TIMEOUT, phase_index)
                    yield {
                        "event": "narration_timeout",
                        "message": f"Narration timed out ({LLM_TIMEOUT}s), skipping.",
                    }
                    break
                yield {
                    "event": "narrating",
                    "elapsed": _elapsed,
                }
            if scenes is None and narrative_future.done():
                scenes = narrative_future.result()
        except Exception as e:
            logger.error("Narration LLM error: %s", e)
            yield {
                "event": "narration_error",
                "message": "Narration failed, skipping.",
            }
        finally:
            executor.shutdown(wait=False)
        if scenes is None:
            scenes = []

        for scene in scenes:
            # 更新状态
            if "memory" in scene:
                state.memories.append(scene["memory"])
            if scene.get("new_fear"):
                fear = scene["new_fear"]
                if fear not in state.fears:
                    state.fears.append(fear)
            if scene.get("new_preference"):
                pref = scene["new_preference"]
                if pref not in state.preferences:
                    state.preferences.append(pref)

            yield {
                "event": "scene",
                "scene": scene.get("scene", 0),
                "event_names": scene.get("event_names", []),
                "trigger": scene.get("trigger", ""),
                "nanny_observation": scene.get("nanny_observation", ""),
                "nanny_action": scene.get("nanny_action", ""),
                "baby_reaction": scene.get("baby_reaction", ""),
                "outcome": scene.get("outcome", ""),
                "transition": scene.get("transition", ""),
                "emotional_valence": scene.get("emotional_valence", "neutral"),
                "intensity": scene.get("intensity", 0.5),
                "trace": scene.get("trace", ""),
                "growth_signal": scene.get("growth_signal", ""),
            }
    else:
        executor.shutdown(wait=False)  # 无事件时直接关闭

    # 5. 关键事件
    critical = events["critical"]
    if _should_trigger_naming(state):
        naming = get_event("naming_ceremony")
        if naming and naming not in critical:
            critical.insert(0, naming)

    for event in critical:
        entry = {
            "event": event.name,
            "event_display": event.display_name,
            "description": event.description,
            "requires_parent": True,
            "parent_choices": event.parent_choices,
            "resolved": False,
        }
        result.critical_events.append(entry)
        yield {
            "event": "critical_event",
            "event_name": event.name,
            "event_display": event.display_name,
            "description": event.description,
            "parent_choices": event.parent_choices,
            "awaiting_parent": True,
        }

    # 6. 能力解锁
    new_caps = _check_capability_unlocks(state, phase_index)
    result.new_capabilities = new_caps
    if new_caps:
        yield {
            "event": "capabilities_unlocked",
            "capabilities": new_caps,
        }

    # 7. 里程碑
    milestones = _check_milestones(state, new_caps)
    result.new_milestones = [m.to_dict() for m in milestones]
    if result.new_milestones:
        yield {
            "event": "milestones",
            "milestones": result.new_milestones,
        }

    # 标记已模拟（幂等性保护）
    if phase_index not in state.simulated_phases:
        state.simulated_phases.append(phase_index)

    save_state(state)

    yield {
        "event": "phase_simulated",
        "phase_index": phase.index,
        "has_critical_events": len(result.critical_events) > 0,
        "critical_count": len(result.critical_events),
        "_result": result,  # 内部用，SSE 端点剔除
    }


def resolve_critical_event(
    state: BabyState,
    event_name: str,
    parent_action: str,
    parent_input: str = "",
) -> dict:
    """
    父母介入处理关键事件。

    event_name: 事件名
    parent_action: 父母选择的行为
    parent_input: 自由输入（如命名时的名字）
    """
    event = get_event(event_name)
    if not event:
        return {"error": f"Unknown event: {event_name}"}

    # 特殊处理：命名
    if event_name == "naming_ceremony" and parent_input:
        state.name = parent_input
        save_state(state)
        return {
            "event": "naming_ceremony",
            "reaction": f"From this moment on, this child has a name: {parent_input}.",
            "developmental_impact": "The seed of self-awareness. A name means 'I am a recognized individual'.",
        }

    # 处理其他关键事件
    reaction = process_critical_event(state, event, parent_action)

    # 更新状态
    if "memory" in reaction:
        state.memories.append(reaction["memory"])
    if reaction.get("new_fear"):
        fear = reaction["new_fear"]
        if fear not in state.fears:
            state.fears.append(fear)
    if reaction.get("new_preference"):
        pref = reaction["new_preference"]
        if pref not in state.preferences:
            state.preferences.append(pref)
    if reaction.get("new_comfort"):
        comfort = reaction["new_comfort"]
        if comfort not in state.comfort_sources:
            state.comfort_sources.append(comfort)
    if reaction.get("attachment_signal"):
        # 简单的依恋更新逻辑
        _update_attachment(state, parent_action, reaction.get("attachment_signal", ""))

    # 更新父母画像
    _update_parent_profile(state, parent_action)

    save_state(state)

    return {k: v for k, v in reaction.items() if k != "memory"}


def _update_attachment(state: BabyState, parent_action: str, signal: str) -> None:
    """根据父母行为更新依恋类型趋势。"""
    # 简单模型：响应性高 → 安全，忽视 → 回避，不一致 → 焦虑
    responsive_actions = {"comfort", "hold_and_rock", "hold_tight", "sing",
                          "celebrate", "validate", "explain_return", "calm_check"}
    avoidant_actions = {"let_cry", "ignore", "sneak_away"}
    balanced_actions = {"encourage", "gentle_smile", "boundary", "stay_nearby",
                        "gradual", "negotiate", "observe", "discuss_why"}

    if parent_action in responsive_actions:
        if state.attachment_style in ("forming", "secure"):
            state.attachment_style = "secure"
    elif parent_action in avoidant_actions:
        if state.attachment_style == "forming":
            state.attachment_style = "avoidant"
    # balanced actions tend toward secure
    elif parent_action in balanced_actions:
        if state.attachment_style == "forming":
            state.attachment_style = "secure"


def _update_parent_profile(state: BabyState, action: str) -> None:
    """更新父母画像。"""
    pp = state.parent_profile
    pp.total_interventions += 1
    pp.intervention_log.append({
        "phase": state.current_phase,
        "age_days": state.age_days,
        "action": action,
    })

    # 响应性
    responsive = {"comfort", "hold_and_rock", "hold_tight", "sing", "celebrate",
                  "validate", "rush_over", "explain_return"}
    if action in responsive:
        pp.responsiveness = min(1.0, pp.responsiveness + 0.05)
    elif action in {"let_cry", "ignore", "sneak_away"}:
        pp.responsiveness = max(0.0, pp.responsiveness - 0.05)

    # 介入风格
    protective = {"rush_over", "comfort", "hold_tight", "insist"}
    hands_off = {"let_cry", "ignore", "observe"}
    if action in protective:
        pp.intervention_style = "protective"
    elif action in hands_off:
        pp.intervention_style = "hands_off"
    else:
        pp.intervention_style = "balanced"


def complete_phase(state: BabyState) -> dict:
    """
    完成当前阶段，生成总结，推进到下一阶段。
    """
    # 生成阶段总结
    summary = generate_phase_summary(state)

    # 应用总结中的更新
    if isinstance(summary, dict):
        if summary.get("attachment_update"):
            att = summary["attachment_update"]
            if att in ("secure", "anxious", "avoidant"):
                state.attachment_style = att

    # 记录阶段总结
    state.phase_summaries.append({
        "phase": state.current_phase,
        "phase_name": PHASES[state.current_phase].name,
        "summary": summary,
    })

    # 推进到下一阶段
    completed_phase = state.current_phase
    if state.current_phase < len(PHASES) - 1:
        state.current_phase += 1
        next_phase = PHASES[state.current_phase]
        state.expression_mode = next_phase.expression_mode

    # 清除已完成阶段的模拟标记（幂等性：允许下个阶段正常模拟）
    if completed_phase in state.simulated_phases:
        state.simulated_phases.remove(completed_phase)

    save_state(state)

    return summary


def grow_stream(state: BabyState):
    """
    自动成长流：连续推进所有阶段，关键事件时暂停。

    事件流 = 多个阶段的 simulate_phase_stream + complete_phase 交织：
    - 每个阶段的全部事件（phase_start → ... → phase_simulated）
    - 如果无关键事件 → 自动 complete（LLM 总结）→ 进入下一阶段
    - 如果有关键事件 → yield paused，结束流。等父母 intervene 后重新调用。
    - 最后一个阶段完成后 yield growth_complete
    """
    while state.current_phase < len(PHASES):
        phase = PHASES[state.current_phase]
        has_critical = False

        # 运行当前阶段模拟
        for step in simulate_phase_stream(state):
            event_type = step.get("event")

            # 检测关键事件
            if event_type == "critical_event":
                has_critical = True

            # 透传所有事件（剔除内部字段）
            yield {k: v for k, v in step.items() if not k.startswith("_")}

        # 有关键事件 → 暂停，等父母介入
        if has_critical:
            yield {
                "event": "paused",
                "phase_index": state.current_phase,
                "phase_display": phase.display_name,
                "reason": "awaiting_parent",
                "message": "Growth paused — critical event requires parent intervention.",
            }
            return  # 结束流，等待 intervene + 重新调用

        # 无关键事件 → 自动完成阶段
        yield {
            "event": "phase_completing",
            "phase_index": state.current_phase,
            "phase_display": phase.display_name,
            "message": "Generating phase developmental summary...",
        }

        summary = complete_phase(state)

        next_p = PHASES[state.current_phase] if state.current_phase < len(PHASES) else None
        yield {
            "event": "phase_completed",
            "phase_index": phase.index,
            "phase_name": phase.name,
            "phase_display": phase.display_name,
            "summary": summary,
            "next_phase": next_p.display_name if next_p else None,
            "next_phase_name": next_p.name if next_p else None,
        }

    # 所有阶段完成
    yield {
        "event": "growth_complete",
        "baby_id": state.baby_id,
        "name": state.name,
        "total_phases": len(PHASES),
        "total_milestones": len(state.milestones),
        "total_memories": len(state.memories),
        "attachment_style": state.attachment_style,
    }
