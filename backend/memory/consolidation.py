"""
遗忘 + 巩固：recompute_forget_scores / prune_if_needed / self_heal。

不做聚类合并/软归档（v1 延伸目标）。阶段 A 只做：
1. recompute_forget_scores: 重算所有 life_moments 的 forget_score
2. prune_if_needed: 超过 PRUNE_SOFT_CAP 时按 forget_score 保留 top PRUNE_KEEP_TOP（硬剪）
3. self_heal: 启动自检，修复 jsonl 和 state.memories 的不一致（D1-4 崩溃恢复）

[INPUT]: 依赖 memory.store / schema / forget_params / ingest._compute_forget_score
[OUTPUT]: recompute_forget_scores, prune_if_needed, self_heal
[POS]: memory/ 的后台维护层，被 scheduler 睡眠事件 + 启动 lifespan 调用
[PROTOCOL]: 变更时更新此头部，然后检查 CLAUDE.md
"""

from __future__ import annotations

import logging

from . import store
from .forget_params import PRUNE_KEEP_TOP, PRUNE_SOFT_CAP
from .ingest import _compute_forget_score, _downgrade_to_memory

logger = logging.getLogger(__name__)


# ============================================================
# 重算遗忘分（睡眠事件触发）
# ============================================================

def recompute_forget_scores(state, baby_id: str) -> int:
    """
    遍历所有 life_moments，按 state.age_days 重算 forget_score。
    原子重写 jsonl（tempfile + os.replace）。
    返回：重算条数。
    """
    try:
        moments = store.load_life_moments(baby_id)
    except Exception as e:
        logger.warning("recompute_forget_scores: load failed %s", e)
        return 0
    if not moments:
        return 0

    age_days = getattr(state, "age_days", 0)
    for m in moments:
        m.forget_score = _compute_forget_score(m, age_days)

    try:
        store.rewrite_life_moments(baby_id, moments)
    except Exception as e:
        logger.warning("recompute_forget_scores: rewrite failed %s", e)
        return 0

    return len(moments)


# ============================================================
# 惰性剪枝
# ============================================================

def prune_if_needed(state, baby_id: str,
                    soft_cap: int = PRUNE_SOFT_CAP,
                    keep_top: int = PRUNE_KEEP_TOP) -> int:
    """
    超过 soft_cap 时按 forget_score 保留 top keep_top。
    先调 recompute 保证分数最新，然后按分数倒序保留。
    返回被裁条数（0 表示不触发）。
    """
    try:
        moments = store.load_life_moments(baby_id)
    except Exception:
        return 0
    if len(moments) <= soft_cap:
        return 0

    age_days = getattr(state, "age_days", 0)
    for m in moments:
        m.forget_score = _compute_forget_score(m, age_days)
    moments.sort(key=lambda m: -m.forget_score)
    kept = moments[:keep_top]
    pruned = len(moments) - len(kept)
    # 保持 seq 单调（仍用原始 seq 不重分配）
    kept.sort(key=lambda m: m.seq)
    try:
        store.rewrite_life_moments(baby_id, kept)
    except Exception as e:
        logger.warning("prune_if_needed: rewrite failed %s", e)
        return 0
    return pruned


# ============================================================
# 启动自检（D1-4 崩溃恢复）
# ============================================================

def self_heal(state, baby_id: str) -> int:
    """
    启动自检：修复 jsonl 与 state.memories 的不一致。

    场景：进程在 append_life_moment（Step 3）与 state.memories.append（Step 4）
    之间崩溃，jsonl 有孤儿 moment 但 state.memories 缺少对应降级条目。

    修复策略：
    - 扫描 life_moments.jsonl 全量
    - 若 len(life_moments) > len(state.memories)，取差集的末尾 moments 补 _downgrade_to_memory
    - 保持幂等，已一致时零操作

    返回：补齐条数。
    """
    if state is None or not hasattr(state, "memories"):
        return 0
    try:
        moment_count = store.count_life_moments(baby_id)
    except Exception:
        return 0
    mem_count = len(state.memories)
    if moment_count <= mem_count:
        return 0

    # 补齐：加载最后 (moment_count - mem_count) 条
    diff = moment_count - mem_count
    try:
        tail = store.load_recent_moments(baby_id, limit=diff)
    except Exception as e:
        logger.warning("self_heal: load tail failed %s", e)
        return 0

    added = 0
    for m in tail:
        try:
            state.memories.append(_downgrade_to_memory(m))
            added += 1
        except Exception as e:
            logger.warning("self_heal: downgrade append failed seq=%s err=%s", m.seq, e)
    if added:
        logger.info("memory.self_heal: baby=%s repaired %d state.memories entries", baby_id, added)
    return added
