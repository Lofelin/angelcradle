# 任务清单：autonomous-life

## 1. 共享事件系统
- [x] 1.1 创建 `backend/events/` 模块，Event 数据模型增加 hour_range/requires_tags/excludes_tags/duration_hours/generates_next 字段
- [x] 1.2 将 `cradle/events.py` 的 48 种事件定义迁移到 `events/definitions.py`，补充时间窗口和标签
- [x] 1.3 实现 `route_events()` 函数（时间 + 阶段 + 标签三重过滤）
- [x] 1.4 将 `cradle/events.py` 改为 thin wrapper，保持 `roll_events()` 原签名向后兼容
- [x] 1.5 实现 `roll_emergent_event()` 涌现事件掷骰
- [x] 1.6 迁移权重调制器（`_compute_affinity`, `_phase_weight_modifier`）到 `events/modifiers.py`

## 2. Agent 状态扩展
- [x] 2.1 BabyState 新增 `life_tags: set[str]`, `last_active_ts: float`, `sim_time: float`, `time_scale: str`
- [x] 2.2 `to_dict()` / `from_dict()` 支持新字段（life_tags 序列化为 list）
- [x] 2.3 实现 `sim_time` → `age_days` 的自动映射（不超过当前阶段上限）

## 3. 世界层
- [x] 3.1 创建 `backend/world.py`，定义日程模板（infant/toddler/preschool_home/school_age）
- [x] 3.2 实现 `select_template()` 根据 phase + life_tags 选择模板
- [x] 3.3 实现日程随机化（±30 分钟偏移，保持先后顺序）
- [x] 3.4 实现 `process_event()` 分层处理（daily→规则 / environment→LLM）
- [x] 3.5 定义阶段自动标签规则（phase → life_tags 映射）
- [x] 3.6 定义能力解锁 → life_tags 映射
- [x] 3.7 定义关键事件决策 → life_tags 变更规则

## 4. DES 调度器
- [x] 4.1 创建 `backend/scheduler.py`，ScheduledEvent 数据类 + EventScheduler 类
- [x] 4.2 实现优先级队列（heapq）+ Agent 注册/注销
- [x] 4.3 实现主循环（取事件 → 处理 → 生成后续 → 插回队列）
- [x] 4.4 实现现实时间 ↔ 模拟时间转换（支持三种 time_scale）
- [x] 4.5 实现 LLM 调用限流（asyncio.Semaphore）
- [x] 4.6 实现 SSE 订阅/推送机制
- [x] 4.7 实现追赶模式（离线期间事件快速补跑）
- [x] 4.8 FastAPI lifespan 集成（启动时注册所有宝宝，关闭时停止调度器）

## 5. API 改造
- [x] 5.1 `heartbeat/stream` 端点改为订阅调度器事件通道
- [x] 5.2 admit 端点完成后自动注册到调度器
- [x] 5.3 interact/intervene 端点更新 `last_active_ts`
- [x] 5.4 心跳评估集成到调度器事件循环（有事事件后触发）

## 6. 前端
- [x] 6.1 Reducer 新增 `AUTONOMOUS_ROUTINE` / `AUTONOMOUS_EVENT` / `AUTONOMOUS_CATCHUP` case
- [x] 6.2 SSE handler 分发新事件类型
- [x] 6.3 renderLog 渲染日常活动（浅灰简短行）
- [x] 6.4 renderLog 渲染有"事"事件（醒目卡片 + 状态变化标签）
- [x] 6.5 renderLog 渲染追赶摘要（可折叠卡片）

## 7. 文档更新
- [x] 7.1 更新 `cradle/CLAUDE.md` 成员清单（events.py 变更说明 + 新依赖）
- [x] 7.2 创建 `events/CLAUDE.md`（L2 文档）
- [x] 7.3 新文件 L3 头部注释（scheduler.py, world.py, events/*.py）
