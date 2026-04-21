# Requirements: Lifeline Redesign

## 背景

Angel Cradle 自驱动生命系统当前架构存在四个核心缺陷：事件生产与 SSE 投递耦合导致重复/丢失、阶段推进速度不可接受（2555 天 x 8 事件需数小时）、前端连接状态影响后端生命进程、LLM 执行时前端无反馈。本次重构旨在彻底解耦事件生产与消费，引入日志即真相架构，10 分钟内跑完 12 阶段。

---

## US-1: 日志即真相 -- 事件生产与消费解耦

**作为** 后端调度器，  
**我需要** 将事件写入 events.jsonl 而不关心是否有 SSE 订阅者，  
**以便** 事件永不丢失，且前端连接/断连不影响生命进程。

### 验收标准

- **AC-1.1**: 当 scheduler 处理一个事件时，系统应将事件以 JSONL 格式追加到 `nursery/{baby_id}/events.jsonl`，且事件中包含单调递增的 `seq` 字段（从 1 开始）。
- **AC-1.2**: 当没有任何 SSE 客户端连接时，系统应正常写入事件到 events.jsonl，不丢失任何事件。
- **AC-1.3**: 当多个 SSE 客户端同时连接时，系统应各自独立推送，不影响日志写入。
- **AC-1.4**: 当 scheduler 写入事件后，系统应通过 `asyncio.Event` 通知机制唤醒等待中的 SSE 读取器。

---

## US-2: 客户端游标 -- 无状态断点续传

**作为** 前端客户端，  
**我需要** 通过 `after_seq` 参数连接 SSE 端点并从指定位置继续接收事件，  
**以便** 断连重连后不丢失也不重复事件。

### 验收标准

- **AC-2.1**: 当前端请求 `GET /cradle/{baby_id}/lifeline?after_seq=0` 时，系统应从 events.jsonl 的第一条事件开始推送。
- **AC-2.2**: 当前端请求 `GET /cradle/{baby_id}/lifeline?after_seq=N` 时，系统应只推送 `seq > N` 的事件。
- **AC-2.3**: 当回放历史事件时，系统应以 50ms/条的节奏推送（快速回放）。
- **AC-2.4**: 当历史事件回放完毕后，系统应切换到实时模式，通过 `asyncio.Event` 等待新事件。
- **AC-2.5**: 当 2 秒内无新事件时，系统应推送 `sim_tick` 心跳事件（含当前 sim_day/sim_hour）。
- **AC-2.6**: 当前端断连后重连时，系统应根据 `after_seq` 自动从断点继续，服务端无需维护客户端状态。

---

## US-3: 时间跳跃 -- 10 分钟跑完 12 阶段

**作为** 调度器，  
**我需要** 以批量计算 routine 事件 + LLM 预算控制涌现事件的方式推进生命，  
**以便** 12 阶段（2555 天）在 10 分钟内完成。

### 验收标准

- **AC-3.1**: 当处理 routine 事件（feeding/nap/sleep 等）时，系统应通过规则引擎批量计算状态变化，不调用 LLM。
- **AC-3.2**: 当连续多日无涌现事件时，系统应将平静日压缩为一条 `day_summary` 日志（含日数范围和累计状态变化）。
- **AC-3.3**: 每阶段 LLM 调用预算应约为 6 次（5 story events + 1 phase summary），12 阶段总计约 72 次。
- **AC-3.4**: 当涌现事件被判定为 story_worthy 时，系统应调用 LLM 生成叙事；否则使用模板化反应。
- **AC-3.5**: 当 LLM 调用完成时，系统应受 semaphore（3 并发）限流。
- **AC-3.6**: 12 阶段的总运行时间应不超过 10 分钟（72 次 LLM / 3 并发 x 15s = 360s ~ 6 分钟）。

---

## US-4: Story-Worthy 判断 -- 涌现事件分级

**作为** 调度器，  
**我需要** 对涌现事件进行 story_worthy 判断，  
**以便** LLM 调用聚焦在真正值得叙事的事件上。

### 验收标准

- **AC-4.1**: 当涌现事件是婴儿首次经历（该事件名未出现在 memories 中）时，系统应判定为 story_worthy。
- **AC-4.2**: 当涌现事件的 intensity >= 0.5 时，系统应判定为 story_worthy。
- **AC-4.3**: 当涌现事件的 sensory_channels 与婴儿 identity 的 dominant sense 匹配时，系统应判定为 story_worthy。
- **AC-4.4**: 当涌现事件未被判定为 story_worthy 时，系统应使用模板化反应（预定义文本 + 状态微调），不调用 LLM。
- **AC-4.5**: 每阶段 story_worthy 事件数量应有上限（默认 5），超出后降级为模板化反应。

---

## US-5: 前端游标管理 -- 最小改动适配

**作为** 前端，  
**我需要** 将 SSE 连接切换到 lifeline 端点并管理 last_seq，  
**以便** 断连重连无缝衔接。

### 验收标准

- **AC-5.1**: 当前端连接 SSE 时，系统应使用 `EventSource(\`/cradle/{baby_id}/lifeline?after_seq=${lastSeq}\`)` 替代旧的 heartbeat/stream。
- **AC-5.2**: 当前端收到事件时，系统应从事件的 `seq` 字段更新 `localStorage` 中的 `lastSeq_{baby_id}`。
- **AC-5.3**: 当前端首次连接（无 localStorage 记录）时，系统应使用 `after_seq=0` 从头开始。
- **AC-5.4**: 当 `heartbeat/stream` 端点被请求时，系统应返回 301 重定向到 `lifeline` 端点（向后兼容）。

---

## US-6: 家长互动插入 -- interact API 兼容

**作为** 家长用户，  
**我需要** 在生命线运行期间通过 interact API 与婴儿互动，  
**以便** 互动事件被正确记录到 events.jsonl 并通过 lifeline SSE 推送。

### 验收标准

- **AC-6.1**: 当 interact API 被调用时，系统应将互动事件写入 events.jsonl（带 seq），并触发 notify 通知 SSE 读取器。
- **AC-6.2**: 当 intervene API（关键事件介入）被调用时，系统应同样写入 events.jsonl 并通知。
- **AC-6.3**: 当外部事件（interact/intervene）插入时，系统应不中断正在运行的 scheduler 主循环。

---

## US-7: 阶段推进整合 -- 消除双轨并存

**作为** 系统架构，  
**我需要** 将 nanny.py 的 simulate_phase_stream / complete_phase 逻辑整合进新 scheduler，  
**以便** 只有一套阶段推进路径，消除代码重复和状态不一致风险。

### 验收标准

- **AC-7.1**: 当 scheduler 检测到阶段边界时，系统应在新 scheduler 内部执行阶段推进（调用 nanny 的核心逻辑），不通过旧的 `_run_phase_transition` 间接调用。
- **AC-7.2**: 当阶段推进完成时，系统应写入 `phase_completed` 事件到 events.jsonl。
- **AC-7.3**: 旧的 `/advance/stream` 和 `/grow/stream` 端点应保留为手动触发/调试路径，但主路径由 scheduler 驱动。

---

## US-8: LLM 执行反馈 -- 前端可见

**作为** 前端用户，  
**我需要** 在 LLM 处理期间看到"正在思考..."的提示，  
**以便** 知道系统在工作而非卡死。

### 验收标准

- **AC-8.1**: 当 scheduler 开始 LLM 调用时，系统应先写入 `autonomous_processing` 事件到 events.jsonl。
- **AC-8.2**: 当 LLM 调用完成后，系统应写入最终结果事件（autonomous_event）。
- **AC-8.3**: 前端收到 `autonomous_processing` 事件时应显示加载指示器。

---

## 非功能需求

### NFR-1: 性能
- 12 阶段（2555 天）总运行时间 <= 10 分钟
- Routine 事件批量处理速度 >= 100 事件/秒
- SSE 回放速度：50ms/条（可配置）

### NFR-2: 可靠性
- events.jsonl 使用追加写入，崩溃后不丢失已写入事件
- seq 序列号严格单调递增，不跳号、不重复
- 前端断连重连后事件完整性 100%

### NFR-3: 向后兼容
- interact API 签名不变
- intervene API 签名不变
- heartbeat/stream 端点重定向到 lifeline
- 现有 events.jsonl 数据可平滑迁移（为旧事件补充 seq）

### NFR-4: 资源控制
- LLM 并发上限 3（semaphore）
- 每阶段 LLM 调用上限约 6 次
- 连续平静日压缩（不生成逐条日志）
