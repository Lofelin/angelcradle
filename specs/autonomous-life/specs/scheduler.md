# Delta for DES Scheduler

## ADDED Requirements

### Requirement: 离散事件调度器
系统 SHALL 提供一个常驻的 DES（离散事件模拟）调度器，管理所有 Agent 的生命线。

#### Scenario: 事件按模拟时间排序执行
- GIVEN 队列中有 (baby_A, sim_07:00, wake_up) 和 (baby_B, sim_07:30, wake_up)
- WHEN 调度器取队首
- THEN 先处理 baby_A 的 07:00 事件，再处理 baby_B 的 07:30 事件

#### Scenario: 无事件时等待
- GIVEN 队列中最早事件在 10 分钟后（现实时间）
- WHEN 调度器处理完当前事件
- THEN 调度器 sleep 直到下一事件到期或被新事件唤醒

#### Scenario: 多 Agent 并行管理
- GIVEN 100 个 Agent 注册在调度器中
- WHEN 调度器运行
- THEN 所有 Agent 的事件在同一个优先级队列中按时间排序处理

### Requirement: Agent 注册与注销
系统 SHALL 支持动态注册和注销 Agent。

#### Scenario: 新宝宝入摇篮时注册
- GIVEN 用户通过 `POST /cradle/admit` 将宝宝放入摇篮
- WHEN admit 完成
- THEN 宝宝自动注册到调度器，生成首日日程事件

#### Scenario: 进程重启后恢复
- GIVEN 调度器进程重启
- WHEN 启动时扫描所有摇篮中的宝宝
- THEN 每个宝宝根据 `sim_time` 和 `last_active_ts` 恢复调度

### Requirement: LLM 调用限流
系统 SHALL 限制 LLM 并发调用数。

#### Scenario: LLM 并发控制
- GIVEN `max_concurrent=3` 的信号量
- WHEN 4 个 Agent 同时需要 LLM 处理事件
- THEN 最多 3 个并发执行，第 4 个等待

### Requirement: 时间比例配置
系统 SHALL 支持每个 Agent 独立配置时间比例。

#### Scenario: 慢养模式
- GIVEN Agent 的 `time_scale="slow"`
- WHEN 现实时间过去 1 小时
- THEN 该 Agent 的模拟时间推进 1 天（24 模拟小时）

#### Scenario: 正常模式
- GIVEN Agent 的 `time_scale="normal"`
- WHEN 现实时间过去 1 小时
- THEN 该 Agent 的模拟时间推进 7 天（168 模拟小时）

#### Scenario: 快养模式
- GIVEN Agent 的 `time_scale="fast"`
- WHEN 现实时间过去 1 小时
- THEN 该 Agent 的模拟时间推进 30 天（720 模拟小时）

### Requirement: 追赶模式
系统 SHALL 在 Agent 重新连接时补跑离线期间的事件。

#### Scenario: 离线 10 小时后重连（normal 模式）
- GIVEN Agent 离线 10 小时，time_scale="normal"
- WHEN Agent 重新连接（SSE 或进程重启）
- THEN 系统补跑 70 天的模拟事件
- AND 日常事件用规则引擎快速跑（不调 LLM）
- AND 涌现事件暂存后批量调 LLM
- AND 前端收到 `autonomous_catchup` 摘要事件

#### Scenario: 追赶天数上限
- GIVEN 离线时间对应超过 90 模拟天
- WHEN 追赶计算
- THEN 最多追赶 90 天，超出部分丢弃
