"""
调度器常量与配置。

[INPUT]: 无
[OUTPUT]: TIME_SCALES, EVENT_PACE, NEED_EVAL_INTERVAL, STORY_BUDGET, CRADLE_EXIT_PHASE
[POS]: scheduler/ 的纯数据叶子模块
[PROTOCOL]: 变更时更新此头部，然后检查 scheduler/CLAUDE.md
"""

# ============================================================
# 时间比例（被 api/cradle.py 和 state 消费）
# ============================================================

TIME_SCALES: dict[str, float] = {
    "slow":   24.0 / 3600,     # 1 real hour = 1 sim day
    "normal": 168.0 / 3600,    # 1 real hour = 7 sim days
    "fast":   720.0 / 3600,    # 1 real hour = 30 sim days
    "turbo":  8640.0 / 3600,   # 1 real hour = 360 sim days（开发验证专用）
}

# 可见事件之间的节奏延迟（秒），让生命线有呼吸感
EVENT_PACE: dict[str, float] = {
    "slow":   2.0,
    "normal": 0.3,
    "fast":   0.05,
    "turbo":  0.0,             # 无延迟
}

# 需求评估间隔（模拟天数）
NEED_EVAL_INTERVAL: dict[str, int] = {
    "slow":   2,
    "normal": 2,
    "fast":   2,
    "turbo":  9999,            # 实际不触发（turbo 跳过需求评估）
}

# 每阶段 story LLM 预算
STORY_BUDGET: dict[str, int] = {
    "slow":   5,
    "normal": 3,
    "fast":   2,
    "turbo":  1,               # 每阶段 1 次叙事（保留收割反馈回路）
}

# 摇篮出口：Phase 0-8（0-4岁），Phase 9+ 属于"世界"模块
CRADLE_EXIT_PHASE = 9  # exclusive，跑完 Phase 8 后出摇篮
