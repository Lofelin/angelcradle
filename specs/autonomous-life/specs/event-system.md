# Delta for Event System

## ADDED Requirements

### Requirement: 共享事件基础设施
系统 SHALL 将事件系统从 `cradle/events.py` 拆出为独立的 `events/` 模块，供摇篮和世界共用。

#### Scenario: 事件时间窗口过滤
- GIVEN 一个事件定义 `school_class` 的 `hour_range=(8, 16)`
- WHEN 当前模拟时间为 03:00
- THEN 该事件不会被 `route_events()` 返回

#### Scenario: 事件 life context 过滤
- GIVEN 一个事件定义 `school_class` 的 `requires_tags=["enrolled_school"]`
- WHEN Agent 的 `life_tags` 不包含 `"enrolled_school"`
- THEN 该事件不会被 `route_events()` 返回

#### Scenario: 事件排斥标签过滤
- GIVEN 一个事件定义 `home_play` 的 `excludes_tags=["enrolled_school"]`
- WHEN Agent 的 `life_tags` 包含 `"enrolled_school"` 且当前为上学时间
- THEN 该事件不会被 `route_events()` 返回

### Requirement: 事件日程链
系统 SHALL 支持事件通过 `generates_next` 字段形成日程链。

#### Scenario: 日程事件链式生成
- GIVEN `wake_up` 事件的 `generates_next="breakfast"` 且 `duration_hours=0.5`
- WHEN `wake_up` 事件在 sim_time=7.0 处理完成
- THEN 系统自动在 sim_time=7.5 插入 `breakfast` 事件到优先级队列

### Requirement: 涌现事件掷骰
系统 SHALL 在每个日程事件处理后，以概率触发涌现事件。

#### Scenario: 涌现事件产生
- GIVEN 当前时间 10:00，Agent 在上学，压力 0.6
- WHEN 处理完 `school_morning` 事件后掷骰
- THEN 有 20-30% 概率从 environment/critical 事件池中选出一个涌现事件
- AND 涌现事件插入当前时间点的队列中

#### Scenario: 涌现事件概率调制
- GIVEN Agent 压力水平 > 0.5
- WHEN 掷骰涌现事件时
- THEN 负面涌现事件（intensity > 0.5）的概率增加 30%

## MODIFIED Requirements

### Requirement: Event 数据模型
Event 数据类 SHALL 扩展以下字段：
- `hour_range: tuple[int, int]` — 可发生的小时范围（0-24），默认 (0, 24)
- `requires_tags: list[str]` — 前置条件标签列表，默认空
- `excludes_tags: list[str]` — 排斥标签列表，默认空
- `duration_hours: float` — 事件持续时长（模拟小时），默认 1.0
- `generates_next: str | None` — 链式后续事件名，默认 None

#### Scenario: 向后兼容
- GIVEN 现有的 48 种事件定义未设置新字段
- WHEN 通过 `roll_events()` 调用
- THEN 行为与修改前完全一致（新字段使用默认值，不影响过滤）
