"""
主动行为场景原子结构。

一条 InitiativeScene 代表一个"某阶段婴儿可能主动发起的行为情境"——
trigger 是触发因素，context 是情境描述，expression 是按该阶段 expression_mode
输出的可观察表达，signal/facial/body 是身体多模态，intent 是内心意图。

双语适配（向后兼容）:
- 英文主字段：context / expression / signal / facial / body
  （LLM few-shot prompt 使用，保留不变）
- 中文副字段：context_zh / expression_zh / signal_zh / facial_zh / body_zh
  （前端家长视角展示用）
- intent / parent_hint 天生中文，新增 intent_en / parent_hint_en 供英文侧使用
- 全部副字段可选，缺省为空字符串；旧 JSON 无需改动即可继续加载

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
    - 中/英副字段均可选，缺省空串；消费方按需取对应语种
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
    # 中文副字段（描述类字段的中文版本，前端展示用）
    context_zh: str = ""
    expression_zh: str = ""
    signal_zh: str = ""
    facial_zh: str = ""
    body_zh: str = ""
    # 英文副字段（描述类字段的英文版本 + intent/parent_hint 的英文译）
    # 注意：phase_04+ 的主字段 expression/signal 本身含中文对白（首词期开始），
    # 因此也需要 *_en 提供英文描述供国际化。
    context_en: str = ""
    expression_en: str = ""
    signal_en: str = ""
    facial_en: str = ""
    body_en: str = ""
    intent_en: str = ""
    parent_hint_en: str = ""

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
            "context_zh": self.context_zh,
            "expression_zh": self.expression_zh,
            "signal_zh": self.signal_zh,
            "facial_zh": self.facial_zh,
            "body_zh": self.body_zh,
            "context_en": self.context_en,
            "expression_en": self.expression_en,
            "signal_en": self.signal_en,
            "facial_en": self.facial_en,
            "body_en": self.body_en,
            "intent_en": self.intent_en,
            "parent_hint_en": self.parent_hint_en,
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
            context_zh=d.get("context_zh", ""),
            expression_zh=d.get("expression_zh", ""),
            signal_zh=d.get("signal_zh", ""),
            facial_zh=d.get("facial_zh", ""),
            body_zh=d.get("body_zh", ""),
            context_en=d.get("context_en", ""),
            expression_en=d.get("expression_en", ""),
            signal_en=d.get("signal_en", ""),
            facial_en=d.get("facial_en", ""),
            body_en=d.get("body_en", ""),
            intent_en=d.get("intent_en", ""),
            parent_hint_en=d.get("parent_hint_en", ""),
        )

    # ------------------------------------------------------------
    # 便捷取值：按语种获取整组描述字段
    # ------------------------------------------------------------

    def localized(self, lang: str = "zh") -> dict:
        """
        按语种返回一组可展示字段。

        lang='zh': 英文描述 → 取 *_zh，缺省回退英文原文
        lang='en': 中文描述 → 取 *_en，缺省回退中文原文
        """
        if lang == "zh":
            return {
                "context": self.context_zh or self.context,
                "expression": self.expression_zh or self.expression,
                "signal": self.signal_zh or self.signal,
                "facial": self.facial_zh or self.facial,
                "body": self.body_zh or self.body,
                "intent": self.intent,
                "parent_hint": self.parent_hint,
            }
        return {
            "context": self.context_en or self.context,
            "expression": self.expression_en or self.expression,
            "signal": self.signal_en or self.signal,
            "facial": self.facial_en or self.facial,
            "body": self.body_en or self.body,
            "intent": self.intent_en or self.intent,
            "parent_hint": self.parent_hint_en or self.parent_hint,
        }
