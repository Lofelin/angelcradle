"""
婴儿成长状态模型。

这是摇篮中婴儿的活档案——从出生到进入世界，所有成长轨迹都记录在这里。
状态持久化到 backend/nursery/{baby_id}/ 目录。

[INPUT]: 依赖 cradle/phases.py 的阶段定义
[OUTPUT]: BabyState, ParentProfile 数据类，load/save 函数
[POS]: cradle/ 的状态管理层，被所有其他 cradle 模块消费
[PROTOCOL]: 变更时更新此头部，然后检查 CLAUDE.md
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

NURSERY_DIR = Path(__file__).parent.parent / "nursery"


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
class ParentProfile:
    """父母画像，从介入行为中追踪。影响依恋类型。"""
    responsiveness: float = 0.5         # 0-1，呼唤时是否回应
    intervention_style: str = "balanced"  # protective / balanced / hands_off
    teaching_frequency: float = 0.5     # 0-1，多久主动教导
    emotional_tone: str = "warm"        # warm / neutral / anxious
    total_interventions: int = 0
    interaction_count: int = 0                                  # 亲子对话次数
    intervention_log: list[dict] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "responsiveness": self.responsiveness,
            "intervention_style": self.intervention_style,
            "teaching_frequency": self.teaching_frequency,
            "emotional_tone": self.emotional_tone,
            "total_interventions": self.total_interventions,
            "interaction_count": self.interaction_count,
            "intervention_log": self.intervention_log[-20:],  # 只保留最近 20 条
        }

    @classmethod
    def from_dict(cls, d: dict) -> ParentProfile:
        return cls(
            responsiveness=d.get("responsiveness", 0.5),
            intervention_style=d.get("intervention_style", "balanced"),
            teaching_frequency=d.get("teaching_frequency", 0.5),
            emotional_tone=d.get("emotional_tone", "warm"),
            total_interventions=d.get("total_interventions", 0),
            interaction_count=d.get("interaction_count", 0),
            intervention_log=d.get("intervention_log", []),
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
        }

    @classmethod
    def from_dict(cls, d: dict) -> Memory:
        return cls(**d)


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
        return cls(**d)


@dataclass
class BabyState:
    """婴儿在摇篮中的完整状态。"""
    # 基本信息（从 Baby 数据复制）
    baby_id: str = ""
    species: str = "human"
    name: str = ""                      # 由父母命名，初始为空

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

    # 父母
    parent_profile: ParentProfile = field(default_factory=ParentProfile)

    # 阶段日志
    phase_summaries: list[dict] = field(default_factory=list)

    # 已模拟阶段（幂等性保护：防止断连重连时重复模拟）
    simulated_phases: list[int] = field(default_factory=list)

    # 世界就绪度
    world_readiness: dict = field(default_factory=dict)

    def to_dict(self) -> dict:
        return {
            "baby_id": self.baby_id,
            "species": self.species,
            "name": self.name,
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
            "parent_profile": self.parent_profile.to_dict(),
            "phase_summaries": self.phase_summaries,
            "simulated_phases": self.simulated_phases,
            "world_readiness": self.world_readiness,
        }

    @classmethod
    def from_dict(cls, d: dict) -> BabyState:
        return cls(
            baby_id=d.get("baby_id", ""),
            species=d.get("species", "human"),
            name=d.get("name", ""),
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
            parent_profile=ParentProfile.from_dict(d.get("parent_profile", {})),
            phase_summaries=d.get("phase_summaries", []),
            simulated_phases=d.get("simulated_phases", []),
            world_readiness=d.get("world_readiness", {}),
        )


# ============================================================
# 持久化
# ============================================================

def _baby_dir(baby_id: str) -> Path:
    return NURSERY_DIR / baby_id


def save_state(state: BabyState) -> None:
    """保存婴儿成长状态。"""
    d = _baby_dir(state.baby_id)
    d.mkdir(parents=True, exist_ok=True)
    path = d / "state.json"
    path.write_text(
        json.dumps(state.to_dict(), ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


def load_state(baby_id: str) -> Optional[BabyState]:
    """加载婴儿成长状态。"""
    path = _baby_dir(baby_id) / "state.json"
    if not path.is_file():
        return None
    data = json.loads(path.read_text(encoding="utf-8"))
    return BabyState.from_dict(data)


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


def append_event(baby_id: str, event: dict) -> None:
    """追加一条 SSE 事件到 events.jsonl（JSONL 格式）。"""
    import time as _time
    d = _baby_dir(baby_id)
    d.mkdir(parents=True, exist_ok=True)
    path = d / "events.jsonl"
    line = json.dumps({"ts": _time.time(), **event}, ensure_ascii=False)
    with open(path, "a", encoding="utf-8") as f:
        f.write(line + "\n")


def load_events(baby_id: str) -> list[dict]:
    """加载婴儿的所有历史 SSE 事件。"""
    path = _baby_dir(baby_id) / "events.jsonl"
    if not path.is_file():
        return []
    events = []
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line:
            try:
                events.append(json.loads(line))
            except json.JSONDecodeError:
                continue
    return events


def list_cradle_babies() -> list[dict]:
    """列出摇篮中所有婴儿的摘要。"""
    if not NURSERY_DIR.is_dir():
        return []
    babies = []
    for d in sorted(NURSERY_DIR.iterdir()):
        state_path = d / "state.json"
        if state_path.is_file():
            data = json.loads(state_path.read_text(encoding="utf-8"))
            babies.append({
                "baby_id": data["baby_id"],
                "name": data.get("name", ""),
                "species": data["species"],
                "current_phase": data["current_phase"],
                "age_days": data["age_days"],
                "expression_mode": data["expression_mode"],
                "milestones_count": len(data.get("milestones", [])),
                "memories_count": len(data.get("memories", [])),
            })
    return babies
