"""
保姆：自动模拟引擎。

每个阶段运行一次，产出日常事件摘要、环境事件反应、关键事件（等待父母）。
保姆不是 NPC，是系统内核。

[INPUT]: 依赖 cradle/state.py, cradle/events.py, cradle/mind.py, cradle/phases.py, cradle/causality.py
[OUTPUT]: simulate_phase(), SimulationResult, _update_stress(), _check_stress_regression(), _check_regression_recovery(), _update_phase_state()
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
from .causality import generate_effect_tags


def _snapshot_state(state: BabyState) -> dict:
    """状态快照，用于因果标签的 before/after 对比。"""
    return {
        "stress_level": state.stress.stress_level,
        "attachment_style": state.attachment_style,
        "capabilities": list(state.capabilities),
        "regressed_capabilities": list(state.stress.regressed_capabilities),
        "fears": list(state.fears),
        "preferences": list(state.preferences),
    }


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
    """检查当前阶段应解锁的能力，尊重先天缺陷和压力回退约束。"""
    phase = PHASES[phase_index]
    blocked = _blocked_capabilities(state)
    regressed = {r["capability"] for r in state.stress.regressed_capabilities}
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
        # 当前已回退的能力不重复解锁（等恢复）
        if cap in regressed:
            logger.info("Capability '%s' currently regressed, skipping unlock", cap)
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
    # ---- 增强：喂养/体格/情绪/社交里程碑 ----
    "first_solid_food": {
        "trigger_state": lambda s: s.nutrition_sleep.feeding_mode == "introducing_solids",
        "description": "First taste of solid food",
        "min_phase": 3,
    },
    "first_tooth": {
        "trigger_state": lambda s: s.physical.teeth_count > 0,
        "description": "First tooth emerged",
        "min_phase": 3,
    },
    "toilet_trained": {
        "trigger_state": lambda s: s.physical.toilet_trained,
        "description": "Successfully toilet trained",
        "min_phase": 7,
    },
    "first_tantrum": {
        "trigger_state": lambda s: s.emotional.tantrum_frequency > 0,
        "description": "First full emotional meltdown",
        "min_phase": 6,
    },
    "imaginary_friend": {
        "trigger_state": lambda s: bool(s.emotional.imaginary_friend),
        "description": "Created an imaginary friend",
        "min_phase": 8,
    },
    "kindergarten_start": {
        "trigger_state": lambda s: "teacher" in s.caregivers,
        "description": "First day at kindergarten",
        "min_phase": 8,
    },
}


def _check_milestones(state: BabyState, new_capabilities: list[str]) -> list[Milestone]:
    """检查能力解锁或状态变化是否触发里程碑。"""
    achieved_names = {m.name for m in state.milestones}
    new_milestones = []

    for name, defn in MILESTONE_DEFINITIONS.items():
        if name in achieved_names:
            continue
        if state.current_phase < defn["min_phase"]:
            continue

        triggered = False
        trigger_event = ""

        # 方式一：能力触发
        if "trigger_capabilities" in defn:
            if all(cap in state.capabilities for cap in defn["trigger_capabilities"]):
                triggered = True
                trigger_event = "capability_unlock"

        # 方式二：状态触发（lambda 检查）
        if "trigger_state" in defn:
            try:
                if defn["trigger_state"](state):
                    triggered = True
                    trigger_event = "state_change"
            except Exception:
                pass

        if triggered:
            milestone = Milestone(
                name=name,
                phase=state.current_phase,
                age_days=state.age_days,
                trigger_event=trigger_event,
                description=defn["description"],
            )
            new_milestones.append(milestone)
            state.milestones.append(milestone)

    return new_milestones


# ============================================================
# 压力回退引擎（纯规则，无 LLM）
# ============================================================

# 不可回退的核心能力
UNREGRESSIVE_CAPABILITIES = {
    "startle_reflex", "sucking_reflex", "crying",
    "sleep_wake_cycle", "object_permanence",
}


def _update_stress(state: BabyState, emotional_valence: str,
                   intensity: float, parent_present: bool) -> None:
    """事件后更新压力值。"""
    stress = state.stress
    attachment_mod = {
        "secure": 0.7, "forming": 1.0, "anxious": 1.3, "avoidant": 1.1,
    }
    att_mod = attachment_mod.get(state.attachment_style, 1.0)

    if emotional_valence == "negative":
        delta = intensity * 0.15 * att_mod
        stress.stress_level = min(1.0, stress.stress_level + delta)
    elif emotional_valence == "positive":
        recovery = intensity * 0.1
        if parent_present:
            recovery *= 1.5
        stress.stress_level = max(0.0, stress.stress_level - recovery)


def _check_stress_regression(state: BabyState) -> list[str]:
    """检查是否触发能力回退。返回回退的能力名。"""
    threshold = 0.6
    if state.attachment_style == "secure":
        threshold = 0.7
    elif state.attachment_style == "anxious":
        threshold = 0.5

    if state.stress.stress_level < threshold:
        return []

    already_regressed = {r["capability"] for r in state.stress.regressed_capabilities}
    candidates = [
        cap for cap in reversed(state.capabilities)
        if cap not in UNREGRESSIVE_CAPABILITIES and cap not in already_regressed
    ]
    if not candidates:
        return []

    count = min(random.randint(1, 2), len(candidates))
    regressed = random.sample(candidates[:5], count)

    for cap in regressed:
        state.stress.regressed_capabilities.append({
            "capability": cap,
            "regressed_at": state.age_days,
            "original_phase": state.current_phase,
        })
        # 机械执行：从能力列表中移除（LLM prompt + 就绪检查都会感知）
        if cap in state.capabilities:
            state.capabilities.remove(cap)
    return regressed


def _check_regression_recovery(state: BabyState) -> list[dict]:
    """检查回退能力是否恢复。返回 [{"capability": str, "strengthened": bool}]。"""
    recovered = []
    remaining = []

    for reg in state.stress.regressed_capabilities:
        days_regressed = state.age_days - reg["regressed_at"]

        base_recovery = state.stress.stress_level < 0.3
        time_limit = 30 if state.attachment_style == "secure" else 60
        time_recovery = days_regressed > time_limit

        if base_recovery or time_recovery:
            strengthened = random.random() < 0.3
            if strengthened and reg["capability"] not in state.stress.resilience_bonus:
                state.stress.resilience_bonus.append(reg["capability"])
            # 机械执行：恢复能力到列表
            if reg["capability"] not in state.capabilities:
                state.capabilities.append(reg["capability"])
            recovered.append({
                "capability": reg["capability"],
                "strengthened": strengthened,
            })
        else:
            remaining.append(reg)

    state.stress.regressed_capabilities = remaining
    return recovered


def _natural_stress_decay(state: BabyState) -> None:
    """
    阶段末压力自然衰减。

    按阶段实际天数计算：日衰减率 0.5% → 阶段衰减 = 0.995^days。
    30 天阶段衰减约 14%，365 天阶段衰减约 84%——长阶段压力有足够时间消散。
    """
    phase = PHASES[state.current_phase]
    phase_days = phase.age_days[1] - phase.age_days[0]
    daily_retention = 0.995  # 每天保��� 99.5% 的压力
    decay_factor = daily_retention ** phase_days
    state.stress.stress_level = max(0.0, state.stress.stress_level * decay_factor)


# ============================================================
# 阶段状态自动更新（纯规则引擎，无 LLM）
# ============================================================

# 喂养模式映射（按 age_days，对齐 WHO 喂养指南）
# 0-180天(0-6月): 纯母乳, 180-365天(6-12月): 引入固体,
# 365-730天(12-24月): 自主进食学习, 730+天(2岁+): 家庭餐
FEEDING_MODE_BY_AGE = [
    (0, 180, "breast_milk"),
    (180, 365, "introducing_solids"),
    (365, 730, "self_feeding_learning"),
    (730, 99999, "family_meals"),
]

# 夜醒次数基线
NIGHT_WAKING_BY_PHASE = {
    0: 5, 1: 4, 2: 3, 3: 3, 4: 2, 5: 2, 6: 1, 7: 1,
    8: 0, 9: 0, 10: 0, 11: 0,
}

# 睡眠回归高发阶段
SLEEP_REGRESSION_PHASES = {2, 3, 6, 7}

# Tantrum 频率曲线
TANTRUM_FREQUENCY = {
    6: 0.4, 7: 0.7, 8: 0.4, 9: 0.15, 10: 0.1, 11: 0.05,
}

# 共情发展
EMPATHY_BY_PHASE = {
    (0, 4): "none", (5, 7): "primitive", (8, 11): "true",
}

# 游戏类型
PLAY_TYPE_BY_PHASE = {
    (0, 4): "functional", (5, 6): "constructive",
    (7, 9): "symbolic", (10, 11): "rule_based",
}

# 标准身高体重曲线（每阶段末值）
GROWTH_CURVE = [
    (0, 54, 4.0), (1, 62, 5.8), (2, 68, 7.5), (3, 72, 8.5),
    (4, 76, 9.5), (5, 82, 10.5), (6, 87, 12.0), (7, 95, 14.0),
    (8, 102, 16.0), (9, 108, 18.0), (10, 115, 20.0), (11, 121, 22.0),
]

# 出牙时间线
TEETH_BY_PHASE = {
    3: 2, 4: 4, 5: 8, 6: 12, 7: 16, 8: 20, 9: 20, 10: 20, 11: 20,
}

# 情绪词汇渐进解锁
EMOTIONAL_VOCAB_BY_PHASE = {
    5: ["no", "scared"],
    6: ["no", "scared", "want", "mine"],
    7: ["angry", "sad", "happy", "why"],
    8: ["angry_because", "sorry", "friend", "fair"],
    9: ["frustrated", "proud", "embarrassed", "if_then"],
    10: ["worried", "excited", "disappointed", "jealous"],
    11: ["grateful", "lonely", "confused", "determined"],
}


def _update_phase_state(state: BabyState, phase_index: int) -> list[dict]:
    """
    阶段开始时自动更新喂养/睡眠/情绪/体格状态。
    返回变更事件列表（用于 SSE 推送）。纯规则引擎，0 LLM。
    """
    changes = []
    ns = state.nutrition_sleep
    em = state.emotional
    ph = state.physical

    # 0. 阶段自动标签（world.py 定义，此处应用）
    from world import PHASE_AUTO_TAGS
    auto_tags = PHASE_AUTO_TAGS.get(phase_index, set())
    for tag in auto_tags:
        if tag not in state.life_tags:
            state.life_tags.add(tag)
            changes.append({"type": "life_tag_added", "tag": tag})

    # 1. 喂养模式（按 age_days 判断，不依赖 phase_index）
    for age_lo, age_hi, mode in FEEDING_MODE_BY_AGE:
        if age_lo <= state.age_days < age_hi and ns.feeding_mode != mode:
            old = ns.feeding_mode
            ns.feeding_mode = mode
            changes.append({"type": "feeding_transition", "from": old, "to": mode})

    # 2. 夜醒次数
    base_waking = NIGHT_WAKING_BY_PHASE.get(phase_index, 0)
    if ns.sleep_regression_active:
        base_waking += 2
    ns.night_waking_frequency = base_waking

    # 3. 睡眠回归
    if phase_index in SLEEP_REGRESSION_PHASES:
        if random.random() < 0.8:
            ns.sleep_regression_active = True
            ns.sleep_quality = max(0.2, ns.sleep_quality - 0.3)
            changes.append({"type": "sleep_regression_onset"})
    else:
        if ns.sleep_regression_active:
            ns.sleep_regression_active = False
            ns.sleep_quality = min(0.9, ns.sleep_quality + 0.2)
            changes.append({"type": "sleep_regression_resolved"})

    # 4. Tantrum 频率
    em.tantrum_frequency = TANTRUM_FREQUENCY.get(phase_index, 0.0)

    # 5. 共情等级
    for (lo, hi), level in EMPATHY_BY_PHASE.items():
        if lo <= phase_index <= hi:
            em.empathy_level = level

    # 6. 游戏类型
    for (lo, hi), ptype in PLAY_TYPE_BY_PHASE.items():
        if lo <= phase_index <= hi:
            em.play_type = ptype

    # 7. 体格更新
    for p, h, w in GROWTH_CURVE:
        if p == phase_index:
            # 身高、体重独立方差（真实婴儿 ~10-15% 个体差异）
            h_var = random.gauss(0, 0.10)
            w_var = random.gauss(0, 0.10)
            ph.height_cm = round(h * (1 + h_var), 1)
            ph.weight_kg = round(w * (1 + w_var), 1)
            changes.append({
                "type": "physical_growth",
                "height_cm": ph.height_cm,
                "weight_kg": ph.weight_kg,
            })

    # 8. 出牙
    expected_teeth = TEETH_BY_PHASE.get(phase_index, ph.teeth_count)
    if expected_teeth > ph.teeth_count:
        new_teeth = expected_teeth - ph.teeth_count
        ph.teeth_count = expected_teeth
        changes.append({"type": "new_teeth", "count": new_teeth, "total": ph.teeth_count})

    # 9. 情绪词汇
    new_vocab = EMOTIONAL_VOCAB_BY_PHASE.get(phase_index, [])
    for word in new_vocab:
        if word not in em.emotional_vocabulary:
            em.emotional_vocabulary.append(word)

    # 10. 精细运动等级（随阶段渐进）
    expected_motor = min(phase_index // 2, 5)  # 0→0, 2→1, 4→2, 6→3, 8→4, 10→5
    if expected_motor > ph.fine_motor_level:
        ph.fine_motor_level = expected_motor
        changes.append({"type": "fine_motor_advance", "level": ph.fine_motor_level})

    # 11. 自我调节能力（随共情和阶段渐进）
    expected_reg = min(phase_index / 11.0, 1.0)  # 线性 0→1
    if expected_reg > em.self_regulation_score:
        em.self_regulation_score = round(expected_reg, 2)

    # 12. 过渡客体（phase 2-4 有概率产生，如安抚巾、玩偶）
    if 2 <= phase_index <= 4 and not ns.transitional_object:
        if random.random() < 0.4:
            objects = ["小毯子", "布偶熊", "安抚奶嘴", "小枕头", "毛绒兔"]
            ns.transitional_object = random.choice(objects)
            changes.append({"type": "transitional_object", "object": ns.transitional_object})

    # 13. 想象伙伴（phase 8-9 有概率产生）
    if 8 <= phase_index <= 9 and not em.imaginary_friend:
        if random.random() < 0.3:
            friends = ["Boo", "Mimi", "Captain Star", "小影子", "云朵先生"]
            em.imaginary_friend = random.choice(friends)
            changes.append({"type": "imaginary_friend", "name": em.imaginary_friend})

    return changes


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
    """[DEPRECATED] 同步版，内部消费生成器。主路径已由 scheduler DES 接管。"""
    result = None
    for step in simulate_phase_stream(state):
        if step.get("event") == "phase_simulated":
            result = step["_result"]
    if result is None:
        raise RuntimeError("simulate_phase_stream did not produce a final result")
    return result


def simulate_phase_stream(state: BabyState):
    """[DEPRECATED] 主路径已由 scheduler DES 接管，此函数仅保留供调试。

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
                age_range=phase.age_range(state.lang),
            ),
        }
        return

    result = PhaseResult(
        phase_index=phase_index,
        phase_name=phase.name,
        phase_display=phase.display_name,
        age_range=phase.age_range(state.lang),
    )

    # 阶段开始
    state.age_days = phase.age_days[1]
    state.expression_mode = phase.expression_mode

    yield {
        "event": "phase_start",
        "phase_index": phase.index,
        "phase_name": phase.name,
        "phase_display": phase.display_name,
        "age_range": phase.age_range(state.lang),
        "age_range_zh": phase.age_range_zh,
        "age_range_en": phase.age_range_en,
        "description": phase.description,
        "expression_mode": phase.expression_mode,
    }

    # 0. 阶段状态自动更新（喂养/睡眠/情绪/体格，纯规则）
    phase_state_changes = _update_phase_state(state, phase_index)
    if phase_state_changes:
        yield {
            "event": "phase_state_update",
            "changes": phase_state_changes,
        }

    # 1. 事件生成（身份调制权重 + 阶段状态调制）
    events = roll_events(phase_index, identity=state.identity, state=state)
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
            # 因果标签：保存状态快照（before）
            state_before = _snapshot_state(state)

            # 更新状态 —— 记忆通过 memory.record_moment 统一写入（jsonl 真相源 + 降级回写）
            if "memory" in scene:
                from memory import record_moment as _record_moment
                _primary_event = scene.get("event_names", ["unknown"])[0] if scene.get("event_names") else "unknown"
                _record_moment(
                    state, state.baby_id,
                    actor="world", target="self",
                    trigger=_primary_event,
                    action=scene.get("trigger", "") or scene.get("nanny_observation", ""),
                    response=scene.get("baby_reaction", ""),
                    outcome="neutral",
                    valence=scene.get("emotional_valence", "neutral"),
                    intensity=float(scene.get("intensity", 0.5)),
                    cause_tags=scene.get("cause_tags", []) or [],
                    effect_tags=[],   # effect_tags 稍后由 state diff 生成（已在原代码后段）
                    _legacy_memory_override=scene["memory"],  # 保留 LLM trace 原文
                )
            if scene.get("new_fear"):
                fear = scene["new_fear"]
                if fear not in state.fears:
                    state.fears.append(fear)
            if scene.get("new_preference"):
                pref = scene["new_preference"]
                if pref not in state.preferences:
                    state.preferences.append(pref)
            # 叙事收割：life_tag_hint → state.life_tags
            tag_hint = scene.get("life_tag_hint")
            if tag_hint and isinstance(tag_hint, str) and len(state.life_tags) < 50:
                state.life_tags.add(tag_hint)

            # 压力更新（每个场景后）
            _update_stress(
                state,
                scene.get("emotional_valence", "neutral"),
                scene.get("intensity", 0.5),
                scene.get("parent_involved", False),
            )

            # 因果标签：生成 effect_tags（状态快照 after）
            state_after = _snapshot_state(state)
            event_data = {
                "sensory_channels": [],
                "intensity": scene.get("intensity", 0.5),
                "category": "daily",
            }
            effect_tags = generate_effect_tags(
                event_data, scene, state_before, state_after,
            )

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
                "cause_tags": scene.get("cause_tags", []),
                "effect_tags": effect_tags,
                "stress_level": round(state.stress.stress_level, 2),
            }

        # 叙事完成后：检查回退和恢复
        regressed = _check_stress_regression(state)
        if regressed:
            yield {
                "event": "stress_regression",
                "regressed": regressed,
                "stress_level": round(state.stress.stress_level, 2),
            }
        recovered = _check_regression_recovery(state)
        if recovered:
            yield {
                "event": "regression_recovery",
                "recovered": [r["capability"] for r in recovered],
                "strengthened": [r["capability"] for r in recovered if r["strengthened"]],
                "stress_level": round(state.stress.stress_level, 2),
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
    caregiver_id: str = "primary_parent",
) -> dict:
    """
    照护者介入处理关键事件。

    event_name: 事件名
    parent_action: 照护者选择的行为
    parent_input: 自由输入（如命名时的名字）
    caregiver_id: 介入的照护者 ID
    """
    event = get_event(event_name)
    if not event:
        return {"error": f"Unknown event: {event_name}"}

    # 特殊处理：命名（设置名字，但不跳过照护者/依恋更新流程）
    if event_name == "naming_ceremony" and parent_input:
        state.name = parent_input

    # 因果标签：保存状态快照（before）
    state_before = _snapshot_state(state)

    # 处理关键事件（命名也走 LLM 生成反应 + 照护者更新）
    reaction = process_critical_event(state, event, parent_action)

    # 更新状态 —— 关键事件记忆通过 memory.record_moment 统一写入
    if "memory" in reaction:
        from memory import record_moment as _record_moment
        _caregiver_involved = bool(parent_action)
        _actor = "caregiver:parent" if _caregiver_involved else "world"
        _record_moment(
            state, state.baby_id,
            actor=_actor, target="self",
            trigger=event.name,
            action=event.description,
            response=reaction.get("reaction", ""),
            outcome="responded" if _caregiver_involved else "neutral",
            valence=reaction.get("emotional_valence", "neutral"),
            intensity=float(reaction.get("intensity", 0.5)),
            cause_tags=reaction.get("cause_tags", []) or [],
            effect_tags=[],
            _legacy_memory_override=reaction["memory"],
        )
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
        _update_attachment(state, parent_action, reaction.get("attachment_signal", ""),
                           caregiver_id=caregiver_id)

    # 更新照护者画像
    _update_caregiver_profile(state, parent_action, caregiver_id=caregiver_id)

    # 压力更新（关键事件后）
    valence = reaction.get("emotional_valence", "neutral")
    intensity = reaction.get("intensity", 0.5)
    _update_stress(state, valence, intensity, parent_present=True)

    # 决策标签效果（world.py 定义，此处应用）
    from world import DECISION_TAG_EFFECTS
    tag_effect = DECISION_TAG_EFFECTS.get((event_name, parent_action))
    if tag_effect:
        for tag in tag_effect.get("add", set()):
            state.life_tags.add(tag)
        for tag in tag_effect.get("remove", set()):
            state.life_tags.discard(tag)

    # 如厕训练成功：设置 toilet_trained
    if event_name == "toilet_training" and parent_action in ("patient_encourage", "strict_schedule"):
        state.physical.toilet_trained = True

    # 分房：设置 room_separated
    if event_name == "room_separation" and parent_action == "separate":
        state.nutrition_sleep.room_separated = True

    # 入园：自动添加 teacher 照护者
    if event_name == "kindergarten_entry" and "teacher" not in state.caregivers:
        from .state import CaregiverProfile
        state.caregivers["teacher"] = CaregiverProfile(
            caregiver_id="teacher",
            role="teacher",
            display_name="Teacher",
            responsiveness=0.6,
            intervention_style="balanced",
            emotional_tone="warm",
        )
        state.attachment_per_caregiver["teacher"] = "forming"

    # 因果标签：生成 effect_tags（状态快照 after）
    state_after = _snapshot_state(state)
    event_data = {
        "sensory_channels": event.sensory_channels,
        "intensity": event.intensity,
        "category": event.category,
    }
    effect_tags = generate_effect_tags(event_data, reaction, state_before, state_after)
    reaction["effect_tags"] = effect_tags

    save_state(state)

    return {k: v for k, v in reaction.items() if k != "memory"}


def _update_attachment(state: BabyState, parent_action: str, signal: str,
                       caregiver_id: str = "primary_parent") -> None:
    """根据照护者行为更新依恋类型趋势（按照护者独立追踪）。"""
    responsive_actions = {"comfort", "hold_and_rock", "hold_tight", "sing",
                          "celebrate", "validate", "explain_return", "calm_check",
                          "rush_hospital", "observe_carefully", "patient_encourage",
                          "stay_briefly", "quick_goodbye", "stay_safe", "hold_gently",
                          "curious", "play_along", "gradual_transition"}
    avoidant_actions = {"let_cry", "ignore", "sneak_away", "worried"}
    balanced_actions = {"encourage", "gentle_smile", "boundary", "stay_nearby",
                        "gradual", "negotiate", "observe", "discuss_why",
                        "remove_food", "wait_readiness", "delay", "try_wake"}

    # 按照护者更新依恋（双向状态转移）
    current = state.attachment_per_caregiver.get(caregiver_id, "forming")
    if parent_action in responsive_actions:
        # 持续回应：forming/anxious → secure，secure 保持
        if current in ("forming", "anxious"):
            current = "secure"
    elif parent_action in avoidant_actions:
        # 忽视/回避：forming → avoidant, secure → anxious, anxious → avoidant
        if current == "forming":
            current = "avoidant"
        elif current == "secure":
            current = "anxious"
        elif current == "anxious":
            current = "avoidant"
    elif parent_action in balanced_actions:
        # 平衡回应：forming → secure，anxious → forming（缓慢恢复）
        if current == "forming":
            current = "secure"
        elif current == "anxious":
            current = "forming"
    state.attachment_per_caregiver[caregiver_id] = current

    # 同步主照护者依恋到 state.attachment_style（显式查找 primary_parent）
    if "primary_parent" in state.attachment_per_caregiver:
        state.attachment_style = state.attachment_per_caregiver["primary_parent"]
    elif state.caregivers:
        # 没有 primary_parent 时回退到第一个照护者
        first_cid = next(iter(state.caregivers))
        state.attachment_style = state.attachment_per_caregiver.get(first_cid, "forming")


def _update_caregiver_profile(state: BabyState, action: str,
                              caregiver_id: str = "primary_parent") -> None:
    """更新照护者画像。"""
    # 确保照护者存在
    if caregiver_id not in state.caregivers:
        from .state import CaregiverProfile
        state.caregivers[caregiver_id] = CaregiverProfile(
            caregiver_id=caregiver_id,
        )

    cg = state.caregivers[caregiver_id]
    cg.total_interventions += 1
    cg.intervention_log.append({
        "phase": state.current_phase,
        "age_days": state.age_days,
        "action": action,
    })

    # 响应性
    responsive = {"comfort", "hold_and_rock", "hold_tight", "sing", "celebrate",
                  "validate", "rush_over", "explain_return", "rush_hospital",
                  "patient_encourage", "stay_briefly", "stay_safe", "hold_gently",
                  "curious", "play_along", "gradual_transition"}
    if action in responsive:
        cg.responsiveness = min(1.0, cg.responsiveness + 0.05)
    elif action in {"let_cry", "ignore", "sneak_away", "worried"}:
        cg.responsiveness = max(0.0, cg.responsiveness - 0.05)

    # 介入风格
    protective = {"rush_over", "comfort", "hold_tight", "insist", "rush_hospital"}
    hands_off = {"let_cry", "ignore", "observe", "wait_readiness", "delay"}
    if action in protective:
        cg.intervention_style = "protective"
    elif action in hands_off:
        cg.intervention_style = "hands_off"
    else:
        cg.intervention_style = "balanced"


def complete_phase(state: BabyState) -> dict:
    """
    完成当前阶段，生成总结，推进到下一阶段。
    """
    # 阶段末压力自然衰减
    _natural_stress_decay(state)

    # 生成阶段总结
    summary = generate_phase_summary(state)

    # 应用总结中的更新（同步 attachment_per_caregiver 保持一致）
    if isinstance(summary, dict):
        if summary.get("attachment_update"):
            att = summary["attachment_update"]
            if att in ("secure", "anxious", "avoidant"):
                state.attachment_style = att
                # 同步主照护者的 per-caregiver 记录
                if "primary_parent" in state.attachment_per_caregiver:
                    state.attachment_per_caregiver["primary_parent"] = att
                elif state.attachment_per_caregiver:
                    first_cid = next(iter(state.attachment_per_caregiver))
                    state.attachment_per_caregiver[first_cid] = att

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

    # 阶段转换时更新声音画像（先天基准 + 后天经历 → 稳定的说话风格）
    _update_voice_profile(state)

    save_state(state)

    return summary


def _update_voice_profile(state: BabyState) -> None:
    """
    从先天身份 + 后天积累的经历/状态重新计算声音画像。

    只在阶段转换时调用，保证同一阶段内人格稳定。
    """
    parts = []
    identity = state.identity
    sp = identity.sensory_profile

    # ── 先天基准（不变的底色）──
    if sp.dominant:
        parts.append(f"Innate dominant sense: {sp.dominant}")
    if identity.arousal_baseline == "high":
        parts.append("Innate high arousal: baseline tendency toward fast, loud, intense")
    elif identity.arousal_baseline == "low":
        parts.append("Innate low arousal: baseline tendency toward slow, quiet, deliberate")
    if identity.temperament:
        parts.append(f"Temperament seed: {identity.temperament[:120]}")

    # ── 后天塑造（阶段累积）──
    phase = PHASES[state.current_phase] if state.current_phase < len(PHASES) else None
    if phase:
        parts.append(f"Expression mode: {phase.expression_mode}")

    if state.attachment_style and state.attachment_style != "forming":
        parts.append(f"Attachment (formed through experience): {state.attachment_style}")

    if state.preferences:
        parts.append(f"Known preferences: {', '.join(state.preferences[-5:])}")
    if state.fears:
        parts.append(f"Known fears: {', '.join(state.fears[-5:])}")
    if state.comfort_sources:
        parts.append(f"Comfort sources: {', '.join(state.comfort_sources[-3:])}")

    # 从记忆中提炼反复出现的发育线索
    traces = {}
    for m in state.memories[-20:]:
        t = getattr(m, "trace", "")
        if t:
            traces[t] = traces.get(t, 0) + 1
    recurring = [t for t, count in traces.items() if count >= 2]
    if recurring:
        parts.append(f"Recurring developmental traits: {', '.join(recurring[:3])}")

    if state.emotional and state.emotional.emotional_vocabulary:
        parts.append(f"Emotional vocabulary: {', '.join(state.emotional.emotional_vocabulary[:5])}")

    state.voice_profile = "\n".join(f"- {p}" for p in parts)


def grow_stream(state: BabyState):
    """[DEPRECATED] 主路径已由 scheduler DES 接管。

    手动成长流（备用路径）：连续推进所有阶段，关键事件时暂停。

    注意：主路径已由 scheduler 自驱动阶段推进接管。
    此函数保留用于手动触发/调试。

    事件流 = 多个阶段的 simulate_phase_stream + complete_phase 交织：
    - 每个阶段的全部事件（phase_start → ... → phase_simulated）
    - 如果无关键事件 → 自动 complete（LLM 总结）→ 进入下一阶段
    - 如果有关键事件 → yield paused，结束流。等父母 intervene 后重新调用。
    - 最后一个阶段完成后 yield growth_complete
    """
    # 如果有未处理的关键事件或阶段推进中，拒绝手动运行
    active_criticals = [c for c in state.pending_criticals if c.get("awaiting_parent")]
    if active_criticals:
        yield {
            "event": "paused",
            "phase_index": state.current_phase,
            "reason": "pending_criticals",
            "pending_criticals": state.pending_criticals,
            "message": "Growth paused — critical events require parent intervention.",
        }
        return
    if state.phase_advancing:
        yield {
            "event": "error",
            "message": "Autonomous phase transition in progress.",
        }
        return
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

        # 心跳注入：阶段模拟完成后，评估宝宝是否要主动找父母
        if not has_critical:
            try:
                from heartbeat import evaluate_heartbeat
                from .heartbeat_provider import CradleMonologueProvider
                from .mind import generate_heartbeat_evaluation, generate_ignored_reaction
                _provider = CradleMonologueProvider()
                _hb = evaluate_heartbeat(
                    state, _provider, state.initiative,
                    generate_heartbeat_evaluation, generate_ignored_reaction,
                )
                if _hb.get("initiative"):
                    yield {"event": "heartbeat_initiative", **_hb["initiative"]}
                if _hb.get("ignored_reaction"):
                    yield {"event": "heartbeat_ignored", **_hb["ignored_reaction"]}
            except Exception as _hb_err:
                logger.warning("Heartbeat in grow_stream failed: %s", _hb_err)

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

        # 无关键事件 → 自动完成阶段（LLM 总结 + 计时心跳）
        yield {
            "event": "phase_completing",
            "phase_index": state.current_phase,
            "phase_display": phase.display_name,
            "message": "Generating phase developmental summary...",
        }

        import time as _time
        _completing_phase_index = state.current_phase  # 捕获当前值，防线程修改后数据不自洽
        _summary_executor = ThreadPoolExecutor(max_workers=1)
        _summary_future = _summary_executor.submit(complete_phase, state)
        _summary_elapsed = 0
        summary = None
        try:
            while not _summary_future.done():
                _time.sleep(1)
                _summary_elapsed += 1
                yield {
                    "event": "phase_completing",
                    "phase_index": _completing_phase_index,
                    "phase_display": phase.display_name,
                    "elapsed": _summary_elapsed,
                }
                if _summary_elapsed > LLM_TIMEOUT:
                    _summary_future.cancel()
                    break
            if _summary_future.done():
                summary = _summary_future.result()
        except Exception as e:
            logger.error("Phase summary LLM error: %s", e)
        finally:
            _summary_executor.shutdown(wait=False)
        if summary is None:
            summary = {"summary": "Phase summary unavailable."}

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
