# Plan: lifeline-redesign

## Tasks

- [ ] 1. 事件日志基础设施（cradle/state.py）
  - [ ] 1.1 新增 `_seq_counters` / `_seq_locks` 模块级变量和 `_get_seq_lock()` / `_next_seq()` / `_count_lines()` 辅助函数
  - [ ] 1.2 重构 `append_event()`: 签名改为返回 `int`，内部加 per-baby threading.Lock，分配 seq，写入 `{"seq": N, "ts": ..., ...}`
  - [ ] 1.3 新增 `_notify_events` 模块级变量和 `get_notify(baby_id)` 函数（返回 `asyncio.Event`）
  - [ ] 1.4 在 `append_event()` 末尾调用 `get_notify(baby_id).set()` 触发通知
  - [ ] 1.5 新增 `load_events_after(baby_id, after_seq)` 函数：扫描 events.jsonl 返回 seq > after_seq 的事件列表，兼容旧数据（无 seq 字段时按行号补充）
  - [ ] 1.6 更新 `load_events()` 返回的事件也包含 seq 字段（兼容现有 `/events` 端点）
  - [ ] 1.7 更新 L3 头部注释（新增 `get_notify`, `load_events_after` 到 OUTPUT）
  - [ ] 1.8 **测试**: 验证 append_event 写入的 seq 严格递增；验证 load_events_after 正确过滤；验证旧数据兼容

- [ ] 2. Story-Worthy 判断 + 模板化反应（world.py）
  - [ ] 2.1 新增 `is_story_worthy(event, state)` 函数：首次经历 / intensity >= 0.5 / 主导感官匹配 → True
  - [ ] 2.2 新增 `TEMPLATE_REACTIONS` 字典：按 `{category}_{low|high}` 分档，每档 2-3 条中文模板
  - [ ] 2.3 新增 `template_reaction(event, state)` 函数：选模板 + 格式化 + stress 微调，返回 `{"summary": ..., "stress_delta": ...}`
  - [ ] 2.4 更新 L3 头部注释（新增 `is_story_worthy`, `template_reaction` 到 OUTPUT）
  - [ ] 2.5 **测试**: 验证首次经历返回 True；验证低强度非首次返回 False；验证模板反应格式正确

- [ ] 3. LifelineScheduler 核心（scheduler.py）
  - [ ] 3.1 新建 `LifelineScheduler` 类：`__init__`（`_agents`, `_llm_semaphore`, `_running`）
  - [ ] 3.2 实现 `register(baby_id)`: 取消旧 task（如有），创建 `asyncio.create_task(_run_life)`
  - [ ] 3.3 实现 `unregister(baby_id)`: 取消 task
  - [ ] 3.4 实现 `_run_life(baby_id)`: 加载 state，遍历 phases，调用 `_run_phase` + `_complete_phase`，结束写入 `life_complete`
  - [ ] 3.5 实现 `_run_phase(baby_id, state, phase_idx)`: 日循环，story_budget 控制，quiet_days 压缩
  - [ ] 3.6 实现 `_run_day(baby_id, state, day, phase_idx, remaining_budget)`: 批量 routine + 涌现掷骰 + story_worthy 判断 + LLM/模板分流
  - [ ] 3.7 实现 `_flush_quiet_days(baby_id, state, from_day, to_day)`: 写入 `day_summary` 事件
  - [ ] 3.8 实现 `_complete_phase(baby_id, state, phase_idx)`: 调用 `nanny.complete_phase`，写入 `phase_completing` + `phase_completed` 事件
  - [ ] 3.9 移植 `_generate_story()` 方法（从旧 EventScheduler 复制，逻辑不变）
  - [ ] 3.10 实现 `run()` / `stop()` 方法（管理 `_running` 标志）
  - [ ] 3.11 将模块级单例从 `EventScheduler()` 切换为 `LifelineScheduler()`
  - [ ] 3.12 保留旧 `EventScheduler` 类但添加 `# DEPRECATED` 注释
  - [ ] 3.13 更新 L3 头部注释（INPUT/OUTPUT/POS 反映新架构）
  - [ ] 3.14 **测试**: 模拟一个 phase 0（30 天），验证产出 day_summary + story events；验证 LLM 调用不超过 6 次

- [ ] 4. Lifeline SSE 端点（api/cradle.py）
  - [ ] 4.1 新增 `lifeline(baby_id, after_seq)` 端点：Phase 1 回放（50ms/条）+ Phase 2 实时追踪（notify + 2s sim_tick）
  - [ ] 4.2 实现 notify 竞态安全逻辑（先读 → clear → 再读 → wait）
  - [ ] 4.3 替换旧 `heartbeat_stream()` 为 301 重定向到 lifeline
  - [ ] 4.4 移除旧 heartbeat_stream 中的 `scheduler.subscribe/unsubscribe/catchup/register` 调用
  - [ ] 4.5 更新 `set_time_scale()`: 移除 `scheduler.register` 调用（time_scale 只改 state，不重置调度）
  - [ ] 4.6 更新 `admit_baby()`: 调用新 `scheduler.register()`
  - [ ] 4.7 更新 L3 头部注释（heartbeat/stream → lifeline）
  - [ ] 4.8 **测试**: 用 curl 请求 lifeline?after_seq=0，验证回放 + 实时切换；验证 heartbeat/stream 返回 301

- [ ] 5. interact / intervene 兼容验证（api/cradle.py）
  - [ ] 5.1 验证 `interact()` 中的 `append_event` 调用自动获得 seq + notify（无需代码改动）
  - [ ] 5.2 验证 `intervene()` 中的 `append_event` 调用同理
  - [ ] 5.3 **测试**: 在 scheduler 运行期间调用 interact，验证事件出现在 lifeline SSE 流中

- [ ] 6. 旧 Scheduler 清理（scheduler.py）
  - [ ] 6.1 从旧 `EventScheduler` 移除 `_subscribers` / `subscribe()` / `unsubscribe()` / `_push()` 方法
  - [ ] 6.2 从旧 `EventScheduler` 移除 `catchup()` 方法
  - [ ] 6.3 从旧 `EventScheduler` 移除 `_process()` 中的 `_push()` 调用
  - [ ] 6.4 从旧 `EventScheduler` 移除 `_run_phase_transition()` 中的 `_push()` 调用
  - [ ] 6.5 确认 `TIME_SCALES` 常量保留（被 state.py 和 api 消费）

- [ ] 7. 前端适配（frontend/src/Cradle.jsx）
  - [ ] 7.1 SSE 连接 URL 改为 `/cradle/{baby_id}/lifeline?after_seq=${lastSeq}`，lastSeq 从 `localStorage.getItem(\`lastSeq_${selectedId}\`)` 读取
  - [ ] 7.2 在 `source.onmessage` 中：每条事件如果有 `data.seq`，更新 `localStorage.setItem(\`lastSeq_${selectedId}\`, data.seq)`
  - [ ] 7.3 新增 `day_summary` 事件的 dispatch 处理（DAY_SUMMARY action）
  - [ ] 7.4 新增 `phase_completing` 事件的 dispatch 处理
  - [ ] 7.5 新增 `life_complete` 事件的 dispatch 处理
  - [ ] 7.6 **测试**: 刷新页面，验证 SSE 从 localStorage.lastSeq 断点续传；验证清除 localStorage 后从头回放

- [ ] 8. 前端 ConsolePanel 适配（frontend/src/components/ConsolePanel.jsx）
  - [ ] 8.1 新增 DAY_SUMMARY reducer case：显示为折叠的 "Day X-Y: 平静日" 摘要行
  - [ ] 8.2 新增 PHASE_COMPLETING reducer case：显示加载指示器
  - [ ] 8.3 新增 LIFE_COMPLETE reducer case：显示成长完成标记
  - [ ] 8.4 **测试**: 验证三种新事件类型在控制台正确渲染

- [ ] 9. L2 文档更新
  - [ ] 9.1 更新 `cradle/CLAUDE.md`: 反映新 scheduler 架构、seq 机制、notify 机制
  - [ ] 9.2 更新 `events/CLAUDE.md`: 补充 `is_story_worthy` 和 `template_reaction` 的消费关系（如果最终放在 world.py）
  - [ ] 9.3 更新或创建 `api/CLAUDE.md`: 反映 lifeline 端点替代 heartbeat/stream

- [ ] 10. 集成测试 + 性能验证
  - [ ] 10.1 端到端测试：admit → scheduler 自动运行 → lifeline SSE 接收全部事件 → 12 阶段完成
  - [ ] 10.2 性能验证：12 阶段运行时间 < 10 分钟
  - [ ] 10.3 断点续传测试：中途断开 SSE → 重连 after_seq → 验证无丢失无重复
  - [ ] 10.4 并发互动测试：scheduler 运行中调用 interact → 验证互动事件出现在 lifeline 流中
  - [ ] 10.5 旧数据兼容测试：用无 seq 的旧 events.jsonl → lifeline?after_seq=0 → 验证事件正确补充 seq
