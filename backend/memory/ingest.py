"""
Selective Ingestion 新颖性闸门 + record_moment / record_milestone 单写入口。

架构铁律：
- record_moment 是 LifeMoment 的**唯一写入口**（CI 静态检查将禁用 state.memories.append 直接调用）
- 写顺序约定：先 append_life_moment → 再 state.memories.append(_downgrade) → 最后由调用方 save_state
- V2=on 时强制降级回写 state.memories，守 interaction/requirements.md:49 等旧 spec 契约
- 崩溃半成功可恢复：jsonl 孤儿可容忍（recall fallback state.memories），启动自检修复
- 不变量：任意 save_state 前 len(state.memories) == count_life_moments

[INPUT]: 依赖 memory.schema, memory.store, memory.forget_params,
         cradle.state.Memory（用于 _downgrade_to_memory）
[OUTPUT]: should_ingest, record_moment, record_milestone,
          _downgrade_to_memory, _compute_forget_score,
          is_v2_enabled, _tokens, _jaccard
[POS]: memory/ 的写入门面，被所有 Memory() 历史创建点 + 主动行为接入点调用
[PROTOCOL]: 变更时更新此头部，然后检查 CLAUDE.md
"""

from __future__ import annotations

import logging
import math
import os
import re
from typing import Iterable, Optional

from . import store
from .forget_params import (
    CAREGIVER_PREFIX,
    DEFAULT_TAU,
    HIGH_INTENSITY,
    JACCARD_THRESHOLD,
    LOW_INTENSITY,
    MEMORY_V2_ENV,
    RECENT_WINDOW,
    TAU_BY_PHASE,
)
from .schema import LifeMoment, Milestone

logger = logging.getLogger(__name__)


# ============================================================
# V2 灰度开关
# ============================================================

def is_v2_enabled() -> bool:
    """MEMORY_V2 默认 on。设为 "off" 时走旧行为回退。"""
    val = os.environ.get(MEMORY_V2_ENV, "on").strip().lower()
    return val != "off"


# ============================================================
# 文本分词 + Jaccard（零依赖，复用 causality.py 风格）
# ============================================================

_TOKEN_RE = re.compile(r"[\w\u4e00-\u9fff]+")
_STOP = frozenset({
    "the", "a", "an", "to", "of", "and", "or", "is", "was", "in", "on", "at",
    "了", "的", "在", "和", "与", "是", "有", "被", "而",
})


def _tokens(text: str) -> set[str]:
    if not text:
        return set()
    return {t.lower() for t in _TOKEN_RE.findall(text)
            if t.lower() not in _STOP and len(t) >= 2}


def _jaccard(a: set[str], b: set[str]) -> float:
    if not a and not b:
        return 0.0
    inter = len(a & b)
    uni = len(a | b)
    return inter / uni if uni else 0.0


# ============================================================
# 遗忘分（recall / consolidation 共用公式）
# ============================================================

def _compute_forget_score(moment: LifeMoment, current_age_days: int) -> float:
    """
    forget_score = intensity × exp(-Δ_days / (τ × (1 + 0.5 × intensity)))
    - τ 按 phase 查表（新生儿 3 天，学龄前 1080 天）
    - emotional_boost 用 intensity 线性（v1 改 arousal/valence 拆分）
    """
    delta = max(current_age_days - moment.age_days, 0)
    tau = TAU_BY_PHASE.get(moment.phase, DEFAULT_TAU)
    boost = 1.0 + 0.5 * float(moment.intensity)
    return float(moment.intensity) * math.exp(-delta / (tau * boost))


# ============================================================
# Selective Ingestion 新颖性闸门（D2-1）
# ============================================================

def should_ingest(baby_id: str, moment: LifeMoment) -> bool:
    """
    决定是否入库。强制白名单优先，低强度条目走 Jaccard 去重。
    """
    # 强制白名单：高强度 / 首触 / caregiver 参与 / 非 neutral outcome
    if moment.intensity >= HIGH_INTENSITY:
        return True
    if moment.is_first:
        return True
    if moment.actor.startswith(CAREGIVER_PREFIX) or moment.target.startswith(CAREGIVER_PREFIX):
        return True
    if moment.outcome in {"responded", "ignored", "fallback"}:
        return True

    # 低强度 + 高重复 → 丢弃
    if moment.intensity < LOW_INTENSITY:
        try:
            recent = store.load_recent_moments(baby_id, limit=RECENT_WINDOW)
        except Exception:
            # 读失败保守放行，不阻塞主流程
            return True
        new_tokens = _tokens(f"{moment.action} {moment.trigger}")
        for r in recent:
            old_tokens = _tokens(f"{r.action} {r.trigger}")
            if _jaccard(new_tokens, old_tokens) >= JACCARD_THRESHOLD:
                return False

    return True


# ============================================================
# 降级：LifeMoment → cradle.state.Memory（守 interaction 契约，D1-2）
# ============================================================

def _downgrade_to_memory(moment: LifeMoment):
    """
    把 LifeMoment 压缩回传统 Memory，使得：
    - interaction spec 契约（读 state.memories 最近 3 条）仍成立
    - 老代码 V2=off 回退无需改动
    - rebuild_triggered_events 等消费 state.memories 的函数零影响
    """
    from cradle.state import Memory

    is_self = (moment.actor == "self")
    is_caregiver = moment.actor.startswith(CAREGIVER_PREFIX)
    caregiver_involved = is_caregiver or moment.target.startswith(CAREGIVER_PREFIX)

    # 被动经验：stimulus=发生的事，reaction=婴儿反应
    # 主动行为：stimulus 空，reaction=婴儿做的事（这是对 Memory 字段的最合理映射）
    if is_self:
        stimulus = ""
        reaction = moment.action
    else:
        stimulus = moment.action
        reaction = moment.response

    return Memory(
        phase=moment.phase,
        age_days=moment.age_days,
        event=moment.trigger or moment.action[:40],
        stimulus=stimulus,
        reaction=reaction,
        trace=",".join(moment.cause_tags),
        emotional_valence=moment.valence,
        intensity=moment.intensity,
        parent_involved=caregiver_involved,
        parent_action=moment.action if is_caregiver else moment.response,
        growth_signal=",".join(t for t in moment.effect_tags if t.startswith("growth:")),
        forget_score=moment.forget_score,
    )


# ============================================================
# 单写入口：record_moment（D1-1）
# ============================================================

def record_moment(
    state,
    baby_id: str,
    *,
    actor: str,
    target: str = "",
    witnesses: Optional[Iterable[str]] = None,
    trigger: str = "",
    action: str = "",
    response: str = "",
    outcome: str = "neutral",
    valence: str = "neutral",
    intensity: float = 0.5,
    cause_tags: Optional[Iterable[str]] = None,
    effect_tags: Optional[Iterable[str]] = None,
    is_first: bool = False,
    source_seq: int = -1,
    companion_seq: int = -1,
    _legacy_memory_override=None,  # 旧创建点传入已构造的 Memory，保留 trace LLM 原文等字段
) -> Optional[LifeMoment]:
    """
    LifeMoment 唯一写入口。返回写入的 moment（被新颖性闸门丢弃时返回 None）。

    不自动调 save_state —— 调用方负责（通常在 nanny/mind/heartbeat 的业务闭包末尾统一 save）。

    写顺序约定：
      1. next_moment_seq（分配 seq）
      2. should_ingest（闸门）
      3. append_life_moment（jsonl，新真相源）
      4. state.memories.append(_downgrade 或 _legacy_memory_override)
         V2 开关无关，总是回写（D1-2 守 interaction 契约）

    关于 `_legacy_memory_override`：
      旧创建点（mind.py:681/836 / scheduler/story.py:140）已精心构造 Memory 对象，
      其 trace 字段是 LLM 英文句子，与自动降级的 tags 字符串语义不同。
      传入此参数让降级回写使用原 Memory 对象，避免语义丢失。
      新创建点（主动行为/里程碑）不需要此参数，由 _downgrade_to_memory 自动生成。

    崩溃后若 step 3 完成 step 4 未完成，启动自检 self_heal 可补齐 step 4。
    """
    if state is None:
        logger.warning("record_moment called with state=None, skip")
        return None

    seq = store.next_moment_seq(baby_id)
    moment = LifeMoment(
        seq=seq,
        source_seq=source_seq,
        phase=getattr(state, "current_phase", 0),
        age_days=getattr(state, "age_days", 0),
        sim_time=float(getattr(state, "sim_time", 0.0)),
        actor=actor,
        target=target,
        witnesses=list(witnesses or []),
        trigger=trigger,
        action=action,
        response=response,
        outcome=outcome,
        companion_seq=companion_seq,
        valence=valence,
        intensity=float(intensity),
        cause_tags=list(cause_tags or []),
        effect_tags=list(effect_tags or []),
        is_first=is_first,
    )
    moment.forget_score = _compute_forget_score(moment, getattr(state, "age_days", 0))

    # 闸门
    if not should_ingest(baby_id, moment):
        # 被过滤：回退 seq 计数（后续 next_moment_seq 会拿到下一个；此处不回滚，保持单调）
        logger.debug("moment filtered by ingest gate: actor=%s trigger=%s", actor, trigger)
        return None

    # Step 3: 写 jsonl（新真相源）
    store.append_life_moment(baby_id, moment)

    # Step 4: 降级回写 state.memories（V2=on 默认，守 interaction 契约）
    # V2=off 时也仍然写 —— 关闭 V2 只影响读路径（不影响写），避免灰度期数据分叉
    if hasattr(state, "memories"):
        if _legacy_memory_override is not None:
            # 旧创建点保留原 Memory 对象（含 LLM 原文 trace 等语义），
            # 只把 forget_score 同步为新计算值
            try:
                _legacy_memory_override.forget_score = moment.forget_score
            except AttributeError:
                pass
            state.memories.append(_legacy_memory_override)
        else:
            state.memories.append(_downgrade_to_memory(moment))

    return moment


# ============================================================
# 单写入口：record_milestone
# ============================================================

def record_milestone(
    state,
    baby_id: str,
    *,
    kind: str,
    subject: str,
    description: str = "",
    intensity: float = 0.8,
    tags: Optional[Iterable[str]] = None,
) -> Milestone:
    """
    Milestone 唯一写入口。Milestone 不降级回写 state.milestones（state 已有独立 milestones 列表，
    业务代码继续自行维护；本函数只写 milestones.jsonl 作为可检索真相源）。
    """
    seq = store.next_milestone_seq(baby_id)
    ms = Milestone(
        seq=seq,
        phase=getattr(state, "current_phase", 0),
        age_days=getattr(state, "age_days", 0),
        sim_time=float(getattr(state, "sim_time", 0.0)),
        kind=kind,
        subject=subject,
        description=description,
        intensity=float(intensity),
        tags=list(tags or []),
    )
    store.append_milestone(baby_id, ms)
    return ms


# ============================================================
# 不变量断言（D1 强制前提）
# ============================================================

def assert_invariant(state, baby_id: str) -> None:
    """
    调用点：每次 save_state 前（可选）+ 测试环境每次 record_moment 后。
    生产环境失败记 log 不抛异常；测试环境 MEMORY_STRICT=1 抛 AssertionError。
    """
    if state is None or not hasattr(state, "memories"):
        return
    mem_count = len(state.memories)
    try:
        moment_count = store.count_life_moments(baby_id)
    except Exception:
        return

    # 兼容场景：老 baby 的 state.memories 可能有历史条目，但 life_moments.jsonl 还未重建
    # 只检查"新增部分"：moment_count 必须 ≥ 某个时刻后新增的 memory 数
    # 这里保守策略：仅在 moment_count > 0 时校验相等
    if moment_count > 0 and mem_count != moment_count:
        msg = (
            f"[memory] invariant violated: len(state.memories)={mem_count} "
            f"!= count_life_moments={moment_count} (baby={baby_id})"
        )
        if os.environ.get("MEMORY_STRICT", "").strip() == "1":
            raise AssertionError(msg)
        logger.warning(msg)
