# Requirements: World Context Driven Event Emergence

## 背景

当前涌现事件系统采用固定事件池（91 个硬编码事件）+ 随机掷骰机制，存在事件重复、缺乏因果关系、cooldown 失效等严重问题。本需求用"世界快照"（World Snapshot）替代固定事件池，让 LLM 根据婴儿的生活环境和当前状态生成具有因果连贯性的涌现事件。

## 用户痛点

1. **事件严重重复**：Phase 8 仅 11 个环境事件可选，1460 天生命中同一事件反复出现
2. **事件缺乏因果关系**：第 217 天"听到雨声"，第 218 天"坐电梯"，第 220 天"雷暴"，不像真实天气模式
3. **Cooldown 形同虚设**：基于 memories 的去重机制无效（83% 事件不创建 memory）
4. **"first_X" 事件重复发生**：first_drawing 出现 13 次，违反语义
5. **关键事件无去重**：toilet_training 触发 17 次
6. **模板反应单一**：6 个模板无变化，体验贫乏

---

## US-1: 世界快照生成

**作为** 模拟系统，**我想** 每隔 N 个模拟天由 LLM 生成一份"世界快照"，描述当前周期的天气模式、家庭动态、和可用刺激源，**以便** 涌现事件具有时间连贯性和因果关系。

### 验收标准

- **AC-1.1**: When 模拟推进到快照刷新日（每 7 模拟天一次），the system shall 调用 LLM 生成一份 WorldSnapshot，包含天气模式、家庭事件弧线、和当日候选涌现事件列表。
- **AC-1.2**: When LLM 生成 WorldSnapshot 时，the system shall 将婴儿的 life_tags、current_phase、age_days、recent memories（最近 5 条）、当前压力水平作为 prompt 上下文传入。
- **AC-1.3**: When WorldSnapshot 生成成功，the system shall 缓存该快照直到下一个刷新周期（7 天后），每日从缓存的候选列表中选取事件。
- **AC-1.4**: When 快照中的天气模式为"连续雨天"，the system shall 在该周期内的多天中产出与雨天相关的事件（如听雨声、室内活动增加、看窗外雨景），而非随机跳到"晴天户外"。
- **AC-1.5**: When WorldSnapshot 包含一个多日事件弧线（如"家里来客人"），the system shall 在弧线覆盖的天数内产出与该弧线相关的事件序列。

---

## US-2: 每日事件选取

**作为** 调度器，**我想** 从当前世界快照的候选事件中按日选取涌现事件，**以便** 每天的事件与世界上下文一致且不重复。

### 验收标准

- **AC-2.1**: When 调度器运行 _run_day 时，the system shall 从当前 WorldSnapshot 的候选事件列表中选取当天的涌现事件，而非从固定事件池随机抽取。
- **AC-2.2**: When 候选列表中有标记为当天应发生的事件（day_index 匹配），the system shall 优先选取该事件。
- **AC-2.3**: When 候选列表中无当天事件或所有候选已用完，the system shall 按概率决定是否触发"意外事件"（快照中的 surprise 槽位），概率沿用现有 25% 基础值 + 压力调制。
- **AC-2.4**: When 某个候选事件已在本周期内被选取过，the system shall 不再重复选取同一事件（周期内去重）。

---

## US-3: 关键事件去重与规则驱动

**作为** 模拟系统，**我想** 关键事件（critical category）保留规则驱动且加入全局去重，**以便** naming_ceremony、toilet_training 等里程碑事件不会重复触发。

### 验收标准

- **AC-3.1**: When 关键事件已在 state.memories 或 state.milestones 中有记录，the system shall 不再触发同名关键事件。
- **AC-3.2**: When "first_X" 类事件（name 以 "first_" 开头）已触发过一次，the system shall 将其从候选池中永久移除（通过 life_tags 或 triggered_events 集合追踪）。
- **AC-3.3**: When 关键事件被触发，the system shall 立即将事件名记录到 BabyState.triggered_events 集合中，用于后续去重判断。
- **AC-3.4**: Where 关键事件需要父母介入（requires_parent=True），the system shall 继续将其写入 pending_criticals 队列，行为与当前一致。

---

## US-4: LLM 降级回退

**作为** 模拟系统，**我想** 在 LLM 调用失败时自动回退到固定事件池，**以便** 系统在 LLM 不可用时仍能正常运行。

### 验收标准

- **AC-4.1**: When LLM 生成 WorldSnapshot 失败（超时、解析错误、网络异常），the system shall 回退到当前 roll_emergent_event 逻辑（固定事件池 + 随机掷骰），并记录 warning 日志。
- **AC-4.2**: When 降级发生时，the system shall 在下一个快照刷新点重新尝试 LLM 生成，而非永久降级。
- **AC-4.3**: When 降级到固定事件池时，the system shall 应用 US-3 的去重规则（关键事件去重、first_X 去重）。

---

## US-5: 向后兼容

**作为** 已有用户，**我想** 旧的 BabyState 数据能正常加载，**以便** 已运行的模拟不受影响。

### 验收标准

- **AC-5.1**: When 加载不含 world_snapshot 字段的旧 BabyState JSON，the system shall 使用默认值（None/空）初始化新字段，不报错。
- **AC-5.2**: When 加载不含 triggered_events 字段的旧 BabyState JSON，the system shall 初始化为空集合。
- **AC-5.3**: Where 旧数据中存在 memories 和 milestones，the system shall 在首次快照生成前从中推断 triggered_events（重建去重集合）。

---

## US-6: LLM 调用预算控制

**作为** 系统运营者，**我想** 世界快照的 LLM 调用总量在可控范围内，**以便** API 成本不会失控。

### 验收标准

- **AC-6.1**: When 快照刷新间隔为 7 天，1460 天总生命周期的 WorldSnapshot LLM 调用次数 shall 不超过 209 次。
- **AC-6.2**: When 系统处于 fast 时间比例（1 real hour = 30 sim days），快照生成 shall 不因速度加快而增加每周期超过 1 次 LLM 调用。
- **AC-6.3**: Where LLM semaphore 已满（3 并发），WorldSnapshot 生成 shall 排队等待而非跳过。
