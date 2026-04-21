"""
主动行为场景原子结构。

一条 InitiativeScene 代表一个"某阶段婴儿可能主动发起的行为情境"——
trigger 是触发因素，context 是情境描述，expression 是按该阶段 expression_mode
输出的可观察表达，signal/facial/body 是身体多模态，intent 是内心意图。

[INPUT]: 无外部依赖
[OUTPUT]: InitiativeScene 数据类 + to_dict/from_dict
[POS]: scenes/ 的数据模型层，被 scenes/__init__.py 加载
[PROTOCOL]: 变更时更新此头部，然后检查 CLAUDE.md
"""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class InitiativeScene:
    """
    一条主动行为场景。

    核心约束：
    - trigger 必须 ∈ initiative_needs.TRIGGER_URGENCY 枚举（19 种）
    - expression 必须符合对应 phase 的 expression_mode（cradle.phases.EXPRESSION_MODES）
    - id 全局唯一，格式建议 "phase{N}_{trigger}_{slug}_NN"
    """

    id: str
    trigger: str
    context: str
    expression: str
    signal: str
    intent: str
    parent_hint: str
    facial: str = ""
    body: str = ""
    default_tags: list[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "trigger": self.trigger,
            "context": self.context,
            "expression": self.expression,
            "signal": self.signal,
            "facial": self.facial,
            "body": self.body,
            "intent": self.intent,
            "parent_hint": self.parent_hint,
            "default_tags": list(self.default_tags),
        }

    @classmethod
    def from_dict(cls, d: dict) -> "InitiativeScene":
        return cls(
            id=d["id"],
            trigger=d["trigger"],
            context=d.get("context", ""),
            expression=d.get("expression", ""),
            signal=d.get("signal", ""),
            facial=d.get("facial", ""),
            body=d.get("body", ""),
            intent=d.get("intent", ""),
            parent_hint=d.get("parent_hint", ""),
            default_tags=list(d.get("default_tags", []) or []),
        )
