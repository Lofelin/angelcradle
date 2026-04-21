"""
scheduler 包入口 -- 保持对外 API 不变。

外部代码使用:
    from scheduler import scheduler, TIME_SCALES, EVENT_PACE, signal_need_responded

[PROTOCOL]: 变更时更新此头部，然后检查 CLAUDE.md
"""

from scheduler.constants import TIME_SCALES, EVENT_PACE  # noqa: F401
from scheduler.events import signal_need_responded  # noqa: F401
from scheduler.core import LifelineScheduler  # noqa: F401

# 模块级单例
scheduler = LifelineScheduler()
