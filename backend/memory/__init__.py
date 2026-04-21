"""
memory/ 模块对外 API。

阶段 A（本 PR 范围）：数据模型 + 存储 + 写入口 + 新颖性闸门 + 遗忘分公式。
阶段 A 后续 PR：recall 读路径（PR-2）、业务接入（PR-3/4）、巩固（PR-5）、CI 保障 + 文档（PR-5/6）。
阶段 B 终结 spec：phase-b-unify-memory（见 forget_params.PHASE_B_SPEC_ID）。

[INPUT]: 依赖 memory.schema / store / ingest / forget_params
[OUTPUT]: 统一导出：数据类 + 写入口 + 闸门 + 开关 + 基础检索原语
[POS]: memory/ 的门面，对外是唯一导入锚点
[PROTOCOL]: 变更时更新此头部，然后检查 CLAUDE.md
"""

from __future__ import annotations

# 数据模型
from .schema import LifeMoment, Milestone, RecalledContext

# 写入口（本模块对业务代码开放的唯一 LifeMoment 写入路径）
from .ingest import (
    record_moment,
    record_milestone,
    should_ingest,
    is_v2_enabled,
    assert_invariant,
    _compute_forget_score,
    _tokens,
    _jaccard,
)

# 存储原语（主要给 recall / consolidation 用；业务代码也可用 load_life_moments 只读查询）
from .store import (
    append_life_moment,
    append_milestone,
    load_life_moments,
    load_milestones,
    load_recent_moments,
    count_life_moments,
    count_milestones,
    next_moment_seq,
    next_milestone_seq,
    rewrite_life_moments,
)

# 读取门面（D2 对齐：三层金字塔 + token_budget + tag 一跳倒排）
from .recall import (
    recall,
    build_memory_prompt_block,
    _legacy_recall,
    _estimate_tokens,
    _score,
)

# 巩固 / 剪枝 / 自检（PR-5）
from .consolidation import (
    recompute_forget_scores,
    prune_if_needed,
    self_heal,
)

# 常量
from .forget_params import (
    TAU_BY_PHASE,
    DEFAULT_TAU,
    JACCARD_THRESHOLD,
    LOW_INTENSITY,
    HIGH_INTENSITY,
    RECENT_WINDOW,
    CAREGIVER_PREFIX,
    SELF_ACTOR,
    WORLD_ACTOR,
    PRUNE_SOFT_CAP,
    PRUNE_KEEP_TOP,
    MEMORY_V2_ENV,
    PHASE_B_SPEC_ID,
)

__all__ = [
    # 数据模型
    "LifeMoment", "Milestone", "RecalledContext",
    # 写入口
    "record_moment", "record_milestone",
    "should_ingest", "is_v2_enabled", "assert_invariant",
    "_compute_forget_score",
    # 存储
    "append_life_moment", "append_milestone",
    "load_life_moments", "load_milestones", "load_recent_moments",
    "count_life_moments", "count_milestones",
    "next_moment_seq", "next_milestone_seq",
    "rewrite_life_moments",
    # 读取
    "recall", "build_memory_prompt_block",
    # 巩固/剪枝/自检
    "recompute_forget_scores", "prune_if_needed", "self_heal",
    # 常量
    "TAU_BY_PHASE", "DEFAULT_TAU",
    "JACCARD_THRESHOLD", "LOW_INTENSITY", "HIGH_INTENSITY", "RECENT_WINDOW",
    "CAREGIVER_PREFIX", "SELF_ACTOR", "WORLD_ACTOR",
    "PRUNE_SOFT_CAP", "PRUNE_KEEP_TOP",
    "MEMORY_V2_ENV", "PHASE_B_SPEC_ID",
    # 工具（测试可见）
    "_tokens", "_jaccard",
]
