"""
Heartbeat 主动行为系统 — 跨模块的生命体主动行为引擎。

通过 Inner Monologue（内心独白）上下文让 LLM 作为生命体的潜意识，
判断此刻是否要主动发起行为（寻求接近、表达需求、或主动躲避）。

三个触发时机：grow/stream 阶段结束后、interact 完成后、空闲 poll。
适配器模式：各生命阶段模块（cradle/world）通过 MonologueProvider 提供上下文。

[INPUT]: 依赖 llm.py 的 LLM 基础设施，各模块的 MonologueProvider 实现
[OUTPUT]: InitiativeState, BehaviorSpace, MonologueProvider, evaluate_heartbeat()
[POS]: 顶级模块，被 api/ 和各生命阶段模块消费
[PROTOCOL]: 变更时更新此头部，然后检查 CLAUDE.md
"""

from __future__ import annotations

import logging
import time
import uuid
from dataclasses import dataclass, field
from typing import Any, Protocol

logger = logging.getLogger(__name__)


# ── 数据模型 ──────────────────────────────────────────────


@dataclass
class InitiativeState:
    """
    主动行为状态追踪。
    通用结构，不绑定特定生命阶段模块。
    """
    last_initiative_ts: float = 0.0
    last_interact_ts: float = 0.0
    pending_initiative_id: str = ""
    pending_initiative_ts: float = 0.0
    pending_initiative_type: str = ""       # urgent / exploratory
    pending_behavior_type: str = ""         # verbal / physical / avoidance
    consecutive_ignores: int = 0
    total_initiatives: int = 0
    total_responded: int = 0
    total_ignored: int = 0

    def to_dict(self) -> dict:
        return {
            "last_initiative_ts": self.last_initiative_ts,
            "last_interact_ts": self.last_interact_ts,
            "pending_initiative_id": self.pending_initiative_id,
            "pending_initiative_ts": self.pending_initiative_ts,
            "pending_initiative_type": self.pending_initiative_type,
            "pending_behavior_type": self.pending_behavior_type,
            "consecutive_ignores": self.consecutive_ignores,
            "total_initiatives": self.total_initiatives,
            "total_responded": self.total_responded,
            "total_ignored": self.total_ignored,
        }

    @classmethod
    def from_dict(cls, d: dict) -> InitiativeState:
        return cls(
            last_initiative_ts=d.get("last_initiative_ts", 0.0),
            last_interact_ts=d.get("last_interact_ts", 0.0),
            pending_initiative_id=d.get("pending_initiative_id", ""),
            pending_initiative_ts=d.get("pending_initiative_ts", 0.0),
            pending_initiative_type=d.get("pending_initiative_type", ""),
            pending_behavior_type=d.get("pending_behavior_type", ""),
            consecutive_ignores=d.get("consecutive_ignores", 0),
            total_initiatives=d.get("total_initiatives", 0),
            total_responded=d.get("total_responded", 0),
            total_ignored=d.get("total_ignored", 0),
        )


@dataclass
class BehaviorSpace:
    """
    当前发育阶段可用的行为空间。
    各生命阶段模块根据当前能力构造。
    """
    verbal: list[str] = field(default_factory=list)
    physical: list[str] = field(default_factory=list)
    avoidance: list[str] = field(default_factory=list)

    def to_prompt_section(self) -> str:
        lines = ["## Available Behaviors"]
        if self.verbal:
            lines.append(f"Verbal: {', '.join(self.verbal)}")
        if self.physical:
            lines.append(f"Physical: {', '.join(self.physical)}")
        if self.avoidance:
            lines.append(f"Avoidance: {', '.join(self.avoidance)}")
        return "\n".join(lines)


# ── 适配器协议 ────────────────────────────────────────────


class MonologueProvider(Protocol):
    """
    各生命阶段模块实现此协议，为心跳评估提供上下文。
    """
    def build_inner_monologue(self, state: Any) -> str:
        """构造生命体的内心状态摘要。"""
        ...

    def get_behavior_space(self, state: Any) -> BehaviorSpace:
        """返回当前发育阶段的可用行为空间。"""
        ...

    def get_expression_mode(self, state: Any) -> str:
        """返回当前表达模式标识。"""
        ...

    def get_expression_constraints(self, state: Any) -> dict:
        """返回表达模式的描述和格式规则。"""
        ...

    def get_attachment_style(self, state: Any) -> str:
        """返回当前依恋风格。"""
        ...

    def get_caregivers(self, state: Any) -> dict:
        """返回照护者画像字典。"""
        ...

    def get_stress_state(self, state: Any) -> Any:
        """返回压力状态对象。"""
        ...

    def apply_ignore_escalation(self, state: Any) -> None:
        """连续忽略 >=3 次时的模块特定后果（stress regression, attachment shift 等）。"""
        ...

    def save_state(self, state: Any) -> None:
        """持久化状态。"""
        ...

    def get_species(self, state: Any) -> str:
        """返回物种。"""
        ...

    def get_age_days(self, state: Any) -> int:
        """返回日龄。"""
        ...


# ── 频率控制 ──────────────────────────────────────────────


HARD_MIN_INTERVAL = 120     # 2 分钟，绝对最小间隔
POST_INTERACT_COOLDOWN = 60  # interact 后 60 秒冷却


def frequency_gate(ini: InitiativeState) -> bool:
    """
    硬性频率门卫。LLM 通过 inner monologue 自律频率，此处仅做兜底。
    """
    now = time.time()
    if ini.last_initiative_ts and now - ini.last_initiative_ts < HARD_MIN_INTERVAL:
        return False
    if ini.last_interact_ts and now - ini.last_interact_ts < POST_INTERACT_COOLDOWN:
        return False
    return True


# ── 忽略检测 ──────────────────────────────────────────────


IGNORE_TIMEOUT = 300  # 5 分钟


def _check_and_process_ignore(
    state: Any,
    provider: MonologueProvider,
    ini: InitiativeState,
    now: float,
    generate_ignored_fn: Any,
) -> dict | None:
    """
    检测 pending 主动行为是否已超时被忽略。
    返回忽略反应 dict 或 None。
    """
    if not ini.pending_initiative_id:
        return None
    if now - ini.pending_initiative_ts < IGNORE_TIMEOUT:
        return None

    # 标记忽略
    ini.consecutive_ignores += 1
    ini.total_ignored += 1
    ignored_type = ini.pending_initiative_type
    ignored_behavior = ini.pending_behavior_type
    ini.pending_initiative_id = ""
    ini.pending_initiative_type = ""
    ini.pending_behavior_type = ""

    # 照护者 responsiveness 扣分
    caregivers = provider.get_caregivers(state)
    for cg in caregivers.values():
        cg.responsiveness = max(0.0, cg.responsiveness - 0.05)

    # 连续忽略 >=3 次：模块特定升级后果
    if ini.consecutive_ignores >= 3:
        stress = provider.get_stress_state(state)
        stress.stress_level = min(1.0, stress.stress_level + 0.1)
        provider.apply_ignore_escalation(state)

    # LLM 生成忽略反应
    reaction = generate_ignored_fn(state, provider, ini, ignored_type, ignored_behavior)

    provider.save_state(state)
    return reaction


# ── 心跳评估主入口 ────────────────────────────────────────


def evaluate_heartbeat(
    state: Any,
    provider: MonologueProvider,
    ini: InitiativeState,
    generate_heartbeat_fn: Any,
    generate_ignored_fn: Any,
) -> dict:
    """
    心跳评估主入口。

    Returns:
        {
            "initiative": {...} | None,
            "ignored_reaction": {...} | None,
        }
    """
    now = time.time()
    result = {"initiative": None, "ignored_reaction": None}

    # 1. 先检查忽略
    ignored = _check_and_process_ignore(state, provider, ini, now, generate_ignored_fn)
    if ignored:
        result["ignored_reaction"] = ignored

    # 2. 如果还有 pending 未超时，不产生新的
    if ini.pending_initiative_id:
        return result

    # 3. 频率门卫
    if not frequency_gate(ini):
        return result

    # 4. 构造内心独白 + 行为空间
    monologue = provider.build_inner_monologue(state)
    behavior_space = provider.get_behavior_space(state)
    expression_mode = provider.get_expression_mode(state)
    expression_constraints = provider.get_expression_constraints(state)

    # 5. LLM 评估
    initiative = generate_heartbeat_fn(
        state, provider, monologue, behavior_space,
        expression_mode, expression_constraints, ini,
    )

    if initiative and initiative.get("initiative"):
        # 记录 pending
        intent_id = uuid.uuid4().hex[:12]
        ini.pending_initiative_id = intent_id
        ini.pending_initiative_ts = now
        ini.pending_initiative_type = initiative.get("type", "exploratory")
        ini.pending_behavior_type = initiative.get("behavior_type", "verbal")
        ini.last_initiative_ts = now
        ini.total_initiatives += 1

        initiative["intent_id"] = intent_id
        initiative["timestamp"] = now
        result["initiative"] = initiative

        provider.save_state(state)

    return result


def mark_responded(ini: InitiativeState, caregivers: dict) -> None:
    """
    标记 pending 主动行为已被响应。在 interact 端点中调用。
    """
    if not ini.pending_initiative_id:
        return
    ini.pending_initiative_id = ""
    ini.pending_initiative_type = ""
    ini.pending_behavior_type = ""
    ini.consecutive_ignores = 0
    ini.total_responded += 1
    ini.last_interact_ts = time.time()
    for cg in caregivers.values():
        cg.responsiveness = min(1.0, cg.responsiveness + 0.03)
