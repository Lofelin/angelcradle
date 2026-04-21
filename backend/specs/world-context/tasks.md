# Plan: world-context

## Tasks

- [ ] 1. BabyState 扩展（数据层基础）
  - [ ] 1.1 在 `cradle/state.py` BabyState 中新增 `triggered_events: set[str]` 字段（default_factory=set）
  - [ ] 1.2 在 `cradle/state.py` BabyState 中新增 `world_snapshot` 字段（默认 None，类型注解引用 world.WorldSnapshot）
  - [ ] 1.3 在 `to_dict` 中序列化 triggered_events 为 list，world_snapshot 调用 snapshot_to_dict
  - [ ] 1.4 在 `from_dict` 中反序列化 triggered_events（d.get -> set）和 world_snapshot（d.get -> snapshot_from_dict）
  - [ ] 1.5 新增 `rebuild_triggered_events(state)` 函数：从 memories + milestones 重建 triggered_events
  - [ ] 1.6 在 `load_state` 后调用 rebuild：若 triggered_events 为空且 memories 非空，自动重建

- [ ] 2. WorldSnapshot 数据模型（world.py 新增）
  - [ ] 2.1 定义 `SnapshotEvent` dataclass（name, display_name, description, sensory_channels, intensity, day_index, category）
  - [ ] 2.2 定义 `WorldSnapshot` dataclass（start_day, end_day, weather_pattern, family_arc, ambient_mood, events, surprise_pool, used_events）
  - [ ] 2.3 实现 `snapshot_event_to_event(se) -> Event` 适配函数
  - [ ] 2.4 实现 `snapshot_to_dict(ws) -> dict` 和 `snapshot_from_dict(d) -> WorldSnapshot` 序列化
  - [ ] 2.5 实现 `infer_season(age_days, baby_id) -> str` — 从 baby_id 解析出生月份推算季节
  - [ ] 2.6 定义 `SNAPSHOT_INTERVAL: dict[int, int]` — 按阶段可变的快照周期

- [ ] 3. WorldSnapshot LLM 生成（核心功能）
  - [ ] 3.1 实现 `_build_snapshot_prompt(state, prev_snapshot) -> str` — 含 life_tags/phase/age/memories/stress/capabilities/season/triggered_events/前一快照摘要
  - [ ] 3.2 实现 `_parse_snapshot_response(parsed, start_day, interval) -> WorldSnapshot | None` — 校验必要字段，转换为 WorldSnapshot
  - [ ] 3.3 实现 `generate_world_snapshot(state, prev_snapshot) -> WorldSnapshot | None` — 调用 _call_and_parse，失败返回 None
  - [ ] 3.4 定义 `_WORLD_ENGINE_SYSTEM` 系统指令常量

- [ ] 4. 事件选取逻辑（每日选取）
  - [ ] 4.1 实现 `pick_daily_event(snapshot, day_in_snapshot, state) -> SnapshotEvent | Event | None`
  - [ ] 4.2 集成 triggered_events 全局去重（first_X 和 critical 过滤）
  - [ ] 4.3 降级分支：snapshot 为 None 时调用 roll_emergent_event_legacy
  - [ ] 4.4 实现 `_needs_snapshot_refresh(day, state) -> bool`

- [ ] 5. Legacy 降级路径
  - [ ] 5.1 新增 `roll_emergent_event_legacy` — 包装 events.roll_emergent_event + triggered_events 去重
  - [ ] 5.2 legacy 路径中 first_X 去重
  - [ ] 5.3 legacy 路径中 critical 去重

- [ ] 6. 模板反应增强
  - [ ] 6.1 `template_reaction` 增加 snapshot 参数，注入天气/氛围前缀

- [ ] 7. Scheduler 集成
  - [ ] 7.1 修改 `_run_day`：涌现事件部分接入 generate_world_snapshot + pick_daily_event
  - [ ] 7.2 快照刷新通过 _llm_semaphore + asyncio.to_thread
  - [ ] 7.3 涌现事件触发后写入 state.triggered_events
  - [ ] 7.4 关键事件写入 pending_criticals 时同步写入 triggered_events
  - [ ] 7.5 快照生成/降级写入 events.jsonl（world_snapshot / world_snapshot_fallback）

- [ ] 8. 文档同构更新
  - [ ] 8.1 更新 world.py L3 头部
  - [ ] 8.2 更新 scheduler.py L3 头部
  - [ ] 8.3 更新 cradle/state.py L3 头部
  - [ ] 8.4 更新 events/CLAUDE.md L2
  - [ ] 8.5 更新 cradle/CLAUDE.md L2

- [ ] 9. 测试验证
  - [ ] 9.1 启动模拟，观察前 30 天是否生成世界快照日志事件
  - [ ] 9.2 断开 LLM，验证降级到固定事件池
  - [ ] 9.3 运行完整 Phase 0-1，验证 first_X 事件不重复
  - [ ] 9.4 检查 events.jsonl 中 world_snapshot 事件和连续性
  - [ ] 9.5 旧 BabyState JSON 加载兼容性验证
