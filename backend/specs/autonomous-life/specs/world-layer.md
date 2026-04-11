# Delta for World Layer

## ADDED Requirements

### Requirement: 日程模板系统
系统 SHALL 根据 Agent 的阶段和 life_tags 选择日程模板，生成每日日程骨架。

#### Scenario: 新生儿日程
- GIVEN Agent 处于 phase 0-1（新生儿期）
- WHEN 生成日程
- THEN 使用吃睡循环模板（约 6 个事件：起床/喂奶/小睡/喂奶/小睡/睡觉）

#### Scenario: 学龄儿童日程
- GIVEN Agent 处于 phase 9+（学龄期）且 life_tags 包含 `enrolled_school`
- WHEN 生成日程
- THEN 使用上学作息模板（约 10 个事件：起床/早餐/上学/午饭/下午课/放学/晚饭/作业/家庭时间/睡觉）

#### Scenario: 未上学的同龄儿童
- GIVEN Agent 处于 phase 9+ 但 life_tags 不包含 `enrolled_school`
- WHEN 生成日程
- THEN 使用家庭活动模板（不含 school 相关事件）

#### Scenario: 日程随机化
- GIVEN 日程模板定义了事件时间
- WHEN 生成具体日程时
- THEN 每个事件的时间在模板基础上 ±30 分钟随机偏移
- AND 保持事件的先后顺序不变

### Requirement: 日程链式生成
系统 SHALL 支持边活边长的事件队列，而非一次生成全天日程。

#### Scenario: 事件链式推进
- GIVEN 处理完 `wake_up` 事件
- WHEN `wake_up.generates_next = "breakfast"`
- THEN 在当前时间 + duration_hours 后插入 `breakfast` 事件
- AND 不预先生成全天所有事件

#### Scenario: 一天结束时生成次日
- GIVEN 处理完 `sleep` 事件
- WHEN `sleep` 是当日最后一个日程事件
- THEN 生成次日的第一个事件（`wake_up`）插入队列

### Requirement: 事件处理分层
系统 SHALL 区分日常事件（规则引擎）和有"事"事件（LLM）。

#### Scenario: 日常事件规则处理
- GIVEN 事件类别为 `daily`（如 feeding, sleeping, wake_up）
- WHEN 调度器处理该事件
- THEN 使用规则引擎更新状态（压力衰减/饱腹度/睡眠质量）
- AND 不调用 LLM
- AND 产出 `autonomous_routine` SSE 事件

#### Scenario: 有"事"事件 LLM 处理
- GIVEN 事件类别为 `environment` 或 `critical`
- WHEN 调度器处理该事件
- THEN 调用 LLM 生成时段总结（发生了什么、宝宝怎么反应、情绪变化）
- AND 创建 Memory 记录
- AND 产出 `autonomous_event` SSE 事件

#### Scenario: LLM 时段总结格式
- GIVEN LLM 处理一个有"事"事件
- WHEN 生成时段总结
- THEN 输出包含：事件描述、宝宝反应（符合 expression_mode 约束）、情绪变化、状态影响
- AND 总结长度不超过 100 字

### Requirement: Agent 生活上下文管理
系统 SHALL 管理每个 Agent 的 life_tags，并在适当时机自动更新。

#### Scenario: 阶段自动标签
- GIVEN Agent 进入 phase 9（规则理解期，4-5 岁）
- WHEN 阶段推进时
- THEN 自动添加 `enrolled_school` 到 life_tags（默认行为）

#### Scenario: 能力解锁触发标签
- GIVEN Agent 解锁 `walk_first_steps` 能力
- WHEN 能力解锁时
- THEN 自动添加 `can_walk` 到 life_tags

#### Scenario: 关键事件决策触发标签
- GIVEN 关键事件 `pet_encounter` 中父母选择了 `adopt_pet`
- WHEN 父母决策处理完成
- THEN 添加 `has_pet` 到 life_tags

#### Scenario: 事件后果触发标签变更
- GIVEN 涌现事件 `moving_house` 发生
- WHEN 事件处理完成
- THEN 移除 `lives_urban`，添加 `lives_suburban`（或反之，由事件参数决定）
