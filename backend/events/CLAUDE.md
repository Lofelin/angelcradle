# events/
> L2 | 父级: /CLAUDE.md

共享事件基础设施——供摇篮和世界层共用的事件模型、定义、过滤和权重调制。

## 成员清单

__init__.py: Event 数据类（含 hour_range/requires_tags/excludes_tags/duration_hours/generates_next）+ route_events() 三重过滤 + roll_emergent_event() 涌现事件
definitions.py: 全部事件常量定义（13 日常 + 19 环境 + 16 关键 + 15 日程骨架 = 63 种）+ ALL_EVENTS + get_event()
modifiers.py: _compute_affinity() 身份亲和度 + _phase_weight_modifier() 阶段权重调制（睡眠回退高发期/tantrum 曲线/压力敏感度）

## 对外暴露

```python
from events import Event, route_events, roll_emergent_event
from events.definitions import DAILY_EVENTS, ENVIRONMENT_EVENTS, CRITICAL_EVENTS, SCHEDULE_EVENTS, ALL_EVENTS, get_event
from events.modifiers import _compute_affinity, _phase_weight_modifier
```

## 依赖关系

- 无外部模块依赖（纯数据模型 + 过滤/调制逻辑）
- 被 cradle/events.py（thin wrapper）、未来 world.py / scheduler.py 消费

[PROTOCOL]: 变更时更新此文档，然后检查 CLAUDE.md
