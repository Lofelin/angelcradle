# Delta for Agent State

## MODIFIED Requirements

### Requirement: BabyState 扩展
BabyState SHALL 新增以下字段以支持自驱动生命系统。

#### Scenario: life_tags 持久化
- GIVEN BabyState 的 `life_tags = {"enrolled_school", "has_pet"}`
- WHEN 调用 `save_state(state)`
- THEN `life_tags` 作为列表序列化到 JSON
- AND `load_state()` 恢复为 set

#### Scenario: sim_time 持久化
- GIVEN BabyState 的 `sim_time = 1680.0`（70 天 × 24 小时）
- WHEN 调用 `save_state(state)`
- THEN `sim_time` 持久化
- AND 进程重启后可恢复调度

#### Scenario: last_active_ts 初始化
- GIVEN 一个旧版 BabyState JSON 不包含 `last_active_ts`
- WHEN `from_dict()` 加载
- THEN `last_active_ts` 默认为 0.0
- AND 首次注册到调度器时设为 `time.time()`

#### Scenario: time_scale 默认值
- GIVEN 一个新创建的 BabyState
- WHEN 未指定 time_scale
- THEN 默认为 `"normal"`（1 现实小时 = 7 模拟天）

## ADDED Requirements

### Requirement: 模拟时间到日龄映射
系统 SHALL 根据 `sim_time` 自动计算 `age_days`。

#### Scenario: age_days 随模拟时间增长
- GIVEN Agent 的 `sim_time` 从 0 增长到 720（30 天 × 24 小时）
- WHEN 模拟时间推进
- THEN `age_days` 更新为 30

#### Scenario: age_days 不超过当前阶段上限
- GIVEN Agent 处于 phase 0（新生儿期，age_days 上限 30）
- WHEN `sim_time` 推进到超过 720 小时
- THEN `age_days` 保持为 30，不继续增长
- AND 阶段推进仍由 grow_stream 驱动
