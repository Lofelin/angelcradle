"""
遗忘曲线参数 + 闸门阈值 + 灰度开关常量。

Phase 0 说明：TAU_BY_PHASE 采用 Ebbinghaus 指数近似，参数基于粗略生物学量级估算，
非文献精调。v1 升级路径见 specs/long-term-memory/v1-deferred/README.md
（Wickelgren 幂律 + DG 成熟拐点 + REM/SWS 区分 + arousal/valence 拆分）。

[INPUT]: 无
[OUTPUT]: TAU_BY_PHASE, DEFAULT_TAU, JACCARD_THRESHOLD, LOW_INTENSITY,
          HIGH_INTENSITY, CAREGIVER_PREFIX, SELF_ACTOR, WORLD_ACTOR,
          PRUNE_SOFT_CAP, PRUNE_KEEP_TOP, RECENT_WINDOW,
          MEMORY_V2_ENV, PHASE_B_SPEC_ID
[POS]: memory/ 的常量配置层，被 ingest / recall / consolidation 消费
[PROTOCOL]: 变更时更新此头部，然后检查 CLAUDE.md
"""

from __future__ import annotations

# ============================================================
# 遗忘曲线（Ebbinghaus 指数近似，单位：天）
# ============================================================
# forget_score = intensity × exp(-Δ_days / (TAU_BY_PHASE[phase] × (1 + 0.5 × intensity)))

TAU_BY_PHASE: dict[int, int] = {
    0: 3,       # 新生儿
    1: 7,
    2: 14,
    3: 30,
    4: 60,
    5: 90,
    6: 180,
    7: 270,
    8: 365,
    9: 540,
    10: 720,
    11: 1080,   # 学龄前
}

DEFAULT_TAU = 180

# ============================================================
# 新颖性闸门（Selective Ingestion，D2 补强）
# ============================================================

JACCARD_THRESHOLD = 0.7    # 与近 RECENT_WINDOW 条的 Jaccard ≥ 此阈值视为重复
LOW_INTENSITY = 0.4        # intensity < 此值才走重复检测
HIGH_INTENSITY = 0.7       # intensity ≥ 此值强制入库（白名单）
RECENT_WINDOW = 20         # 新颖性判定窗口

# Actor 命名空间（保持稳定，避免字符串漂移）
SELF_ACTOR = "self"
WORLD_ACTOR = "world"
CAREGIVER_PREFIX = "caregiver:"

# ============================================================
# 惰性剪枝（软上限，防失控）
# ============================================================

PRUNE_SOFT_CAP = 500       # 超过此数触发剪枝
PRUNE_KEEP_TOP = 300       # 保留 top forget_score 条数

# ============================================================
# 灰度开关（D1 补强）
# ============================================================

MEMORY_V2_ENV = "MEMORY_V2"          # 环境变量名；值 "on"/"off"；默认 "on"

# 终结 spec id（D1-5：防灰度永久化）
# 阶段 A 的双写策略必须保持，直到 phase-b-unify-memory spec 满足触发条件并接管
PHASE_B_SPEC_ID = "phase-b-unify-memory"
