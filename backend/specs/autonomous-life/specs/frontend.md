# Delta for Frontend

## ADDED Requirements

### Requirement: 自主生命事件展示
前端 SHALL 在控制台面板中展示调度器推送的自主生命事件。

#### Scenario: 日常活动展示
- GIVEN SSE 收到 `autonomous_routine` 事件（如 wake_up, feeding）
- WHEN 渲染控制台日志
- THEN 显示为浅灰色的简短状态行（如 "07:00 起床 | 心情：平静"）
- AND 不占用过多视觉空间

#### Scenario: 有"事"事件展示
- GIVEN SSE 收到 `autonomous_event` 事件（含时段总结）
- WHEN 渲染控制台日志
- THEN 显示为醒目的事件卡片，包含：事件名称、时段总结、情绪变化
- AND 如果有新记忆/新恐惧/新偏好，显示状态变化标签

#### Scenario: 追赶摘要展示
- GIVEN SSE 收到 `autonomous_catchup` 事件
- WHEN 渲染控制台日志
- THEN 显示为折叠的摘要卡片（如 "你不在的 3 天里，宝宝经历了..."）
- AND 可展开查看详细的每日事件列表

### Requirement: 心跳 SSE 统一连接
前端 SHALL 通过同一个 SSE 连接接收所有生命信号。

#### Scenario: SSE 事件分发
- GIVEN 前端连接到 `/{baby_id}/heartbeat/stream`
- WHEN 收到不同类型的事件
- THEN `autonomous_routine` → 控制台日志
- AND `autonomous_event` → 控制台日志 + 聊天面板（如果有内容）
- AND `heartbeat_initiative` → 控制台日志 + 聊天面板（现有行为）
- AND `heartbeat_ignored` → 控制台日志 + 聊天面板（现有行为）

## MODIFIED Requirements

### Requirement: 心跳 SSE 连接条件
前端 SHALL 在宝宝被选中时即连接 SSE，不依赖聊天面板状态。

#### Scenario: 无聊天面板时仍连接
- GIVEN 用户选中一个宝宝但未打开聊天面板
- WHEN 组件挂载
- THEN 仍连接 heartbeat/stream SSE
- AND 自主生命事件在控制台中可见
