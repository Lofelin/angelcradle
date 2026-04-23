"""
摇篮发育本体论静态表：per-dimension 发育期 + capability → dim 路由。

[INPUT]: 无外部依赖；phase_index 参数引用 cradle.phases.PHASES 索引
[OUTPUT]: DIMENSION_PHASES / CAPABILITY_DIMENSION_MAP / current_phase_for / capability_dimension /
          iter_dimension_phases / DIMENSIONS / KNOWN_PHASE_STAGES
[POS]: cradle/ 的领域知识静态源，被 cradle/graph_emit.py 的 edge_occurs_in 路由消费、
       被未来 cradle/validate.py 校验 BELONGS_TO 覆盖使用
[PROTOCOL]: 变更时更新此头部，然后检查 cradle/CLAUDE.md

本体论来源
==========
per-dimension phase 划分对齐：
  - motor / cognitive          → Piaget 感觉运动-前运算期切分 + Bayley-III 粗细动作曲线
  - language                   → McArthur-Bates CDI / cooing→babble→first_word→sentence→narrative
  - social                     → Vineland-3 Interpersonal subdomain
  - emotional                  → Self-conscious emotions 发育时间线（Lewis 1995）
  - physical                   → WHO MGRS 生长曲线区段

capability → dim 路由以 cradle.phases.PHASES 各阶段 capabilities 字段为事实基础，
补充少量 nanny.py / heartbeat_provider.py 里出现、但未写进 phases.capabilities 的
常用能力（self_regulation / transitional_object / imaginary_friend 等），
避免 edge_occurs_in 在业务代码新增能力时 KeyError。
"""

from __future__ import annotations

from typing import Iterator

# ============================================================
# 6 维枚举
# ============================================================

DIMENSIONS: tuple[str, ...] = (
    "motor",
    "cognitive",
    "language",
    "social",
    "emotional",
    "physical",
)


# ============================================================
# per-dimension 发育期
#   key   = dim
#   value = [(stage_name, (month_lo, month_hi), age_range_display_zh, age_range_display_en), ...]
#
# 月龄边界采用左闭右开；末段 hi 取 84（7 岁，摇篮上限）。
# 相邻 stage 的 hi/lo 必须首尾相接（current_phase_for 依赖这点）。
# ============================================================

DIMENSION_PHASES: dict[str, list[tuple[str, tuple[float, float], str, str]]] = {
    "motor": [
        ("neonatal",       (0,  1),  "0-1 个月",  "0-1 mo"),
        ("early_infant",   (1,  6),  "1-6 个月",  "1-6 mo"),
        ("late_infant",    (6, 12),  "6-12 个月", "6-12 mo"),
        ("toddler",        (12, 36), "1-3 岁",    "1-3 yr"),
        ("preschool",      (36, 84), "3-7 岁",    "3-7 yr"),
    ],
    "cognitive": [
        ("sensorimotor_reflex", (0,  3),  "0-3 个月",  "0-3 mo"),
        ("primary_circular",    (3,  9),  "3-9 个月",  "3-9 mo"),
        ("coordination",        (9, 18),  "9-18 个月", "9-18 mo"),
        ("symbolic",            (18, 36), "1.5-3 岁",  "1.5-3 yr"),
        ("preoperational",      (36, 84), "3-7 岁",    "3-7 yr"),
    ],
    "language": [
        ("cry",          (0,  2),  "0-2 个月",  "0-2 mo"),
        ("cooing",       (2,  4),  "2-4 个月",  "2-4 mo"),
        ("babble",       (4, 12),  "4-12 个月", "4-12 mo"),
        ("first_words",  (12, 18), "1-1.5 岁",  "1-1.5 yr"),
        ("sentence",     (18, 36), "1.5-3 岁",  "1.5-3 yr"),
        ("narrative",    (36, 84), "3-7 岁",    "3-7 yr"),
    ],
    "social": [
        ("imprint",        (0,  3),  "0-3 个月",  "0-3 mo"),
        ("recognize",      (3,  6),  "3-6 个月",  "3-6 mo"),
        ("attachment",     (6, 18),  "6-18 个月", "6-18 mo"),
        ("parallel_play",  (18, 36), "1.5-3 岁",  "1.5-3 yr"),
        ("cooperative",    (36, 60), "3-5 岁",    "3-5 yr"),
        ("moral",          (60, 84), "5-7 岁",    "5-7 yr"),
    ],
    "emotional": [
        ("reflex_affect",    (0,  3),  "0-3 个月",  "0-3 mo"),
        ("primary_emotions", (3, 12),  "3-12 个月", "3-12 mo"),
        ("self_awareness",   (12, 36), "1-3 岁",    "1-3 yr"),
        ("empathy",          (36, 60), "3-5 岁",    "3-5 yr"),
        ("regulation",       (60, 84), "5-7 岁",    "5-7 yr"),
    ],
    "physical": [
        ("neonate",         (0,  1),  "0-1 个月",   "0-1 mo"),
        ("early_infant",    (1, 12),  "1-12 个月",  "1-12 mo"),
        ("toddler_body",    (12, 36), "1-3 岁",     "1-3 yr"),
        ("preschool_body",  (36, 84), "3-7 岁",     "3-7 yr"),
    ],
}


# 已知的 (dim, stage) 元组集合——校验器与 edge 构造器的合法目标白名单。
KNOWN_PHASE_STAGES: frozenset[tuple[str, str]] = frozenset(
    (dim, stage) for dim, phases in DIMENSION_PHASES.items() for stage, *_ in phases
)


# ============================================================
# capability → dimension 路由表
# ============================================================

CAPABILITY_DIMENSION_MAP: dict[str, str] = {
    # ---- motor ----
    "startle_reflex":      "motor",
    "sucking_reflex":      "motor",
    "head_control":        "motor",
    "rolling":             "motor",
    "grasping":            "motor",
    "hand_discovery":      "motor",
    "reach_for_objects":   "motor",
    "sitting":             "motor",
    "crawling":            "motor",
    "pointing":            "motor",
    "walking":             "motor",
    "running":             "motor",
    "tool_use":            "motor",
    "fine_motor":          "motor",

    # ---- cognitive ----
    "visual_tracking":      "cognitive",
    "sound_localization":   "cognitive",
    "object_permanence":    "cognitive",
    "intentional_action":   "cognitive",
    "simple_cause_effect":  "cognitive",
    "pretend_play":         "cognitive",
    "self_recognition":     "cognitive",
    "basic_counting":       "cognitive",
    "analogy":              "cognitive",
    "time_concept":         "cognitive",
    "hypothetical_thinking":"cognitive",
    "reading_readiness":    "cognitive",
    "future_planning":      "cognitive",
    "imaginary_friend":     "cognitive",

    # ---- language ----
    "crying":               "language",
    "babbling_syllables":   "language",
    "first_words":          "language",
    "word_combination":     "language",
    "two_word_sentences":   "language",
    "full_sentences":       "language",
    "why_questions":        "language",

    # ---- social ----
    "social_smile":         "social",
    "stranger_anxiety":     "social",
    "imitation":            "social",
    "peer_awareness":       "social",
    "role_play":            "social",
    "sharing_concept":      "social",
    "moral_sense":          "social",
    "rule_following":       "social",
    "boundary_testing":     "social",
    "negotiation":          "social",
    "basic_empathy":        "social",
    "independent_opinion":  "social",
    "self_advocacy":        "social",

    # ---- emotional ----
    "laugh":                "emotional",
    "emotional_storms":     "emotional",
    "complex_emotion":      "emotional",
    "self_regulation":      "emotional",
    "transitional_object":  "emotional",

    # ---- physical ----
    "sleep_wake_cycle":     "physical",
    "toilet_trained":       "physical",
    "room_separated":       "physical",
}


# ============================================================
# cradle.phases.PHASES 索引 → 月龄中点
# ============================================================
# 拷贝 phases.PHASES 的 age_days 区间以避免 import 循环（ontology 被 graph_emit 引用，
# graph_emit 未来可能被 nanny 引用，nanny 引用 phases；短链单向避免循环）。
# 若 phases.PHASES 的月龄变动，本表必须同步（由单测守门）。
_PHASE_INDEX_AGE_DAYS: tuple[tuple[int, int], ...] = (
    (0, 30),       # 0 neonatal
    (30, 90),      # 1 sensory_awakening
    (90, 180),     # 2 body_discovery
    (180, 270),    # 3 object_permanence
    (270, 365),    # 4 locomotion
    (365, 540),    # 5 first_word
    (540, 730),    # 6 language_explosion
    (730, 1095),   # 7 why_phase
    (1095, 1460),  # 8 social_budding
    (1460, 1825),  # 9 rule_understanding
    (1825, 2190),  # 10 abstract_beginning
    (2190, 2555),  # 11 independence
)


def phase_index_to_month(phase_index: int) -> float:
    """cradle.phases.PHASES 索引 → 月龄中点（days / 30）。"""
    if not 0 <= phase_index < len(_PHASE_INDEX_AGE_DAYS):
        raise ValueError(f"phase_index out of range [0, 11]: {phase_index}")
    lo, hi = _PHASE_INDEX_AGE_DAYS[phase_index]
    return (lo + hi) / 2.0 / 30.0


# ============================================================
# 路由函数
# ============================================================

def capability_dimension(cap_key: str) -> str:
    """capability_key → dim；未知 key raise KeyError（业务代码新加能力时必须补表）。"""
    try:
        return CAPABILITY_DIMENSION_MAP[cap_key]
    except KeyError:
        raise KeyError(
            f"Unknown capability '{cap_key}'. 新增能力时请在 "
            f"backend/cradle/ontology.py CAPABILITY_DIMENSION_MAP 补条目。"
        )


def current_phase_for(dim: str, phase_index: int) -> str:
    """(dim, phase_index) → per-dim stage name。

    按 cradle.phases.PHASES 索引对应的月龄中点，在该 dim 的 DIMENSION_PHASES
    分段表里找归属 stage。末段兜底。
    """
    if dim not in DIMENSION_PHASES:
        raise KeyError(f"Unknown dimension '{dim}', must be one of {DIMENSIONS}")
    month = phase_index_to_month(phase_index)
    phases = DIMENSION_PHASES[dim]
    for stage_name, (lo, hi), *_ in phases:
        if lo <= month < hi:
            return stage_name
    return phases[-1][0]


def iter_dimension_phases() -> Iterator[tuple[str, str, tuple[float, float], str, str]]:
    """扁平化遍历：(dim, stage, (month_lo, month_hi), age_zh, age_en)。

    供 graph_emit 首次初始化时批量 emit 所有 dimension/phase 节点使用。
    """
    for dim in DIMENSIONS:
        for stage, months, age_zh, age_en in DIMENSION_PHASES[dim]:
            yield dim, stage, months, age_zh, age_en
