"""
婴儿成长状态模型。

这是摇篮中婴儿的活档案——从出生到进入世界，所有成长轨迹都记录在这里。
状态持久化到 backend/babies/{baby_id}/ 目录。

[INPUT]: 依赖 cradle/phases.py 的阶段定义
[OUTPUT]: BabyState(含 InitiativeState + 自驱动生命字段 + triggered_events/world_snapshot), CaregiverProfile, StressState, NutritionSleepState, EmotionalState, PhysicalState 数据类（Memory 含 forget_score 字段，memory/consolidation 动态更新），load/save/append_event(返回seq)/load_events_after/get_notify/get_baby_lock/rebuild_triggered_events 函数
[POS]: cradle/ 的状态管理层，被所有其他 cradle 模块消费
[PROTOCOL]: 变更时更新此头部，然后检查 CLAUDE.md
"""

from __future__ import annotations

import asyncio
import json
import os
import re
import tempfile
import threading
from dataclasses import dataclass, field
from heartbeat import InitiativeState
from pathlib import Path
from typing import Optional

ARCHIVE_DIR = Path(__file__).parent.parent / "archive"


# ============================================================
# 事件日志基础设施：seq 计数器 + 写入锁 + 通知 + 状态锁
# ============================================================

_seq_counters: dict[str, int] = {}           # baby_id -> 当前最大 seq
_seq_locks: dict[str, threading.Lock] = {}   # baby_id -> 事件写入锁
_notify_events: dict[str, asyncio.Event] = {}  # baby_id -> SSE 通知信号
_baby_locks: dict[str, asyncio.Lock] = {}    # baby_id -> 状态读写锁（scheduler/interact 互斥）
_infra_lock = threading.Lock()               # 保护上面四个 dict 的惰性创建


def _get_seq_lock(baby_id: str) -> threading.Lock:
    """获取 baby 的事件写入锁（惰性创建）。"""
    with _infra_lock:
        if baby_id not in _seq_locks:
            _seq_locks[baby_id] = threading.Lock()
        return _seq_locks[baby_id]


def _count_lines(path: Path) -> int:
    """计算文件行数（用于冷启动时推断 seq）。"""
    if not path.is_file():
        return 0
    count = 0
    with open(path, "r", encoding="utf-8") as f:
        for _ in f:
            count += 1
    return count


def _next_seq(baby_id: str) -> int:
    """分配下一个 seq（必须在 _get_seq_lock 内调用）。"""
    if baby_id not in _seq_counters:
        path = _baby_dir(baby_id) / "events.jsonl"
        _seq_counters[baby_id] = _count_lines(path)
    _seq_counters[baby_id] += 1
    return _seq_counters[baby_id]


def get_notify(baby_id: str) -> asyncio.Event:
    """获取 baby 的 SSE 通知信号（惰性创建）。"""
    with _infra_lock:
        if baby_id not in _notify_events:
            _notify_events[baby_id] = asyncio.Event()
        return _notify_events[baby_id]


def get_baby_lock(baby_id: str) -> asyncio.Lock:
    """获取 baby 的状态锁（scheduler 和 interact 互斥）。"""
    with _infra_lock:
        if baby_id not in _baby_locks:
            _baby_locks[baby_id] = asyncio.Lock()
        return _baby_locks[baby_id]


@dataclass
class SensoryProfile:
    """感官画像，从 gestation_log 编译。0.0-1.0 强度。"""
    hearing: float = 0.5
    vision: float = 0.5
    touch: float = 0.5
    smell: float = 0.5
    proprioception: float = 0.5
    # 主导感官（从 gestation_log 的 primary_sense 推断）
    dominant: str = ""
    # 薄弱感官
    weak: str = ""

    def to_dict(self) -> dict:
        return {
            "hearing": self.hearing, "vision": self.vision,
            "touch": self.touch, "smell": self.smell,
            "proprioception": self.proprioception,
            "dominant": self.dominant, "weak": self.weak,
        }


@dataclass
class Identity:
    """从 gestation_log 编译出来的身份约束。出生即锁定，不可修改。"""
    sensory_profile: SensoryProfile = field(default_factory=SensoryProfile)
    arousal_baseline: str = "moderate"      # low / moderate / high
    reflex_patterns: list[dict] = field(default_factory=list)
    instinct_loops: list[dict] = field(default_factory=list)
    temperament: str = ""
    tendencies: list[str] = field(default_factory=list)
    defects: list[str] = field(default_factory=list)
    # 编译出的行为约束（自然语言规则列表）
    constraints: list[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "sensory_profile": {
                "hearing": self.sensory_profile.hearing,
                "vision": self.sensory_profile.vision,
                "touch": self.sensory_profile.touch,
                "smell": self.sensory_profile.smell,
                "proprioception": self.sensory_profile.proprioception,
                "dominant": self.sensory_profile.dominant,
                "weak": self.sensory_profile.weak,
            },
            "arousal_baseline": self.arousal_baseline,
            "reflex_patterns": self.reflex_patterns,
            "instinct_loops": self.instinct_loops,
            "temperament": self.temperament,
            "tendencies": self.tendencies,
            "defects": self.defects,
            "constraints": self.constraints,
        }

    @classmethod
    def from_dict(cls, d: dict) -> Identity:
        sp = d.get("sensory_profile", {})
        return cls(
            sensory_profile=SensoryProfile(
                hearing=sp.get("hearing", 0.5),
                vision=sp.get("vision", 0.5),
                touch=sp.get("touch", 0.5),
                smell=sp.get("smell", 0.5),
                proprioception=sp.get("proprioception", 0.5),
                dominant=sp.get("dominant", ""),
                weak=sp.get("weak", ""),
            ),
            arousal_baseline=d.get("arousal_baseline", "moderate"),
            reflex_patterns=d.get("reflex_patterns", []),
            instinct_loops=d.get("instinct_loops", []),
            temperament=d.get("temperament", ""),
            tendencies=d.get("tendencies", []),
            defects=d.get("defects", []),
            constraints=d.get("constraints", []),
        )


@dataclass
class CaregiverProfile:
    """照护者画像，从介入行为中追踪。每个照护者独立影响依恋类型。"""
    caregiver_id: str = "primary_parent"
    role: str = "parent"                # parent / grandparent / nanny / teacher
    display_name: str = "Parent"
    responsiveness: float = 0.5         # 0-1，呼唤时是否回应
    intervention_style: str = "balanced"  # protective / balanced / hands_off
    teaching_frequency: float = 0.5     # 0-1，多久主动教导
    emotional_tone: str = "warm"        # warm / neutral / anxious / strict
    total_interventions: int = 0
    interaction_count: int = 0          # 对话次数
    intervention_log: list[dict] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "caregiver_id": self.caregiver_id,
            "role": self.role,
            "display_name": self.display_name,
            "responsiveness": self.responsiveness,
            "intervention_style": self.intervention_style,
            "teaching_frequency": self.teaching_frequency,
            "emotional_tone": self.emotional_tone,
            "total_interventions": self.total_interventions,
            "interaction_count": self.interaction_count,
            "intervention_log": self.intervention_log[-20:],
        }

    @classmethod
    def from_dict(cls, d: dict) -> CaregiverProfile:
        return cls(
            caregiver_id=d.get("caregiver_id", "primary_parent"),
            role=d.get("role", "parent"),
            display_name=d.get("display_name", "Parent"),
            responsiveness=d.get("responsiveness", 0.5),
            intervention_style=d.get("intervention_style", "balanced"),
            teaching_frequency=d.get("teaching_frequency", 0.5),
            emotional_tone=d.get("emotional_tone", "warm"),
            total_interventions=d.get("total_interventions", 0),
            interaction_count=d.get("interaction_count", 0),
            intervention_log=d.get("intervention_log", []),
        )


@dataclass
class StressState:
    """压力与回退状态。"""
    stress_level: float = 0.0           # 0.0-1.0，当前压力值
    regressed_capabilities: list[dict] = field(default_factory=list)
    # 每项: {"capability": str, "regressed_at": int, "original_phase": int}
    resilience_bonus: list[str] = field(default_factory=list)
    # 从回退中恢复后获得韧性加成的能力

    def to_dict(self) -> dict:
        return {
            "stress_level": self.stress_level,
            "regressed_capabilities": self.regressed_capabilities,
            "resilience_bonus": self.resilience_bonus,
        }

    @classmethod
    def from_dict(cls, d: dict) -> StressState:
        return cls(
            stress_level=d.get("stress_level", 0.0),
            regressed_capabilities=d.get("regressed_capabilities", []),
            resilience_bonus=d.get("resilience_bonus", []),
        )


@dataclass
class NutritionSleepState:
    """喂养与睡眠状态。"""
    feeding_mode: str = "breast_milk"
    # breast_milk / introducing_solids / self_feeding_learning / family_meals
    food_allergies: list[str] = field(default_factory=list)
    picky_foods: list[str] = field(default_factory=list)
    sleep_quality: float = 0.7          # 0-1，当前睡眠质量
    sleep_regression_active: bool = False
    night_waking_frequency: int = 3     # 每夜平均醒来次数
    room_separated: bool = False
    transitional_object: str = ""       # 过渡客体名称
    # 生理时钟（sim_time 小时）
    last_fed_time: float = 0.0          # 上次喂奶 sim_time
    last_diaper_time: float = 0.0       # 上次换尿布 sim_time
    last_sleep_time: float = 0.0        # 上次入睡 sim_time
    comfort_temp: str = "comfortable"   # comfortable / too_hot / too_cold

    def to_dict(self) -> dict:
        return {
            "feeding_mode": self.feeding_mode,
            "food_allergies": self.food_allergies,
            "picky_foods": self.picky_foods,
            "sleep_quality": self.sleep_quality,
            "sleep_regression_active": self.sleep_regression_active,
            "night_waking_frequency": self.night_waking_frequency,
            "room_separated": self.room_separated,
            "transitional_object": self.transitional_object,
            "last_fed_time": self.last_fed_time,
            "last_diaper_time": self.last_diaper_time,
            "last_sleep_time": self.last_sleep_time,
            "comfort_temp": self.comfort_temp,
        }

    @classmethod
    def from_dict(cls, d: dict) -> NutritionSleepState:
        return cls(
            feeding_mode=d.get("feeding_mode", "breast_milk"),
            food_allergies=d.get("food_allergies", []),
            picky_foods=d.get("picky_foods", []),
            sleep_quality=d.get("sleep_quality", 0.7),
            sleep_regression_active=d.get("sleep_regression_active", False),
            night_waking_frequency=d.get("night_waking_frequency", 3),
            room_separated=d.get("room_separated", False),
            transitional_object=d.get("transitional_object", ""),
            last_fed_time=d.get("last_fed_time", 0.0),
            last_diaper_time=d.get("last_diaper_time", 0.0),
            last_sleep_time=d.get("last_sleep_time", 0.0),
            comfort_temp=d.get("comfort_temp", "comfortable"),
        )


@dataclass
class EmotionalState:
    """情绪调节状态。"""
    tantrum_frequency: float = 0.0      # 当前阶段发脾气概率
    emotional_vocabulary: list[str] = field(default_factory=list)
    # 已掌握的情绪词汇: ["cry", "no", "angry", "sad", "angry_because"]
    empathy_level: str = "none"         # none / contagion / primitive / true
    self_regulation_score: float = 0.0  # 0-1，自我调节能力
    imaginary_friend: str = ""          # 想象伙伴名称（空=无）
    play_type: str = "functional"       # functional / constructive / symbolic / rule_based

    def to_dict(self) -> dict:
        return {
            "tantrum_frequency": self.tantrum_frequency,
            "emotional_vocabulary": self.emotional_vocabulary,
            "empathy_level": self.empathy_level,
            "self_regulation_score": self.self_regulation_score,
            "imaginary_friend": self.imaginary_friend,
            "play_type": self.play_type,
        }

    @classmethod
    def from_dict(cls, d: dict) -> EmotionalState:
        return cls(
            tantrum_frequency=d.get("tantrum_frequency", 0.0),
            emotional_vocabulary=d.get("emotional_vocabulary", []),
            empathy_level=d.get("empathy_level", "none"),
            self_regulation_score=d.get("self_regulation_score", 0.0),
            imaginary_friend=d.get("imaginary_friend", ""),
            play_type=d.get("play_type", "functional"),
        )


@dataclass
class PhysicalState:
    """体格状态。"""
    height_cm: float = 50.0            # 出生身高
    weight_kg: float = 3.3             # 出生体重
    teeth_count: int = 0               # 已萌出牙齿数
    toilet_trained: bool = False
    fine_motor_level: int = 0          # 0-5，精细运动等级

    def to_dict(self) -> dict:
        return {
            "height_cm": round(self.height_cm, 1),
            "weight_kg": round(self.weight_kg, 1),
            "teeth_count": self.teeth_count,
            "toilet_trained": self.toilet_trained,
            "fine_motor_level": self.fine_motor_level,
        }

    @classmethod
    def from_dict(cls, d: dict) -> PhysicalState:
        return cls(
            height_cm=d.get("height_cm", 50.0),
            weight_kg=d.get("weight_kg", 3.3),
            teeth_count=d.get("teeth_count", 0),
            toilet_trained=d.get("toilet_trained", False),
            fine_motor_level=d.get("fine_motor_level", 0),
        )


@dataclass
class Memory:
    """一条经验记忆。"""
    phase: int                          # 哪个阶段
    age_days: int                       # 发生时的日龄
    event: str                          # 事件名
    stimulus: str                       # 刺激描述
    reaction: str                       # 婴儿反应
    trace: str                          # 追溯到哪条先天约束
    emotional_valence: str              # positive / negative / neutral
    intensity: float                    # 0-1，经验强度
    parent_involved: bool = False       # 父母是否介入
    parent_action: str = ""             # 父母做了什么
    growth_signal: str = ""             # 成长信号（如有）
    forget_score: float = 1.0           # 遗忘分（memory/consolidation 动态更新，老 baby 默认 1.0）

    def to_dict(self) -> dict:
        return {
            "phase": self.phase,
            "age_days": self.age_days,
            "event": self.event,
            "stimulus": self.stimulus,
            "reaction": self.reaction,
            "trace": self.trace,
            "emotional_valence": self.emotional_valence,
            "intensity": self.intensity,
            "parent_involved": self.parent_involved,
            "parent_action": self.parent_action,
            "growth_signal": self.growth_signal,
            "forget_score": self.forget_score,
        }

    @classmethod
    def from_dict(cls, d: dict) -> Memory:
        return cls(
            phase=d.get("phase", 0),
            age_days=d.get("age_days", 0),
            event=d.get("event", ""),
            stimulus=d.get("stimulus", ""),
            reaction=d.get("reaction", ""),
            trace=d.get("trace", ""),
            emotional_valence=d.get("emotional_valence", "neutral"),
            intensity=d.get("intensity", 0.5),
            parent_involved=d.get("parent_involved", False),
            parent_action=d.get("parent_action", ""),
            growth_signal=d.get("growth_signal", ""),
            forget_score=float(d.get("forget_score", 1.0)),  # 向后兼容：老 baby 无此字段
        )


@dataclass
class Milestone:
    """已达成的里程碑。"""
    name: str
    phase: int
    age_days: int
    trigger_event: str          # 触发事件
    description: str            # 具体表现

    def to_dict(self) -> dict:
        return {
            "name": self.name,
            "phase": self.phase,
            "age_days": self.age_days,
            "trigger_event": self.trigger_event,
            "description": self.description,
        }

    @classmethod
    def from_dict(cls, d: dict) -> Milestone:
        return cls(
            name=d.get("name", ""),
            phase=d.get("phase", 0),
            age_days=d.get("age_days", 0),
            trigger_event=d.get("trigger_event", ""),
            description=d.get("description", ""),
        )


@dataclass
class BabyState:
    """婴儿在摇篮中的完整状态。"""
    # 基本信息（从 Baby 数据复制）
    baby_id: str = ""
    species: str = "human"
    name: str = ""                      # 由父母命名，初始为空
    lang: str = "en"                    # 运行时语言 "zh" | "en"，创建后锁定，下游 LLM 生成按此切换

    # 出生地（从 Baby 数据复制，用于文化相关行为如命名）
    birthplace: dict = field(default_factory=dict)  # {name, code, region, ...}
    phenotype: dict = field(default_factory=dict)    # {race, ...}

    # 先天身份（出生即锁定）
    identity: Identity = field(default_factory=Identity)

    # 成长状态
    current_phase: int = 0              # 当前阶段索引
    age_days: int = 0                   # 当前日龄
    capabilities: list[str] = field(default_factory=list)  # 已解锁能力
    expression_mode: str = "cry_only"   # 当前表达模式

    # 心理状态（动态）
    attachment_style: str = "forming"   # secure / anxious / avoidant / forming
    fears: list[str] = field(default_factory=list)
    preferences: list[str] = field(default_factory=list)
    comfort_sources: list[str] = field(default_factory=list)

    # 记忆与里程碑
    memories: list[Memory] = field(default_factory=list)
    milestones: list[Milestone] = field(default_factory=list)

    # 照护者（多人，替代旧 parent_profile）
    caregivers: dict[str, CaregiverProfile] = field(default_factory=dict)
    attachment_per_caregiver: dict[str, str] = field(default_factory=dict)

    # 压力与回退
    stress: StressState = field(default_factory=StressState)

    # 喂养与睡眠
    nutrition_sleep: NutritionSleepState = field(default_factory=NutritionSleepState)

    # 情绪调节
    emotional: EmotionalState = field(default_factory=EmotionalState)

    # 体格
    physical: PhysicalState = field(default_factory=PhysicalState)

    # 阶段日志
    phase_summaries: list[dict] = field(default_factory=list)

    # 已模拟阶段（幂等性保护：防止断连重连时重复模拟）
    simulated_phases: list[int] = field(default_factory=list)

    # 世界就绪度
    world_readiness: dict = field(default_factory=dict)

    # 主动行为状态
    initiative: InitiativeState = field(default_factory=InitiativeState)

    # 自驱动生命
    life_tags: set[str] = field(default_factory=set)     # 生活上下文标签
    last_active_ts: float = 0.0                          # 上次活跃的 Unix 时间戳
    sim_time: float = 0.0                                # 当前模拟时间（自出生以来的模拟小时数）
    time_scale: str = "turbo"                            # slow / normal / fast / turbo

    # 自驱动阶段推进
    pending_criticals: list[dict] = field(default_factory=list)  # 待父母处理的关键事件队列（不阻塞生命推进）
    phase_advancing: bool = False            # 阶段推进中（防并发）

    # 对话声音画像（阶段转换时更新，先天基准 + 后天经历 → 说话风格）
    voice_profile: str = ""

    # 生成标记
    turbo_generated: bool = False        # True = turbo 模式快速生成，叙事贫乏

    # 世界上下文系统
    triggered_events: set[str] = field(default_factory=set)  # 全局已触发事件名（first_X/critical 去重）
    # world_snapshot: 运行时由 world.py 管理，持久化到 state.json
    # 类型注解用 Any 避免循环导入，实际类型为 world.WorldSnapshot | None
    world_snapshot: any = None

    def update_age_from_sim_time(self) -> None:
        """根据 sim_time 更新 age_days，不超过当前阶段上限。"""
        from .phases import PHASES
        sim_days = int(self.sim_time / 24.0)
        if self.current_phase < len(PHASES):
            max_days = PHASES[self.current_phase].age_days[1]
            self.age_days = min(sim_days, max_days)
        else:
            self.age_days = sim_days

    def to_dict(self) -> dict:
        return {
            "baby_id": self.baby_id,
            "species": self.species,
            "name": self.name,
            "lang": self.lang,
            "identity": self.identity.to_dict(),
            "current_phase": self.current_phase,
            "age_days": self.age_days,
            "capabilities": self.capabilities,
            "expression_mode": self.expression_mode,
            "attachment_style": self.attachment_style,
            "fears": self.fears,
            "preferences": self.preferences,
            "comfort_sources": self.comfort_sources,
            "memories": [m.to_dict() for m in self.memories],
            "milestones": [m.to_dict() for m in self.milestones],
            "caregivers": {cid: c.to_dict() for cid, c in self.caregivers.items()},
            "attachment_per_caregiver": self.attachment_per_caregiver,
            "stress": self.stress.to_dict(),
            "nutrition_sleep": self.nutrition_sleep.to_dict(),
            "emotional": self.emotional.to_dict(),
            "physical": self.physical.to_dict(),
            "phase_summaries": self.phase_summaries,
            "simulated_phases": self.simulated_phases,
            "world_readiness": self.world_readiness,
            "initiative": self.initiative.to_dict(),
            "life_tags": list(self.life_tags),
            "last_active_ts": self.last_active_ts,
            "sim_time": self.sim_time,
            "time_scale": self.time_scale,
            "pending_criticals": self.pending_criticals,
            "phase_advancing": self.phase_advancing,
            "voice_profile": self.voice_profile,
            "triggered_events": sorted(self.triggered_events),
            "birthplace": self.birthplace,
            "phenotype": self.phenotype,
            "world_snapshot": self.world_snapshot.to_dict() if self.world_snapshot and hasattr(self.world_snapshot, 'to_dict') else self.world_snapshot,
        }

    @classmethod
    def from_dict(cls, d: dict) -> BabyState:
        # 旧数据兼容：triggered_events 为空时从 memories/milestones 重建
        # （在构造完成后由 load_state 调用 rebuild_triggered_events）
        # 照护者：兼容旧 parent_profile 格式
        caregivers: dict[str, CaregiverProfile] = {}
        if "caregivers" in d and d["caregivers"]:
            for cid, cd in d["caregivers"].items():
                caregivers[cid] = CaregiverProfile.from_dict(cd)
        elif "parent_profile" in d:
            pp = d["parent_profile"]
            caregivers["primary_parent"] = CaregiverProfile(
                caregiver_id="primary_parent",
                role="parent",
                display_name="Parent",
                responsiveness=pp.get("responsiveness", 0.5),
                intervention_style=pp.get("intervention_style", "balanced"),
                teaching_frequency=pp.get("teaching_frequency", 0.5),
                emotional_tone=pp.get("emotional_tone", "warm"),
                total_interventions=pp.get("total_interventions", 0),
                interaction_count=pp.get("interaction_count", 0),
                intervention_log=pp.get("intervention_log", []),
            )
        # 兜底：老 archive 既无 caregivers 又无 parent_profile（admit 初始化缺陷
        # 2026-04-23 前残留），补一个默认 primary_parent，让图谱 emit 路径不崩。
        if not caregivers:
            caregivers["primary_parent"] = CaregiverProfile()

        attachment_per_caregiver = dict(d.get("attachment_per_caregiver", {}))
        for cid in caregivers:
            attachment_per_caregiver.setdefault(cid, "forming")

        return cls(
            baby_id=d.get("baby_id", ""),
            species=d.get("species", "human"),
            name=d.get("name", ""),
            lang=d.get("lang", "en"),
            identity=Identity.from_dict(d.get("identity", {})),
            current_phase=d.get("current_phase", 0),
            age_days=d.get("age_days", 0),
            capabilities=d.get("capabilities", []),
            expression_mode=d.get("expression_mode", "cry_only"),
            attachment_style=d.get("attachment_style", "forming"),
            fears=d.get("fears", []),
            preferences=d.get("preferences", []),
            comfort_sources=d.get("comfort_sources", []),
            memories=[Memory.from_dict(m) for m in d.get("memories", [])],
            milestones=[Milestone.from_dict(m) for m in d.get("milestones", [])],
            caregivers=caregivers,
            attachment_per_caregiver=attachment_per_caregiver,
            stress=StressState.from_dict(d.get("stress", {})),
            nutrition_sleep=NutritionSleepState.from_dict(d.get("nutrition_sleep", {})),
            emotional=EmotionalState.from_dict(d.get("emotional", {})),
            physical=PhysicalState.from_dict(d.get("physical", {})),
            phase_summaries=d.get("phase_summaries", []),
            simulated_phases=d.get("simulated_phases", []),
            world_readiness=d.get("world_readiness", {}),
            initiative=InitiativeState.from_dict(d.get("initiative", {})),
            life_tags=set(d.get("life_tags", [])),
            last_active_ts=d.get("last_active_ts", 0.0),
            birthplace=d.get("birthplace", {}),
            phenotype=d.get("phenotype", {}),
            sim_time=d.get("sim_time", 0.0),
            time_scale=d.get("time_scale", "normal"),
            pending_criticals=(
                d["pending_criticals"] if d.get("pending_criticals") is not None
                else ([d["pending_critical"]] if d.get("pending_critical") else [])
            ),
            voice_profile=d.get("voice_profile", ""),
            phase_advancing=d.get("phase_advancing", False),
            triggered_events=set(d.get("triggered_events", [])),
            world_snapshot=_restore_world_snapshot(d.get("world_snapshot")),
        )


def _restore_world_snapshot(raw: dict | None):
    """从 JSON dict 恢复 WorldSnapshot，延迟导入避免循环依赖。"""
    if raw is None:
        return None
    try:
        from world import snapshot_from_dict
        return snapshot_from_dict(raw)
    except Exception:
        return None


def rebuild_triggered_events(state: BabyState) -> None:
    """
    从 memories + milestones + life_moments 重建 triggered_events（旧数据兼容）。
    D1-3 双源遍历：V2 数据 + 旧数据都要扫，避免去重漏网。
    """
    if state.triggered_events:
        return  # 已有数据，不重建
    for m in state.memories:
        state.triggered_events.add(m.event)
    for ms in state.milestones:
        state.triggered_events.add(ms.name)
    # 双源：life_moments.jsonl（V2 真相源）
    try:
        from memory import load_life_moments
        if state.baby_id:
            for lm in load_life_moments(state.baby_id):
                if lm.trigger:
                    state.triggered_events.add(lm.trigger)
    except Exception:
        pass  # 新模块未就绪或读失败，不阻断加载


# ============================================================
# 持久化
# ============================================================

_SAFE_ID_RE = re.compile(r'^[a-zA-Z0-9_-]+$')


def _validate_baby_id(baby_id: str) -> str:
    """校验 baby_id，阻止路径遍历。只允许字母、数字、下划线、连字符。"""
    if not baby_id or not _SAFE_ID_RE.match(baby_id):
        raise ValueError(f"Invalid baby_id: {baby_id!r} (only [a-zA-Z0-9_-] allowed)")
    return baby_id


def _baby_dir(baby_id: str) -> Path:
    _validate_baby_id(baby_id)
    return ARCHIVE_DIR / baby_id


def save_state(state: BabyState) -> None:
    """保存婴儿成长状态。原子写入：先写临时文件再 rename，防并发损坏。"""
    d = _baby_dir(state.baby_id)
    d.mkdir(parents=True, exist_ok=True)
    path = d / "state.json"
    data = json.dumps(state.to_dict(), ensure_ascii=False, indent=2)
    fd, tmp_path = tempfile.mkstemp(dir=str(d), suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            f.write(data)
        os.replace(tmp_path, str(path))  # 原子替换
    except BaseException:
        # 写入失败时清理临时文件
        try:
            os.unlink(tmp_path)
        except OSError:
            pass
        raise


def load_state(baby_id: str) -> Optional[BabyState]:
    """加载婴儿成长状态。"""
    path = _baby_dir(baby_id) / "state.json"
    if not path.is_file():
        return None
    data = json.loads(path.read_text(encoding="utf-8"))
    state = BabyState.from_dict(data)
    # 旧数据兼容：triggered_events 为空时从 memories/milestones 重建
    rebuild_triggered_events(state)
    return state


def append_interaction(baby_id: str, record: dict) -> None:
    """追加一条亲子对话记录到 interactions.jsonl。"""
    import time as _time
    d = _baby_dir(baby_id)
    d.mkdir(parents=True, exist_ok=True)
    path = d / "interactions.jsonl"
    line = json.dumps({"ts": _time.time(), **record}, ensure_ascii=False)
    with open(path, "a", encoding="utf-8") as f:
        f.write(line + "\n")


def load_interactions(baby_id: str, limit: int = 5) -> list[dict]:
    """加载最近 N 条亲子对话记录。"""
    path = _baby_dir(baby_id) / "interactions.jsonl"
    if not path.is_file():
        return []
    records = []
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line:
            try:
                records.append(json.loads(line))
            except json.JSONDecodeError:
                continue
    return records[-limit:]


def append_event(baby_id: str, event: dict) -> int:
    """
    追加一条事件到 events.jsonl，分配单调递增 seq，触发 SSE 通知。

    返回分配的 seq 号。
    """
    import time as _time
    d = _baby_dir(baby_id)
    d.mkdir(parents=True, exist_ok=True)
    path = d / "events.jsonl"
    lock = _get_seq_lock(baby_id)
    with lock:
        seq = _next_seq(baby_id)
        line = json.dumps({"seq": seq, "ts": _time.time(), **event}, ensure_ascii=False)
        with open(path, "a", encoding="utf-8") as f:
            f.write(line + "\n")
    # 通知 SSE 读取器（非阻塞，Event 可能尚未创建）
    try:
        notify = get_notify(baby_id)
        notify.set()
    except Exception:
        pass  # 无事件循环时忽略
    return seq


def load_events(baby_id: str) -> list[dict]:
    """加载婴儿的所有历史 SSE 事件（含 seq，兼容旧数据）。"""
    path = _baby_dir(baby_id) / "events.jsonl"
    if not path.is_file():
        return []
    events = []
    line_num = 0
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        line_num += 1
        try:
            evt = json.loads(line)
            # 兼容旧数据：无 seq 字段时按行号补充
            if "seq" not in evt:
                evt["seq"] = line_num
            events.append(evt)
        except json.JSONDecodeError:
            continue
    return events


def load_events_after(baby_id: str, after_seq: int) -> list[dict]:
    """加载 seq > after_seq 的事件。用于 SSE 回放和增量推送。"""
    path = _baby_dir(baby_id) / "events.jsonl"
    if not path.is_file():
        return []
    events = []
    line_num = 0
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        line_num += 1
        try:
            evt = json.loads(line)
            seq = evt.get("seq", line_num)
            if seq > after_seq:
                if "seq" not in evt:
                    evt["seq"] = seq
                events.append(evt)
        except json.JSONDecodeError:
            continue
    return events


def _summarize_baby_state(data: dict) -> dict:
    """从 state.json 原文中抽取摇篮卡片需要的摘要字段。"""
    ph = data.get("physical", {})
    stress = data.get("stress", {})
    return {
        "baby_id": data["baby_id"],
        "name": data.get("name", ""),
        "species": data["species"],
        "current_phase": data["current_phase"],
        "age_days": data["age_days"],
        "expression_mode": data["expression_mode"],
        "milestones_count": len(data.get("milestones", [])),
        "memories_count": len(data.get("memories", [])),
        "height_cm": ph.get("height_cm", 50.0),
        "weight_kg": ph.get("weight_kg", 3.3),
        "stress_level": stress.get("stress_level", 0.0),
        "caregivers_count": len(data.get("caregivers", {})),
        "sim_time": data.get("sim_time", 0.0),
        "last_active_ts": data.get("last_active_ts", 0.0),
        "time_scale": data.get("time_scale", "normal"),
        # 世界地图消费：出生地含国家 + 经纬度
        "birthplace": data.get("birthplace", {}),
    }


def list_cradle_babies() -> list[dict]:
    """列出摇篮中所有婴儿的摘要（全量，仅启动自检消费）。"""
    if not ARCHIVE_DIR.is_dir():
        return []
    babies = []
    for d in sorted(ARCHIVE_DIR.iterdir()):
        state_path = d / "state.json"
        if state_path.is_file():
            data = json.loads(state_path.read_text(encoding="utf-8"))
            babies.append(_summarize_baby_state(data))
    return babies


# 分页端点（/cradle/babies）的页大小硬上限——防止客户端传大数造成 O(N) 全量解析。
CRADLE_BABIES_PAGE_SIZE_MAX = 100


def list_cradle_babies_page(page: int = 1, page_size: int = 100) -> tuple[list[dict], int]:
    """分页列出摇篮中婴儿的摘要。

    返回 (page_babies, total)。按 archive 目录名字典序排序。
    仅解析落在当前页窗口内的 state.json，total 用目录 stat 统计，避免
    O(N) 的 JSON 解析开销（N 可达数千）。

    page 从 1 起；page < 1 夹紧到 1。page_size 夹紧到 [1, CRADLE_BABIES_PAGE_SIZE_MAX]。
    超出最后一页返回空 babies，total 仍为实际总数。
    """
    page = max(1, int(page))
    page_size = max(1, min(CRADLE_BABIES_PAGE_SIZE_MAX, int(page_size)))

    if not ARCHIVE_DIR.is_dir():
        return [], 0

    baby_dirs = [
        d for d in sorted(ARCHIVE_DIR.iterdir())
        if (d / "state.json").is_file()
    ]
    total = len(baby_dirs)

    start = (page - 1) * page_size
    end = start + page_size
    window = baby_dirs[start:end]

    babies = []
    for d in window:
        data = json.loads((d / "state.json").read_text(encoding="utf-8"))
        babies.append(_summarize_baby_state(data))
    return babies, total
