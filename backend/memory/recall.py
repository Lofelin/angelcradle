"""
统一检索：三层金字塔 + token_budget 裁剪 + tag 一跳倒排（Omni-SimpleMem 本土化）。

设计要点（D2 对齐）：
- Semantic 层：state.phase_summaries[-3:] 独立读，优先注入
- Episodic 层：life_moments.jsonl 按 (Jaccard + tag_overlap + forget_score) 排序 top-k
- 一跳倒排：从 top-k 的 cause/effect_tags 扩展同 tag 历史条目 1-3 条（内存 dict，cradle_graph 不碰）
- Milestone 层：里程碑相关性过滤，budget 允许时兜底
- token_budget 裁剪：按 len(json.dumps)//4 近似累加；预算不够时前层优先保留

回退路径（V2=off）：phase_summaries[-3:] + memories[-3:]，完全等同改造前行为。

[INPUT]: 依赖 memory.schema / store / ingest._tokens / forget_params / ingest._compute_forget_score
[OUTPUT]: recall, build_memory_prompt_block, _legacy_recall
[POS]: memory/ 的读取门面，被 mind.py 三入口 + nanny / heartbeat_provider 消费
[PROTOCOL]: 变更时更新此头部，然后检查 CLAUDE.md
"""

from __future__ import annotations

import json
import logging
from typing import Iterable, Optional

from . import store
from .forget_params import DEFAULT_TAU, TAU_BY_PHASE
from .ingest import _compute_forget_score, _jaccard, _tokens, is_v2_enabled
from .schema import LifeMoment, Milestone, RecalledContext

logger = logging.getLogger(__name__)

# 相关性打分：lex + tag 权重
_TAG_WEIGHT = 0.3          # 每个 tag 命中的加分
_SCORE_MIN = 0.001         # 分数下限（防止全 0 排序无意义）

# 裁剪预算中各层的保留下限（保留给下层的最少 token）
_RESERVE_FOR_EPISODIC = 300
_RESERVE_FOR_MILESTONE = 150


# ============================================================
# Token 估算（粗略，不依赖 tiktoken）
# ============================================================

def _estimate_tokens(obj) -> int:
    """
    近似 token 数。经验值：英文每 4 字符 ≈ 1 token，中文每字符 ≈ 1 token。
    用 JSON 序列化长度 // 4 做粗估（中文偏大、英文偏小，整体可用）。
    """
    if obj is None:
        return 0
    if isinstance(obj, (LifeMoment, Milestone)):
        return max(1, len(json.dumps(obj.to_dict(), ensure_ascii=False)) // 4)
    if isinstance(obj, dict):
        return max(1, len(json.dumps(obj, ensure_ascii=False)) // 4)
    if isinstance(obj, str):
        return max(1, len(obj) // 4)
    return max(1, len(str(obj)) // 4)


# ============================================================
# Semantic 层专用估算：只算 summary 字段尺寸（phase_summary dict 可能含
# stress_note / physical_note 等大字段，直接全算会吃光 budget）
# ============================================================

def _semantic_tokens(item, max_chars: int = 600) -> int:
    """从 phase_summary dict 只提取 summary 文本做 token 估算，长文截断。"""
    if isinstance(item, dict):
        text = item.get("summary", "") or item.get("content", "") or ""
        if isinstance(text, dict):
            text = text.get("summary", "") or ""
    else:
        text = str(item)
    text = (text or "")[:max_chars]
    return max(1, len(text) // 4)


# ============================================================
# 评分
# ============================================================

def _score(moment: LifeMoment, ctx_tokens: set[str],
           current_tags: set[str], current_age_days: int) -> float:
    """
    组合分 = (lex + tag_bonus) × intensity × recency
    - lex: Jaccard(moment 内容 tokens, 上下文 tokens)
    - tag_bonus: 命中 current_tags 的 cause/effect_tags 个数 × _TAG_WEIGHT
    - recency: exp(-Δ/τ) 遗忘衰减（复用 _compute_forget_score 的 τ 表和 boost 公式）
    """
    text = f"{moment.action} {moment.trigger} {moment.response}"
    mem_tokens = _tokens(text)
    lex = _jaccard(mem_tokens, ctx_tokens) if (mem_tokens or ctx_tokens) else 0.0

    tag_hits = 0
    if current_tags:
        tag_hits += sum(1 for t in moment.cause_tags if t in current_tags)
        tag_hits += sum(1 for t in moment.effect_tags if t in current_tags)
    tag_bonus = tag_hits * _TAG_WEIGHT

    # recency 复用遗忘公式（与写入时的 forget_score 一致）
    recency = _compute_forget_score(moment, current_age_days) / max(float(moment.intensity), 0.001)

    score = (lex + tag_bonus) * float(moment.intensity) * recency
    return max(score, _SCORE_MIN)


# ============================================================
# Tag 一跳倒排（D2-3）
# ============================================================

def _build_tag_index(moments: list[LifeMoment]) -> dict[str, list[LifeMoment]]:
    """cause_tags + effect_tags → moments 的倒排映射。内存 dict，零存储开销。"""
    idx: dict[str, list[LifeMoment]] = {}
    for m in moments:
        for t in m.cause_tags:
            idx.setdefault(t, []).append(m)
        for t in m.effect_tags:
            idx.setdefault(t, []).append(m)
    return idx


def _tag_expand(top_k: list[LifeMoment],
                idx: dict[str, list[LifeMoment]],
                limit: int = 3) -> list[LifeMoment]:
    """从 top_k 的 tags 出发扩展同 tag 历史条目，去重后最多 limit 条。"""
    seen_seqs = {m.seq for m in top_k}
    expand: list[LifeMoment] = []
    for m in top_k:
        for t in (m.cause_tags + m.effect_tags):
            for cand in idx.get(t, []):
                if cand.seq in seen_seqs:
                    continue
                seen_seqs.add(cand.seq)
                expand.append(cand)
                if len(expand) >= limit:
                    return expand
    return expand


# ============================================================
# Milestone 相关性过滤
# ============================================================

def _relevant_milestones(baby_id: str,
                         current_phase: int,
                         current_tags: set[str],
                         limit: int = 3) -> list[Milestone]:
    """取相关里程碑：同阶段或跨阶段但 tag 重合。按 intensity 降序。"""
    try:
        milestones = store.load_milestones(baby_id)
    except Exception:
        return []
    if not milestones:
        return []

    def ms_score(ms: Milestone) -> float:
        tag_hits = sum(1 for t in ms.tags if t in current_tags) if current_tags else 0
        phase_bonus = 0.3 if ms.phase == current_phase else 0.0
        return ms.intensity + tag_hits * 0.2 + phase_bonus

    ranked = sorted(milestones, key=ms_score, reverse=True)
    return ranked[:limit]


# ============================================================
# V2=off 回退分支
# ============================================================

def _legacy_recall(state) -> RecalledContext:
    """V2=off 时返回结构，保持与旧行为兼容（phase_summaries[-3:] + memories[-3:]）。"""
    semantic = list((getattr(state, "phase_summaries", None) or [])[-3:])
    # memories[-3:] 直接复用旧行为，但为了返回 LifeMoment 结构，走 _from_memory 降级视图
    # 不过 V2=off 的消费方通常只需要 semantic + 让业务代码自己用 state.memories[-3:]
    return RecalledContext(
        semantic=semantic,
        episodic=[],
        milestones=[],
        used_tokens=sum(_estimate_tokens(s) for s in semantic),
        budget=0,
    )


# ============================================================
# 主入口：recall
# ============================================================

def recall(
    state,
    context: str = "",
    current_tags: Optional[Iterable[str]] = None,
    token_budget: int = 1500,
    episodic_k: int = 8,
    milestone_k: int = 3,
) -> RecalledContext:
    """
    统一检索。默认 V2=on 走三层金字塔；V2=off 走 _legacy_recall。

    Args:
        state: BabyState（读取 baby_id / age_days / current_phase / phase_summaries）
        context: 当前情境的自然语言描述（通常是家长消息 / 场景描述）
        current_tags: 当前事件的 tags（来自 causality.py 产出）
        token_budget: prompt 预算（≈ token 数），用于层级裁剪
        episodic_k: episodic 层 top-k
        milestone_k: milestone 层 top-k

    Returns:
        RecalledContext(semantic, episodic, milestones, used_tokens, budget)
    """
    if not is_v2_enabled():
        return _legacy_recall(state)

    if state is None:
        return RecalledContext(budget=token_budget)

    baby_id = getattr(state, "baby_id", "")
    if not baby_id:
        return _legacy_recall(state)

    budget = token_budget
    tags_set: set[str] = set(current_tags or ())
    ctx_tokens = _tokens(context)
    age_days = getattr(state, "age_days", 0)
    phase = getattr(state, "current_phase", 0)

    # ---------- Step 1: Semantic（phase_summaries，独立读不混）----------
    # 真实 phase_summary dict 可能 500+ tokens（含 stress_note/physical_note 等）。
    # 用 _semantic_tokens 只估 summary 字段；且 semantic 层最多占 budget 40%，避免吃光。
    _semantic_budget_cap = max(400, int(token_budget * 0.4))
    _raw_semantic = list((getattr(state, "phase_summaries", None) or [])[-3:])
    semantic: list[dict] = []
    _sem_used = 0
    for s in _raw_semantic:
        cost = _semantic_tokens(s)
        if _sem_used + cost > _semantic_budget_cap:
            break
        semantic.append(s)
        _sem_used += cost
    budget -= _sem_used

    # ---------- Step 2: Episodic（life_moments 打分 + tag 一跳扩展）----------
    try:
        all_moments = store.load_life_moments(baby_id)
    except Exception as e:
        logger.warning("recall: load_life_moments failed (%s); falling back to legacy", e)
        return _legacy_recall(state)

    if all_moments:
        scored = sorted(
            all_moments,
            key=lambda m: -_score(m, ctx_tokens, tags_set, age_days),
        )
        top_k = scored[:episodic_k]
        tag_idx = _build_tag_index(all_moments)
        expand = _tag_expand(top_k, tag_idx, limit=3)
        candidate_episodic = top_k + expand
    else:
        candidate_episodic = []

    accepted_episodic: list[LifeMoment] = []
    for m in candidate_episodic:
        cost = _estimate_tokens(m)
        if budget - cost < _RESERVE_FOR_MILESTONE:
            break
        budget -= cost
        accepted_episodic.append(m)

    # ---------- Step 3: Milestone（兜底）----------
    candidate_ms = _relevant_milestones(baby_id, phase, tags_set, limit=milestone_k)
    accepted_ms: list[Milestone] = []
    for ms in candidate_ms:
        cost = _estimate_tokens(ms)
        if budget - cost < 0:
            break
        budget -= cost
        accepted_ms.append(ms)

    return RecalledContext(
        semantic=semantic,
        episodic=accepted_episodic,
        milestones=accepted_ms,
        used_tokens=token_budget - budget,
        budget=token_budget,
    )


# ============================================================
# prompt 片段渲染（mind.py 接入用）
# ============================================================

def build_memory_prompt_block(rc: RecalledContext,
                              empty_fallback: str = "No memories yet.") -> str:
    """
    把 RecalledContext 渲染成 LLM prompt 片段。
    V2=on 走三层；V2=off 且 rc.semantic 也空时返回 empty_fallback。
    """
    if not rc.semantic and not rc.episodic and not rc.milestones:
        return empty_fallback

    lines: list[str] = []

    if rc.semantic:
        lines.append("## Long-term traits")
        for s in rc.semantic:
            # phase_summaries 条目常为 dict，取 summary 字段；若是字符串直接用
            if isinstance(s, dict):
                text = s.get("summary") or s.get("content") or ""
                if isinstance(text, dict):
                    text = text.get("summary", "") or json.dumps(text, ensure_ascii=False)
            else:
                text = str(s)
            text = text.strip()
            if text:
                lines.append(f"- {text}")

    if rc.episodic:
        lines.append("## Recent episodes")
        for m in rc.episodic:
            # 三元组呈现：谁/做了什么/结果如何
            actor_label = _actor_label(m.actor)
            target_label = _actor_label(m.target) if m.target else ""
            head = f"[{m.valence}] {actor_label}"
            if target_label and target_label != actor_label:
                head += f" → {target_label}"
            body = m.action or m.trigger
            outcome_suffix = ""
            if m.response:
                outcome_suffix = f" (response: {m.response})"
            elif m.outcome == "ignored":
                outcome_suffix = " (ignored)"
            lines.append(f"- {head}: {body}{outcome_suffix}")

    if rc.milestones:
        lines.append("## Milestones")
        for ms in rc.milestones:
            label = f"[phase {ms.phase}] {ms.kind}: {ms.subject}"
            if ms.description:
                label += f" — {ms.description}"
            lines.append(f"- {label}")

    return "\n".join(lines) if lines else empty_fallback


def _actor_label(actor: str) -> str:
    if not actor:
        return ""
    if actor == "self":
        return "self"
    if actor == "world":
        return "world"
    if actor.startswith("caregiver:"):
        return actor[len("caregiver:"):] or "caregiver"
    return actor
