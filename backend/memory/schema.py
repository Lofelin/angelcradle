"""
LifeMoment / Milestone / RecalledContext 数据模型。

设计原则：
- 无 `kind` 字段：用 actor/target 组合推断事件类型（消除特殊情况铁律）
- kind 选填段不存在：所有字段对所有事件类型都有意义或置空字符串
- append-only：状态转移（pending→responded/ignored）通过 companion_seq 链前向追加
- 标签严格复用 causality.py 产出（格式如 phase:N / stress:+0.15 / memory:positive）

[INPUT]: 无（纯数据模型）
[OUTPUT]: LifeMoment, Milestone, RecalledContext 数据类及 to_dict/from_dict
[POS]: memory/ 的数据模型层，被 store / ingest / recall 消费
[PROTOCOL]: 变更时更新此头部，然后检查 CLAUDE.md
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


# ============================================================
# LifeMoment：事件原子（瞬时发生的一段经历）
# ============================================================

@dataclass
class LifeMoment:
    """
    统一生命经验原子。一件真实事件完整装载：
      被动经验：actor="world"/caregiver:X, target="self"
      主动行为：actor="self",   target="world"/caregiver:X/""
      父母互动：actor="caregiver:X", target="self" 或反之
    "找妈妈讨论上学" → actor="self", target="caregiver:mom",
                       action="提出...", response="妈妈列利弊", outcome="responded"
    """

    # 身份
    seq: int = 0                                 # 单 baby 单序列
    source_seq: int = -1                         # events.jsonl 反查；-1 = 无

    # 时空
    phase: int = 0
    age_days: int = 0
    sim_time: float = 0.0

    # 当事人
    actor: str = "world"                         # "world" / "self" / f"caregiver:{stable_key}"
    target: str = ""                             # 同格式；"" = 无特定对象
    witnesses: list[str] = field(default_factory=list)

    # 内容
    trigger: str = ""                            # 事件名 / need trigger / action key
    action: str = ""                             # what happened（≤ 120 字自然语言）
    response: str = ""                           # 对方回应；"" = 无回应/被忽略
    outcome: str = "neutral"                     # responded / ignored / succeeded / failed / neutral / fallback / pending
    companion_seq: int = -1                      # append-only 状态转移链

    # 感受
    valence: str = "neutral"                     # positive / negative / neutral
    intensity: float = 0.5                       # 0..1

    # 因果标签（严格复用 causality.py 产出）
    cause_tags: list[str] = field(default_factory=list)
    effect_tags: list[str] = field(default_factory=list)

    # 首触标记
    is_first: bool = False

    # 遗忘分（recall 时动态计算，持久化作 cache）
    forget_score: float = 1.0

    def to_dict(self) -> dict:
        return {
            "seq": self.seq,
            "source_seq": self.source_seq,
            "phase": self.phase,
            "age_days": self.age_days,
            "sim_time": self.sim_time,
            "actor": self.actor,
            "target": self.target,
            "witnesses": list(self.witnesses),
            "trigger": self.trigger,
            "action": self.action,
            "response": self.response,
            "outcome": self.outcome,
            "companion_seq": self.companion_seq,
            "valence": self.valence,
            "intensity": self.intensity,
            "cause_tags": list(self.cause_tags),
            "effect_tags": list(self.effect_tags),
            "is_first": self.is_first,
            "forget_score": self.forget_score,
        }

    @classmethod
    def from_dict(cls, d: dict) -> LifeMoment:
        return cls(
            seq=int(d.get("seq", 0)),
            source_seq=int(d.get("source_seq", -1)),
            phase=int(d.get("phase", 0)),
            age_days=int(d.get("age_days", 0)),
            sim_time=float(d.get("sim_time", 0.0)),
            actor=d.get("actor", "world"),
            target=d.get("target", ""),
            witnesses=list(d.get("witnesses", []) or []),
            trigger=d.get("trigger", ""),
            action=d.get("action", ""),
            response=d.get("response", ""),
            outcome=d.get("outcome", "neutral"),
            companion_seq=int(d.get("companion_seq", -1)),
            valence=d.get("valence", "neutral"),
            intensity=float(d.get("intensity", 0.5)),
            cause_tags=list(d.get("cause_tags", []) or []),
            effect_tags=list(d.get("effect_tags", []) or []),
            is_first=bool(d.get("is_first", False)),
            forget_score=float(d.get("forget_score", 1.0)),
        )


# ============================================================
# Milestone：里程碑原子（能力变化/首触/阶段节点）
# ============================================================

@dataclass
class Milestone:
    """
    里程碑型经验。与 LifeMoment 时间尺度不同（结构性变化 vs 瞬时事件），独立存储。
    kind 在此处是合法字段（能力变化类型是结构化的分类数据，非事件类型的伪装分支）。
    """

    seq: int = 0
    phase: int = 0
    age_days: int = 0
    sim_time: float = 0.0
    kind: str = ""                               # capability_gained / capability_lost / capability_recovered
                                                 # / milestone_reached / first_X / phase_advanced / cradle_complete
    subject: str = ""                            # 能力名 / milestone 名 / first_X 事件名
    description: str = ""
    intensity: float = 0.8                       # 里程碑天然高权重
    tags: list[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "seq": self.seq,
            "phase": self.phase,
            "age_days": self.age_days,
            "sim_time": self.sim_time,
            "kind": self.kind,
            "subject": self.subject,
            "description": self.description,
            "intensity": self.intensity,
            "tags": list(self.tags),
        }

    @classmethod
    def from_dict(cls, d: dict) -> Milestone:
        return cls(
            seq=int(d.get("seq", 0)),
            phase=int(d.get("phase", 0)),
            age_days=int(d.get("age_days", 0)),
            sim_time=float(d.get("sim_time", 0.0)),
            kind=d.get("kind", ""),
            subject=d.get("subject", ""),
            description=d.get("description", ""),
            intensity=float(d.get("intensity", 0.8)),
            tags=list(d.get("tags", []) or []),
        )


# ============================================================
# RecalledContext：recall 返回结构
# ============================================================

@dataclass
class RecalledContext:
    """统一检索结果。phase_summaries 保持 dict（复用现有 state 结构）。"""

    semantic: list[dict] = field(default_factory=list)          # state.phase_summaries[-3:]
    episodic: list[LifeMoment] = field(default_factory=list)    # top-k 混合
    milestones: list[Milestone] = field(default_factory=list)   # 相关里程碑
    used_tokens: int = 0
    budget: int = 0                                             # 原始预算，便于日志/断言
