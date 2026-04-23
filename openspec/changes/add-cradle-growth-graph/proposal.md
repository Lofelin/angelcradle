# 变更提案：摇篮成长实时图谱（业务即图 · 自驱动事件 · 跨图延续）

## 动机

摇篮模块（`backend/cradle/` + `backend/scheduler/`）是受孕图谱之后**生命周期最长、事件最密集、主角最多**的一段——12 阶段 × N 天 DES 驱动、phase_start / day_tick / critical_event / phase_complete / heartbeat / baby_need / conversation_message 全向涌现，同时交织多照护者、多 baby（群聊）、19 类主动需求、603 条 InitiativeScene、压力回退与恢复、依附漂移、偏好/恐惧/慰藉物沉淀。

前端 `LifeGraph.jsx` 已通过 womb 图（`add-womb-conception-graph`）跑通"**业务即图 + 实时增量 + 多重边天然浮现**"的全链路。但摇篮侧对应的后端图谱管道：

- `backend/cradle_graph_store.py`（老六层发育因果图谱引擎）已于 2026-04-21 **被推翻删除**，等待全新重构（见 `memory/project_lifegraph_deleted.md` 与 `/CLAUDE.md`）
- `/cradle/{baby_id}/graph` 端点保留空 stub（`{nodes:[], links:[]}`）
- v3 的 `refactor-cradle-graph-phase-axis` 提案已冻结**概念两分**（progression 引擎游标 vs per-dimension phase）作为重构前置决定

摇篮若继续沿用"独立 reducer + 全量重算"的老路线，注定重蹈 womb v1/v2 的覆辙（实体按阶段拆分 → 时间固化进节点身份 → 多重边被合并覆盖 → 业务/图漂移）。本提案**把 womb 跑通的"业务即图"范式完整迁移到摇篮**，并针对摇篮特有的长时序、多主角、自驱动三大特征做最小必要扩展。

## 目标

- **G1 业务即图（沿用 womb 范式）**：取消任何独立 reducer / graph_store 模块，图谱更新作为 `cradle.nanny` / `scheduler.handlers` / `cradle.conversation` / `cradle.initiative_needs` / `cradle.mind` 等业务函数的**副产品**，随 lifeline SSE 事件的 `graph_delta` 字段流出。
- **G2 实体稳定（沿用 womb 范式）**：caregiver / capability / milestone / dimension / need / preference / fear / comfort_source / scene_archetype 每个 continuant 在整个摇篮期仅一个节点，不按阶段拆分。
- **G3 时间在边上（沿用 womb 范式）**：时间坐标以 `phase_index`（0–11）+ 可选 `day_index`（阶段内日序）+ 可选 `sim_time` 三元组作为**边的属性**，节点 metadata 的 `track` 数组承接日常采样。**禁止出现 `stage_N` / `day_N` / `phase_x_day_y` 类时间节点**。
- **G4 概念两分落地（继承 refactor-cradle-graph-phase-axis v3）**：
  - `progression:{phase_name}`（category=`progression`）：12 步引擎游标，作为 `fate_birth` 同类的叙事时间线节点，承担"第几步"的调度叙事，不参与 `OCCURS_IN` 链
  - `phase:{dim}:{stage}`（category=`phase`）：per-dimension 发育期，每个 phase 节点 **MUST** 带 `BELONGS_TO → dimension:{dim}` 出边
  - `capability` / `milestone` 的 `OCCURS_IN` 目标 **MUST** 为对应维度的 per-dim phase，**MUST NOT** 指向 progression
- **G5 跨图延续（摇篮特有）**：摇篮图以 `baby_this` 为唯一根节点，与 `archive/{baby_id}/womb_graph.json` 共享同一 `baby_this` raw_id（UUIDv5 相同 → 节点 UUID 相同）。前端在宝宝详情页上方渲染 womb 图、下方渲染 cradle 图时，**同一 baby UUID 天然可串联两图**（本期只做节点 ID 对齐，视觉串联与联合查询延后）。
- **G6 多主角支持（摇篮特有）**：caregiver 作为独立节点，`caregiver → baby CARED_BY`、`baby → caregiver ATTACHES_TO(state=secure/anxious/avoidant)` 双向多重边；多 baby 群聊场景下每个 baby 节点独立，不共享 `self`。
- **G7 自驱动事件 emit（摇篮特有）**：DES 的 `phase_start` / `day_tick` / `critical_event` / `phase_complete` 都是合法 emit 触发点；`heartbeat` 和 `baby_need` 触发的 scene 实例以 `event_scene_*` 形态节点化，归因到对应 trigger。
- **G8 日常采样不爆量（摇篮特有）**：stress / attachment / nutrition_sleep / physical 每日数值走 `update_nodes` 的 `track_append`，不重复 `add_nodes`。单次完整摇篮期（12 阶段共 90–120 天）图规模 **80-150 节点 / 180-320 边**。
- **G9 实时增量渲染（沿用 womb 范式）**：前端通过 `useCradleGraph(babyId)` hook 订阅 `/lifeline` SSE，按 `graph_delta` 四种原子操作合并；`LifeGraph.jsx` 核心渲染逻辑零修改（womb 已完成 `adaptEdges` 优先用后端 uuid 的改造）。
- **G10 图谱按 baby_id 落库**：每次阶段推进或关键事件解决时，后端维护累积图状态 `_cradle_graph_state`，在阶段结束 / 进入世界 / baby 异常终止时落库到 `archive/{baby_id}/cradle_graph.json`；提供 `GET /baby/{baby_id}/cradle-graph` 端点供前端回读历史。
- **G11 零维护扩展**：新增一种 capability、一类 critical_event、一种 preference 类别，**只需在对应业务函数里加 1-3 行 `emit_*` 调用**，不改 reducer、不改 schema 注册表、不改前端组件。
- **G12 i18n 双语 narrative**：节点 `narrative.primary` / `narrative.scientific` 同时携带 `zh_CN` 和 `en`，前端按当前语言渲染（复用 womb 提案的双语方案）。

## 范围

### 包含

- **后端**
  - `backend/cradle/graph_emit.py`（**新增**）：纯函数帮手库，约 150 行。节点构造器（`node_baby` / `node_caregiver` / `node_progression` / `node_phase_dim` / `node_dimension` / `node_capability` / `node_milestone` / `node_need` / `node_preference` / `node_fear` / `node_comfort` / `node_scene` / `node_event` / `node_narrative`）+ 边构造器（`edge_belongs_to` / `edge_occurs_in` / `edge_unlocks` / `edge_achieves` / `edge_regresses` / `edge_recovers` / `edge_cared_by` / `edge_attaches_to` / `edge_experiences` / `edge_triggered_by` / `edge_caused_by` / `edge_stresses` / `edge_soothes` / `edge_acquires` / `edge_speaks_to` / `edge_describes` / `edge_named_by` / `edge_terminated_by`）+ `delta_add/update/remove` + `merge_deltas`。UUID 规则复用 womb 的 UUIDv5 + 同一 namespace，确保 `baby_this` 跨图一致。
  - `backend/cradle/graph_story.py`（**新增**）：capability / dimension / phase / need / preference 等的双语文本 META 字典（参考 `backend/womb/graph_story.py` 结构）。
  - `backend/cradle/nanny.py`（**修改**）：`simulate_phase_stream` / `resolve_critical_event` / `complete_phase` 在产出业务数据的同时 emit 对应 `graph_delta`。
  - `backend/scheduler/handlers.py`（**修改**）：`on_phase_start` / `on_day_tick` / `on_phase_complete` / `process_story` 在写 events.jsonl 时同步把 `graph_delta` 塞进事件 payload。
  - `backend/cradle/initiative_needs.py`（**修改**）：`evaluate_need` 触发主动需求时 emit `event_need_*` 节点 + `baby → need TRIGGERED_BY` / `need → scene EXPERIENCES` 边。
  - `backend/cradle/conversation.py`（**修改**）：`post_parent_message` / `post_baby_message` 产生 conversation_message 事件时 emit `conv:{conv_id}` 节点 + `baby → conv SPEAKS_TO(stage_index)` 多重边；每条消息 `update_nodes.metadata.track_append` 追加 message 摘要。
  - `backend/cradle/mind.py`（**修改**）：`narrate_phase_events` / `generate_phase_summary` 完成后 emit `narrative:phase_{N}` 节点 + `DESCRIBES → baby` 边。
  - `backend/api/cradle.py`（**修改**）：`/lifeline` SSE 透传 `graph_delta` 字段；把 stub 端点 `GET /cradle/{baby_id}/graph` 改为返回 `archive/{baby_id}/cradle_graph.json` 快照（同时保留 `GET /baby/{baby_id}/cradle-graph` 新端点作为规范命名，旧端点 301/alias 兼容前端）。
  - `backend/api/registry.py`（**修改**）：新增 `save_cradle_graph(baby_id, graph)` / `load_cradle_graph(baby_id)`（对齐现有 `save_womb_graph` / `load_womb_graph` 签名）。

- **前端**
  - `frontend/src/hooks/useCradleGraph.js`（**新增**）：约 60 行，订阅 `/lifeline` SSE，按 `graph_delta` 合并本地 `{nodes, edges}` 状态；复用 `mergeGraph`（从 `useWombGraph` 提出共享到 `frontend/src/utils/mergeGraph.js`）。
  - `frontend/src/utils/mergeGraph.js`（**新增**）：把 `useWombGraph.js` 里的 `mergeGraph` 提炼为共享工具（原文件保留 re-export，零破坏）。
  - `frontend/src/Cradle.jsx` 或宝宝详情页（**修改**）：接入 `useCradleGraph(babyId)`，把 cradle 图谱渲染到摇篮视图。
  - `frontend/src/components/LifeGraph.jsx`（**零修改**）：womb 提案已完成 `adaptEdges` 优先 uuid 改造，cradle 边直接通过。
  - `frontend/src/data/cradle-growth-sample.json`（**新增**）：设计参考实现（design-as-code），完整描绘一个虚拟宝宝走完 12 阶段的图谱最终态，作为后端产出契约参考 + 前端离线调试基准。

- **规范**
  - `openspec/changes/add-cradle-growth-graph/specs/cradle-graph/spec.md`：按 SHALL/MUST 形式固化节点契约、边契约、multi-edge 语义、UUID 规则、progression/phase 两分约束、跨图延续约束、落库与查询、双语 narrative、成功标准。

### 不包含

- **womb ↔ cradle 联合图视图**：两图在前端分开渲染，共享 baby UUID 使得**数据层已具备联合能力**，但 UI 联合视图（悬浮切换 / 时间轴滑块跨段展示）不在本期。
- **多 baby 联合视图**：同一家庭多个宝宝图谱并列对比（基因 vs 环境 vs 养育差异）延后。
- **cradle 图 ↔ world 图串联**：进入世界阶段的后续图谱（工作 / 伴侣 / 子代）不在本期，`world_ready` 事件在 cradle 图中只作为叶子节点 `event_world_ready`。
- **LLM graph_fragment 扩展**：允许 LLM 在阶段总结 / critical_event 决议时额外吐 `graph_fragment` 补充因果边，预留字段但不实现；下一期独立提案。
- **时间轴回放滑块 UI**：数据基础（所有边带 `phase_index`）已就绪，前端"拖拽阶段滑块只显示部分边"的交互不在本期。
- **Neo4j / Graphiti 接入**：图谱仍只在内存 + 前端状态 + JSON 文件三处存在，不接入图数据库。
- **图谱推理 / 路径查询 API**：只做"记录 + 快照查询"，归因链可视化依赖前端点击溯源（前端组件现有能力足以支撑）。
- **scheduler 层的结构改动**：不改 DES 主循环、per-baby lock、events.jsonl 协议；`graph_delta` 只作为事件 payload 的一个字段透传。
- **历史 baby 存档迁移**：archive/ 里现有 baby 的 `cradle_graph.json`（v2 删除前残留）不做迁移，旧文件若存在则标记为 `schema: "v2-deprecated"` 并在端点返回 404，鼓励重新跑一次生命。

## 成功标准

- ✅ 一次 human 物种从 `Neonatal` 跑到 `Independence` 的完整摇篮期（不含中途死亡）结束后，前端能看到一张 **80-150 节点 / 180-320 边**的实时生长图，visual growth 可视。
- ✅ 图中**存在且仅存在** 12 个 `progression:{phase_name}` 节点（category=`progression`），它们之间通过 `NEXT` 或 `PRECEDES` 边串成叙事时间线。
- ✅ 图中存在 6 个 `dimension:{dim}` 节点（motor / cognitive / language / social / emotional / physical），每个 dimension 下挂 4-5 个 `phase:{dim}:{stage}` 节点，所有 phase 节点 **100%** 带 `BELONGS_TO → dimension:{dim}` 出边。
- ✅ 任一 capability / milestone 节点的 `OCCURS_IN` 出边目标 **100%** 是 per-dim phase（形如 `phase:motor:toddler`），**无一例**指向 progression。
- ✅ 同一 `caregiver_mother → baby_this` 存在至少 3 条 `CARED_BY` 多重边（不同 phase_index，不同 care_quality），前端自动曲率分散。
- ✅ `baby_this → caregiver_mother ATTACHES_TO` 至少 2 条多重边（state=secure 与 state=anxious 的跨阶段切换被记录）。
- ✅ 图中**不存在**形如 `stage_N` / `day_N` / `phase_x_day_y` 的时间节点；时间坐标 100% 在边的 `phase_index` / `day_index` 属性上，或节点 metadata 的 `track` 数组元素里。
- ✅ 每个 continuant 实体（capability_walk / fear_stranger / preference_music / caregiver_mother / comfort_blanket 等）在整个摇篮期**仅一个节点**。
- ✅ 归因链可追溯：点击 `milestone_first_word` 节点能沿 `ACHIEVES ← baby_this` ← `UNLOCKS ← event_phase_complete:first_word` ← `DRIVEN_BY ← capability_babble` 找到最近 3 跳因果。
- ✅ 压力回退场景：一次高压阶段触发 `capability_walk` 暂失能 → 图中 emit `event_regression:walk` 节点 + `REGRESSES` 边，下阶段恢复时 emit `event_recovery:walk` + `RECOVERS` 边；前端可见"能力消失→重建"的双向轨迹。
- ✅ 流产 / 死产 / 进入世界任一终局：后端落库 `archive/{baby_id}/cradle_graph.json`，`metadata.status ∈ {alive_ready / deceased / cradle_incomplete}`。
- ✅ 前端 SSE 容错：`/lifeline` 事件不含 `graph_delta` 时不 crash，静默跳过；graph 状态保留已收集部分。
- ✅ 业务代码加新 capability（如 `capability_pretend_play`）零 reducer 改动：只在 `nanny.py._check_capability_unlocks` 解锁分支新增一行 `emit.capability(cap_key, dim, phase)`。
- ✅ UUID 跨图一致性：同一 baby 的 `baby_this` 节点在 `womb_graph.json` 和 `cradle_graph.json` 中 UUID **字节相同**；前端若把两图合并，同 id 节点天然去重。

## 风险与缓解

| 风险 | 等级 | 缓解 |
|------|------|------|
| 图规模爆量（日常 day_tick × 90 天 × 6 维 metrics 若每次都 add_nodes） | 中 | emit 策略铁律：**日常数值采样走 `update_nodes.metadata.track_append`，只有"首次出现" / "显著变化"（如 capability 解锁 / 能力回退 / 依附状态切换 / preference 新增）才 `add_nodes`**。`graph_emit.py` 暴露 `emit.track_sample(node_id, phase, day, value)` 专用 API 引导业务代码走正确路径。上限硬约束：单图 ≤ 200 节点 / ≤ 400 边，落库前校验。 |
| progression 与 per-dim phase 双体系新手易混 | 中 | `graph_emit.py` 的 `node_progression` 与 `node_phase_dim` 是**两个不同的构造器**，签名与返回 category 强制区分；`edge_occurs_in` 内置断言：目标 category **MUST NOT** 为 `progression`，违反直接 raise。 |
| caregiver 人格 / 生命周期复杂（离世 / 新增照护者） | 中 | caregiver 节点支持 `metadata.status ∈ {active, inactive, deceased}`；`edge_cared_by` 带 `phase_span` 表明照护跨度；照护者替换场景只 update 原节点 status + 新增节点，不删除历史关系边。 |
| womb 图与 cradle 图的 `baby_this` UUID 实际不一致（不同 namespace 或 raw_id 拼写差异） | 高 | 本提案明确要求**同一命名空间 + 同一 raw_id**（`baby_this` 或 `baby:{baby_id}`，两侧冻结相同拼写），`graph_emit.py` 通过 `from backend.womb.graph_emit import make_node_uuid` 直接复用，保证字节一致；单元测试 `test_baby_id_cross_graph_consistency` 强制断言。 |
| scheduler 的 events.jsonl 写入 vs graph_delta 发射时序错位 | 中 | graph_delta 作为 SSE 事件 payload 的字段**同步**产出（不另开通道），events.jsonl 先写入再推送 SSE，前端只在收到 SSE 后消费；断线重连时前端 `/baby/{id}/cradle-graph` 拉一次快照恢复，之后增量续传（本期：断线重连只拉快照不做增量续传，简化）。 |
| 前端 `useCradleGraph` 与 `useLifeline` 共用 SSE 连接的订阅冲突 | 低 | `useCradleGraph` 通过 props 接收从 `useLifeline` 暴露的 `applyEvent` 钩子（或直接挂 `onEvent` 回调），共享同一 EventSource，不另开连接；`useLifeline.js` 改造为支持 `onEvent` 回调订阅者（后续可扩展成多个 hook 共享一条 SSE）。 |
| 历史 baby 旧 `cradle_graph.json` 残留混入新 schema | 低 | `load_cradle_graph` 读取时检测 `metadata.schema` 字段，缺失或非 `v3-business-as-graph` 直接返回 `None`，端点返回 404 + 提示"此 baby 的 cradle 图谱需要重新跑一次生命"。 |
| critical_event 等待父母处理时间不定，graph_delta 幂等性 | 中 | critical_event 首次 emit 时 `event` 节点 `metadata.status: "pending"`；父母 resolve 时 `update_nodes` 把 status 改为 `resolved` + 追加 `resolution` / `caregiver_id` / `decided_at`；绝不 remove 已 emit 的 pending 节点，保留完整决策轨迹。 |

## 技术路径概览

### 数据流

```
DES 调度器 push phase_start / day_tick / phase_complete / critical_event 事件
       │
       ↓
scheduler/handlers.py 处理事件
  ├─ 调用 cradle.nanny.simulate_phase_stream / resolve_critical_event / complete_phase
  ├─ 各业务函数顺手产出 graph_delta
  └─ merge_deltas(*) 聚合塞进事件 payload
       │
       ↓
state.append_event(baby_id, event_with_graph_delta)  → events.jsonl 写入
       │
       ↓
/lifeline SSE 把事件连同 graph_delta 一起推送到前端
       │
       ↓
frontend/src/hooks/useLifeline.js onEvent → useCradleGraph.applyEvent
       │
       ↓
mergeGraph(state, delta) → LifeGraph.jsx 渲染
  实时显示生命成长（capability 解锁 / 里程碑达成 / 能力回退 / 依附漂移）
       │
       ↓
born / deceased / cradle_complete 时
  backend/api/registry.save_cradle_graph(baby_id, accumulated_graph)
       → archive/{baby_id}/cradle_graph.json
```

### graph_delta 四种原子操作（与 womb 对齐）

```typescript
type GraphDelta = {
  add_nodes?: Node[]
  add_edges?: Edge[]
  update_nodes?: Partial<Node>[]   // 必须带 id
  update_edges?: Partial<Edge>[]   // 必须带 uuid
  remove_nodes?: string[]
  remove_edges?: string[]
}
```

### 节点 / 边的 schema 契约

见 `specs/cradle-graph/spec.md` 的 Requirement: 节点契约 / 边契约 / progression 与 phase 两分。

### 最终样本的形态

`frontend/src/data/cradle-growth-sample.json` 作为"设计参考实现"（design-as-code），后端 emit 逻辑以它为输出契约。样本应描绘一个虚拟宝宝走完 12 阶段的完整图（含一次压力回退、一次依附漂移、两次 critical_event、多重边 caregiver↔baby、跨 phase_index 的 attachment 状态切换）。

## 向后兼容 / 迁移

- 前端 `LifeGraph.jsx` 组件契约 `{ nodes, edges }` 不变，内部 `adaptEdges` 优先用后端 uuid 的改造已由 womb 提案完成；cradle 边直接通过，无需二次改造。
- `/cradle/{baby_id}/graph` 旧 stub 端点保留一期兼容（返回 empty list），前端在本期内切到新端点 `/baby/{baby_id}/cradle-graph`；下一期提案删除旧端点。
- `/lifeline` SSE 事件新增可选 `graph_delta` 字段，旧客户端忽略该字段不报错（JSON 字段增量扩展本身即兼容）。
- archive 里历史 7 个 baby 的旧 `cradle_graph.json`（v2 删除前残留）保留不动；`load_cradle_graph` 按 schema 版本判别，老数据静默跳过，不做有损迁移。
- `baby_this` 的 UUID 必须与 `archive/{baby_id}/womb_graph.json` 的 `baby_this` 节点 UUID 字节一致；`graph_emit.py` 通过复用 `backend.womb.graph_emit.make_node_uuid` 与相同 raw_id 约定保证。

## 设计模式三问（强制回答 — 详见 CLAUDE.md）

1. **这张图给谁看？讲什么故事？主角是谁？**
   给养育者看、给产品观察者看。故事是"**一个 baby 从新生到可进入世界的发育轨迹——它是如何被照护、被事件塑形、解锁何种能力、带走了哪些恐惧与偏好**"。主角是 `baby_this`（与 womb 图同一节点 UUID，天然接力）。照护者是最重要的配角，事件是情节。

2. **如果只能保留一条性质，保留哪条？**
   **"Baby 是唯一视觉与拓扑中心。"** 所有 capability / milestone / preference / fear / stress 事件 / 依附状态都围绕它辐射，in-degree + out-degree 必须是全图最高（≥ 30）。保留这条意味着放弃"按事件时间线横向摆"的诱惑，回到"以主角为圆心、时间放边上"的范式——这也是本项目已被五次事故验证的唯一正确路径。

3. **spec / sample 的 meta 字段在说什么？哪些不能忽略？**
   - `progression` vs `phase` 两分是 `refactor-cradle-graph-phase-axis` 已冻结的本体论决定，不得再把 12 个全局推进步塞进 `phase` 类别。
   - `BELONGS_TO → dimension` 是 phase 节点的身份证，缺失即孤岛。
   - `role: "anchor"` / `center_anchor: "baby_this"` 是**前端锚定 self 的意图声明**，后端数据必须让 baby 成为入度最高的节点从而让锚定自然涌现，不得靠前端 fx/fy 硬钉。
   - `baby_this` 的 UUID 跨图一致性是**womb 图可以延续到 cradle 图**的唯一技术前提，不得两侧独立随机。
