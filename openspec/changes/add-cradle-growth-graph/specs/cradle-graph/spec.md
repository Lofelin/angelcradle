# Delta for Cradle Graph

> 本 spec 为 `add-cradle-growth-graph` 变更提案定义的新增能力（ADDED）。所有通用原则（业务即图、实体稳定、时间在边上、uuid 构造、graph_delta 四原子操作、前端 LifeGraph.jsx 最小侵入）**全盘沿用** `add-womb-conception-graph` 的对应 spec，不再重述。本文件只记录摇篮特有的 Requirement。

## ADDED Requirements

### Requirement: 摇篮图谱数据产出方式

后端 SHALL 采用"业务即图"模式产出摇篮图谱数据：图谱更新作为 `cradle.nanny` / `scheduler.handlers` / `cradle.initiative_needs` / `cradle.conversation` / `cradle.mind` 等业务函数的副产品，通过 `/lifeline` SSE 事件的 `graph_delta` 字段流出，不存在独立的图谱生成器模块。

#### Scenario: 阶段开始事件 emit
- GIVEN scheduler 派发 `phase_start` 事件给 `handlers.on_phase_start`
- WHEN 处理器产出业务 payload
- THEN 事件 payload MUST 包含 `graph_delta` 字段
- AND `graph_delta` MUST 至少包含 `node_progression(phase_name, phase_index)` 节点的 `add_nodes`
- AND 当 phase_index > 0 时 MUST 同步 emit `edge_next(prev_phase_name, this_phase_name)` 边

#### Scenario: 能力解锁 emit
- GIVEN `cradle.nanny.complete_phase` 检测到新的 capability 解锁
- WHEN 产出 delta
- THEN delta MUST 包含 `node_capability(cap_key, dim, unlocked_at_phase)` 节点
- AND delta MUST 包含 `edge_occurs_in(capability, dim, per_dim_phase_stage)` 边
- AND 该边的 target 节点 MUST 为 category=`phase`（per-dim phase），MUST NOT 为 category=`progression`

#### Scenario: 编排层聚合多个子系统 delta
- GIVEN 一次 `phase_complete` 事件涉及 capability 解锁 / milestone 达成 / narrative 生成三个子系统
- WHEN 各子系统各自返回 graph_delta
- THEN 编排层 MUST 使用 `graph_emit.merge_deltas(*deltas)` 合并为一个 delta 对象
- AND 最终 SSE 事件 payload 中 `graph_delta` MUST 为合并后的单个对象

### Requirement: 概念两分（progression vs per-dim phase）

图中 MUST 严格区分两类节点：`progression:{phase_name}`（category=`progression`，引擎 12 步调度游标）与 `phase:{dim}:{stage}`（category=`phase`，per-dimension 发育期领域知识）。两者不可互用。

#### Scenario: progression 节点数量与来源
- GIVEN 一次完整摇篮期（不含中途死亡）跑完 12 阶段
- WHEN 最终图谱生成
- THEN 图中 MUST 恰好存在 12 个 `progression:*` 节点
- AND 其 id 集合 MUST 等于 `{progression:neonatal, progression:sensory_awakening, ..., progression:independence}`
- AND 每个 progression 节点 MUST 带 `metadata.phase_index ∈ [0, 11]`
- AND 所有 progression 节点的 category MUST 为 `progression`

#### Scenario: per-dim phase 节点数量与归属
- GIVEN 一次完整摇篮期
- WHEN 最终图谱生成
- THEN 图中 MUST 存在 6 个 `dimension:*` 节点（motor / cognitive / language / social / emotional / physical）
- AND 每个 dimension 下 MUST 挂 4-5 个 `phase:{dim}:{stage}` 节点
- AND 所有 per-dim phase 节点 MUST 带 `BELONGS_TO → dimension:{dim}` 出边（100% 覆盖）
- AND 任一 phase 节点 MUST NOT 同时指向两个不同 dimension

#### Scenario: OCCURS_IN 路由约束
- GIVEN 任意 capability 或 milestone 节点
- WHEN 其 `OCCURS_IN` 出边被 emit
- THEN 边的 target MUST 是 per-dim `phase:{dim}:{stage}`
- AND 边的 target MUST NOT 是任何 `progression:*` 节点
- AND 若 `capability.metadata.dim = motor`，则 target MUST 形如 `phase:motor:*`（与 capability 的 dim 匹配）

#### Scenario: progression 不归属 dimension
- GIVEN 任意 progression 节点
- WHEN 扫描其出边
- THEN 该节点 MUST NOT 带任何 `BELONGS_TO → dimension:*` 出边
- AND 该节点与 dimension 节点之间 MUST NOT 有任何直接边

### Requirement: 跨图 continuant 延续（baby_this 跨图 UUID 一致）

摇篮图的 `baby_this` 节点 UUID MUST 与对应 baby 的子宫图 `baby_this` 节点 UUID 字节完全相同，使得两图可通过同一节点 id 做前端合并 / 联合查询，无需翻译层。

#### Scenario: UUID 构造一致性
- GIVEN 同一 baby 经历完整 `womb → cradle` 流程
- WHEN 分别在 `backend/womb/graph_emit.py` 和 `backend/cradle/graph_emit.py` 中调用 `make_node_uuid("baby_this")`
- THEN 两次返回值 MUST 字节完全相等
- AND 两个 `graph_emit.py` MUST 共用同一 UUIDv5 namespace（`6ba7b810-9dad-11d1-80b4-00c04fd430c8`）
- AND raw_id 拼写 MUST 由 `backend/common/graph_ids.BABY_SELF_RAW_ID` 常量集中定义并双方引用

#### Scenario: 落库快照 UUID 验证
- GIVEN `archive/{baby_id}/womb_graph.json` 和 `archive/{baby_id}/cradle_graph.json` 同时存在
- WHEN 加载两文件并分别定位 baby_this 节点
- THEN 两节点的 `id` 字段 MUST 字符串完全相同
- AND 两节点的 `metadata.raw_id` 字段 MUST 均等于 `"baby_this"`

### Requirement: 时间坐标三元组禁实体化

摇篮图 MUST NOT 存在任何形如 `stage_N` / `day_N` / `phase_x_day_y` / `sim_time_N` 等将时间段或时间点固化为节点身份的节点。时间坐标 SHALL 仅以以下形式存在：

1. 边的 `phase_index` 属性（0-11，必填，适用所有带时间的因果边）
2. 边的 `day_index` 属性（可选，阶段内日序）
3. 边的 `sim_time` 属性（可选，精细回放场景）
4. 节点 `metadata.track` 数组元素中的 `phase_index` / `day_index` 字段

#### Scenario: 完整摇篮期图谱的节点审查
- GIVEN 一次完整摇篮期最终图谱
- WHEN 遍历所有节点
- THEN MUST NOT 存在任何 id 以 `stage_` / `day_` / `phase_x_day_` 开头的节点
- AND MUST NOT 存在任何 `metadata.kind` 为 `"stage"` / `"day"` / `"timestamp"` 的节点
- AND MUST NOT 存在任何节点的 `raw_id` 以上述前缀开头

#### Scenario: 时间信息在边上的正确承载
- GIVEN 母亲在 phase_index=4 day_index=12 抚触 baby 一次
- WHEN 后端 emit 对应 CARED_BY 边
- THEN 边的 source MUST 为 `caregiver_mother`，target MUST 为 `baby_this`
- AND 边 MUST 带 `phase_index: 4` 属性
- AND 边 MAY 带 `day_index: 12` 属性
- AND 边的 target MUST NOT 为 `day_12` / `phase_4_day_12` 等任何时间节点

### Requirement: 照护者多中心支持

caregiver 节点 SHALL 作为图中次级中心存在。每个 caregiver 在整个摇篮期 MUST 仅一个节点（continuant 稳定），照护者身份变更（新增 / 离任 / 离世）通过 `metadata.status` 字段表达，不删除节点不拆分节点。

#### Scenario: 首次出现的照护者
- GIVEN 一位母亲在 neonatal 阶段开始照护 baby
- WHEN 首次 emit caregiver 节点
- THEN 节点 id MUST 为 `caregiver_{id}`（id 由业务层给定，通常为 UUID 或 slug）
- AND 节点 metadata MUST 包含 `role: "mother"`, `status: "active"`, `identity_traits` 若有
- AND 同一 caregiver 后续在其他阶段 MUST NOT 被重复 add_nodes（通过 add 幂等性保证）

#### Scenario: 依附状态切换表达为多重边
- GIVEN baby 与 mother 的 attachment 在 phase_index=2 从 secure 切换为 anxious
- WHEN 后端 emit 对应 ATTACHES_TO 边
- THEN MUST 新增一条边 `baby_this → caregiver_mother ATTACHES_TO(phase_index=2, state="anxious")`
- AND MUST NOT update 或 remove 早期的 `ATTACHES_TO(state="secure")` 边
- AND 两条多重边通过 uuid 内纳入 phase_index + state 保持唯一
- AND 前端渲染时自动以曲率分散展示"依附历史"

#### Scenario: 照护者离任不删节点
- GIVEN 一位保姆在 phase_index=6 离任
- WHEN 业务层处理
- THEN MUST 对该 caregiver 节点执行 `update_nodes` 把 `metadata.status` 改为 `"inactive"`
- AND MUST NOT 从图中 `remove_nodes` 该节点
- AND 该 caregiver 与 baby 之间历史 CARED_BY 多重边 MUST 保留完整

### Requirement: 事件型 vs 日常采样的 emit 策略

后端 emit 策略 MUST 明确区分两种场景：事件型（continuant 首次出现 / 显著状态变更）走 `add_nodes` / `add_edges`；日常采样（每日 stress / attachment / nutrition_sleep 等指标）走 `update_nodes.metadata.track_append`，不得每日新增节点。

#### Scenario: capability 首次解锁走 add
- GIVEN 在 phase_index=4 首次检测到 `capability_walk` 解锁
- WHEN 业务函数 emit
- THEN delta MUST 包含 `add_nodes: [node_capability("walk", ...)]`
- AND 后续阶段若 strength 增长，MUST 通过 `update_nodes` 修改 metadata，MUST NOT 再次 add_nodes 同 id 节点

#### Scenario: 每日 stress 采样走 track_append
- GIVEN day_tick 事件每日产生一个 stress level 数值
- WHEN 业务函数 emit
- THEN delta MUST NOT 包含 stress 相关的 `add_nodes`
- AND delta MUST 包含形如 `update_nodes: [{id: "baby_this", metadata: {track_append: {kind: "stress", phase_index, day_index, level}}}]`
- AND 前端 `mergeGraph` MUST 识别 `track_append` 并追加到 `metadata.track` 数组

#### Scenario: 显著变化触发事件节点
- GIVEN 在 phase_index=3 压力水平触发 `capability_walk` 暂失能
- WHEN 业务函数 emit
- THEN delta MUST 包含 `add_nodes: [node_regression(cap="walk", phase_index=3, ...)]`
- AND delta MUST 包含 `add_edges: [edge_regresses(event_id, "capability_walk", phase_index=3)]`
- AND 后续若恢复，MUST 另外 emit `node_recovery` + `edge_recovers`，MUST NOT update 或 remove 之前的 regression 节点 / 边

### Requirement: critical_event 两阶段 emit（pending → resolved）

critical_event 的图谱表达 MUST 分两步完成：触发时以 `status: "pending"` add 节点；家长决议后 update 节点状态 + add 决议边。期间图谱保持一致可查。

#### Scenario: critical_event 首次触发
- GIVEN `simulate_phase` 在 phase_index=5 产生一个 critical_event
- WHEN 业务函数 emit
- THEN delta MUST 包含 `node_critical(phase_index=5, seq=..., status="pending", reason=...)`
- AND delta MUST 包含 `edge_experiences(baby, critical_id, phase_index=5)`
- AND 节点 `metadata.status` MUST 为 `"pending"`

#### Scenario: critical_event 家长决议
- GIVEN 同一 critical_event 被 mother 决议
- WHEN 业务函数 emit 对应 delta
- THEN delta MUST 包含 `update_nodes: [{id: critical_id, metadata: {status: "resolved", resolved_by: caregiver_id, resolution, decided_at}}]`
- AND delta MUST 包含 `add_edges: [edge_resolves(caregiver_id, critical_id, phase_index, action, tag_effects)]`
- AND MUST NOT `remove_nodes` 原 critical 节点（保留完整决策轨迹）

#### Scenario: critical_event 长期悬挂
- GIVEN critical 节点在 phase_index=5 触发后，家长 AFK 多阶段未 resolve
- WHEN baby 进入 phase_index=6 / 7
- THEN critical 节点 MUST 保持 `status: "pending"`
- AND 前端 MAY 视觉区分 pending 态（如边框虚线）
- AND 落库 `cradle_graph.json` MUST 包含该 pending 节点原样保存

### Requirement: 终局状态表达

baby 在摇篮期结束（正常 `world_ready` / 异常 `deceased` / 阶段未完成 `cradle_incomplete`）MUST 通过 update + 终局事件边表达，不得粗暴删除已有节点。

#### Scenario: 正常进入世界
- GIVEN baby 走完 12 阶段通过 `check_world_readiness`
- WHEN 后端触发 `cradle_complete` / `world_ready` 事件
- THEN delta MUST 包含 `node_event(event_type="world_ready", phase_index=11)`
- AND delta MUST 包含 `edge_terminated_by(event_id, baby_id, phase_index=11, cause="world_ready")`
- AND delta MUST 包含 `update_nodes: [{id: "baby_this", metadata: {status: "world_ready", terminated_at_phase: 11}}]`

#### Scenario: 异常死亡
- GIVEN baby 在 phase_index=4 发生不可恢复事件
- WHEN 业务函数触发终局
- THEN delta MUST 包含 `edge_terminated_by(event_id, baby_id, phase_index=4, cause="deceased")`
- AND baby 节点 `metadata.status` MUST 改为 `"deceased"`
- AND 编排层 MUST 提前退出，不再调用后续阶段业务函数，图中 MUST NOT 出现 phase_index > 4 的 caregiver 交互 / capability 解锁相关节点与边

### Requirement: 图谱按 baby_id 落库

每次 `phase_complete` MUST 把当前累积图状态快照保存一次；终局事件（world_ready / deceased / cradle_incomplete）MUST 保存最终快照到 `backend/archive/{baby_id}/cradle_graph.json`。

#### Scenario: 阶段结束快照
- GIVEN phase_index=3 的 `phase_complete` 事件完成
- WHEN scheduler 处理完该事件
- THEN 后端 MUST 调用 `registry.save_cradle_graph(baby_id, accumulated_state)`
- AND 文件 MUST 包含 `{baby_id, species, sex, schema: "v3-business-as-graph", status, saved_at, phases_completed: 4, nodes[], edges[], stats}`

#### Scenario: 终局快照
- GIVEN baby 达到 `world_ready` / `deceased` / `cradle_incomplete`
- WHEN 终局事件被处理
- THEN 后端 MUST 落库，`metadata.status` MUST 反映终局原因
- AND `nodes` 长度 MUST 在 80-200 区间（除非中途终止）
- AND `edges` 长度 MUST 在 180-400 区间（除非中途终止）

### Requirement: 图谱查询 API

后端 MUST 提供 `GET /baby/{baby_id}/cradle-graph` 端点返回已落库快照；旧 stub 端点 `GET /cradle/{baby_id}/graph` SHALL 保留一期兼容。

#### Scenario: 成功查询新端点
- GIVEN `archive/{baby_id}/cradle_graph.json` 存在且 schema 为 `v3-business-as-graph`
- WHEN 客户端 GET `/baby/{baby_id}/cradle-graph`
- THEN 响应 MUST 为 200
- AND body MUST 为 `{baby_id, species, sex, schema, status, saved_at, phases_completed, nodes[], edges[], stats}`
- AND 前端可将此快照直接传给 `useCradleGraph.loadSnapshot(data)` 还原图

#### Scenario: schema 版本不匹配
- GIVEN `archive/{baby_id}/cradle_graph.json` 存在但 schema 为旧版本（如 v2 或缺失 schema 字段）
- WHEN 客户端 GET 新端点
- THEN 响应 MUST 为 404
- AND body MUST 包含提示 `"Cradle graph not found for baby '{id}'"` 或 `"Cradle graph schema outdated, please re-run life"`

#### Scenario: 旧 stub 端点兼容
- GIVEN 客户端仍在使用 `GET /cradle/{baby_id}/graph`
- WHEN 后端处理
- THEN 若新 schema 存在则 MUST 返回同样快照；否则 MUST 返回 `{nodes: [], edges: []}` 保持 stub 行为
- AND 响应 Header 或 body 内 MAY 携带 deprecated 提示

### Requirement: 节点 narrative 双语支持

节点 `narrative.primary` 与 `narrative.scientific` 字段 MUST 支持 `zh_CN` + `en` 双语并存。前端按当前 UI 语言渲染，缺失时 fallback 到另一语言。

#### Scenario: capability 节点双语
- GIVEN 一个 `capability_walk` 节点被产出
- WHEN 节点进入 `graph_delta.add_nodes`
- THEN `node.narrative.primary` MUST 同时包含 `zh_CN` 和 `en` 字段
- AND 两字段内容 MUST 语义对齐（描述同一能力里程碑）

#### Scenario: 前端按语言渲染
- GIVEN 用户在英文模式下点击 `capability_walk` 节点
- WHEN 详情面板打开
- THEN Summary 区块 MUST 显示 `narrative.primary.en`
- AND 若 en 缺失，MUST fallback 到 `zh_CN`，反之亦然
- AND 任一语言都缺失时 MUST 显示节点 label 而非空白

### Requirement: 成功标准对标（可量化验收）

一次完整 human 摇篮期（从 neonatal 到 independence，无中途终止）产出的图谱 SHALL 满足以下可量化指标，作为本变更落地完成的判定依据：

#### Scenario: 单次完整摇篮期图的规模
- GIVEN 一次完整 human 摇篮期
- WHEN 整个 lifeline SSE 流结束
- THEN 最终图节点数 SHALL 在 80-150 区间
- AND 最终图边数 SHALL 在 180-320 区间
- AND `baby_this` 节点的 in-degree + out-degree SHALL 是全图最高（≥ 30）
- AND `caregiver_mother`（或主照护者）节点的 in-degree + out-degree SHALL 是全图次高

#### Scenario: 概念两分覆盖度
- GIVEN 一次完整摇篮期图谱
- WHEN 按 category 统计
- THEN MUST 恰好存在 12 个 `progression` 节点
- AND MUST 恰好存在 6 个 `dimension` 节点
- AND MUST 存在 24-32 个 `phase` 节点（per-dim 合计）
- AND 所有 phase 节点 `BELONGS_TO → dimension` 覆盖率 MUST 为 100%
- AND 所有 capability / milestone 的 `OCCURS_IN` 指向 per-dim phase 覆盖率 MUST 为 100%

#### Scenario: 关键多重边 demo
- GIVEN 一次完整摇篮期
- WHEN 整个 SSE 流结束
- THEN 图中 MUST 满足：
  - `caregiver_mother → baby_this CARED_BY` 多重边数 ≥ 3
  - `baby_this → caregiver_mother ATTACHES_TO` 多重边数 ≥ 2（至少一次状态切换）
  - 任一被回退再恢复的 capability：`REGRESSES` 边 ≥ 1 且 `RECOVERS` 边 ≥ 1（双向轨迹可见）

#### Scenario: 反模式 0 出现
- GIVEN 一次完整摇篮期
- WHEN 图谱被校验
- THEN MUST NOT 存在任何时间节点（`stage_N` / `day_N` / `phase_x_day_y`）
- AND MUST NOT 存在任何 capability 节点按阶段拆分（如 `capability_walk_p4` 与 `capability_walk_p5` 同时并存）
- AND MUST NOT 存在任何 `OCCURS_IN` 边指向 progression 类节点
- AND MUST NOT 存在任何 phase 节点缺失 `BELONGS_TO → dimension` 出边
