# 变更提案：子宫受孕实时图谱（业务即图 · 实体稳定 · 时间入边）

## 动机

当前子宫模块（`backend/womb/`）通过 SSE 流式输出每阶段的生理数据（激素、营养、毒素、体征、命运掷骰、LLM 叙事），但这些**因果丰富的时序数据**在前端只能以数值/文本列表呈现，用户看不到"**谁影响了谁、什么时候发生、为什么**"的整体全貌。

同时，`LifeGraph.jsx` 前端渲染组件已就绪（多重边曲率分散、自环合并、贝塞尔中点标签等视觉能力完整），但缺少与之配套的后端图谱数据管道。

前期尝试（2026-04-20 上线、2026-04-21 被用户推翻重来的 lifegraph 模块）走了"独立 reducer + 全量重算"的路线，**把图谱生成当成独立模块来维护**，结果：

1. **业务与图漂移**：子宫新增字段（如 DHA、血氧）后，reducer 要同步改，否则图丢信息。
2. **时间建模错误**：v1/v2 样本把 `cortisol_s2`、`cortisol_s4`、`cortisol_s6` 拆成多个节点，把"时间"固化进了节点身份，违反 continuant（持续体）设计原则。
3. **引入 Stage 伪节点**：把"受精卵期"等时间坐标当成图节点，让 baby `DEVELOPS_THROUGH → stage_2` 读起来像"胚胎拥有阶段作为成分"，本体论上错误。
4. **多重边信息丢失**：同一对节点间（如 cortisol → heart）跨阶段的多次不同强度调控被"合并"或"覆盖"，失去 Zep/Graphiti 这类时序图谱的核心价值。

本提案推翻 v1/v2 的设计路径，落地一套**业务即图**的新架构。

## 目标

- **G1 业务即图**：取消独立的 `graphify.py` / `reducer.py` 模块，图谱更新**作为业务函数的副产品**随 SSE 事件 `graph_delta` 字段流出。
- **G2 实体稳定**：每个 continuant（激素、营养、毒素、器官、体征等）在整个怀孕过程中**仅一个节点**，不按阶段拆分。
- **G3 时间在边上**：时间坐标（`stage_index`）作为**边的属性**，不作为节点。取消所有 Stage 节点。
- **G4 多重边天然浮现**：同一对节点（如 `hormone_cortisol → organ_heart`）在不同阶段的不同强度调控，表达为**同一对节点间的多条边**（每条带自己的 `stage_index` + `weight` + `description`），通过边的 content-hash uuid 保证唯一不碰撞——**uuid 不承载语义，语义在 `type` 和 `stage_index` 字段**。
- **G5 实时增量渲染**：前端通过 SSE 订阅 `graph_delta`，执行 `add/update/remove` 四种原子操作合并到本地图状态，用户看到"生命树实时生长"。
- **G6 零维护扩展**：新增业务字段（如一种新激素）只需在对应业务函数里加三行 `emit_*` 调用，reducer、schema 注册、前端组件**均无需改动**。
- **G7 LifeGraph.jsx 不改核心渲染**：前端适配层在现有 `adaptNodes/adaptEdges` 基础上做最小扩展（支持 `update_nodes`/`update_edges`/`remove_*` 四种 delta 操作），保留全部视觉资产（多重边曲率、自环合并、贝塞尔标签）。
- **G8 图谱按 baby_id 落库**：每次孕育完成（含流产/发育失败）后端把累积的图快照保存到 `archive/{baby_id}/womb_graph.json`；提供 `GET /baby/{baby_id}/womb-graph` 端点供前端回读历史。
- **G9 i18n 双语 narrative**：节点 narrative 字段同时携带 `zh_CN` 和 `en`，前端按当前语言渲染，fallback 到另一语言，避免摘要文字与界面语言错位。

## 范围

### 包含

- **后端**：
  - `backend/womb/graph_emit.py`（**新增**）：纯函数帮手库，约 100 行，定义节点构造器（`node_hormone`、`node_nutrient`、`node_organ`、`node_event`、`node_vital`...）和边构造器（`edge_modulates`、`edge_feeds`、`edge_damages`、`edge_exposed`、`edge_caused_by`、...），以及 `delta_add`/`delta_update`/`delta_remove`/`merge_deltas` 工具。
  - `backend/womb/hormones.py` / `nutrients.py` / `teratogen.py` / `vitals.py` / `fate.py` / `dynamic_env.py` / `stages.py`（**修改**）：各业务函数在产出业务数据的同时，顺手 emit 对应的 `graph_delta`。
  - `backend/api/conceive.py`（**修改**）：SSE 事件结构扩展 `graph_delta` 字段，保持向后兼容（旧字段不动）。
- **前端**：
  - `frontend/src/hooks/useWombGraph.js`（**新增**）：约 40 行，订阅 conceive SSE，把 `graph_delta` 合并到本地 `{nodes, edges}` 状态。
  - `frontend/src/components/LifeGraph.jsx`（**最小修改**）：`adaptEdges` 的 `uuid` 构造规则支持 `stage_index` 纳入 key（保证多重边不被去重）；顶层渲染支持外部传入完整 nodes/edges 数组（已有接口，无须重构）。
  - `frontend/src/Cradle.jsx` 或对应页面（**修改**）：接入 `useWombGraph` hook，把图谱渲染到 Cradle 的 conceive 会话详情里。
- **样本数据**：
  - `frontend/src/data/womb-conception-sample.json`（**已存在 v2/v3，修正为最终形态**）：按"实体稳定 + 时间入边 + 无 Stage 节点"重写，作为前端离线调试基准 + 后端产出契约参考。

### 不包含

- **LLM graph_fragment 扩展**：允许 LLM 在阶段叙事中额外吐出 `graph_fragment` 补充因果边的能力（如发现"母体焦虑 → 胎动下降"这种非结构化关联）——本变更**预留接口字段但不在本期实现**，首期所有 delta 均由业务代码确定性产出。下一期独立变更推进。
- **cradle 与 womb 图的打通**：受孕图与摇篮图暂时各自独立，**不做 continuant_id 跨图串联**。下一期独立变更推进。
- **跨怀孕对比视图**：多次受孕的图并列展示（不同种族 / 环境 / 遗传对比）不在本期。
- **时间轴回放滑块**：前端按 `stage_index` 滑动只显示部分边的交互——**预留数据基础**（所有边都带 `stage_index`），UI 滑块不在本期。
- **Neo4j / Graphiti 接入**：本期图谱**只在内存 + 前端状态 + JSON 文件落库**三处存在，不接入图数据库。
- **图谱分析 / 路径查询 / 归因推理 API**：本期只做"记录 + 快照查询"，不做图上推理/复杂遍历。

## 成功标准

- ✅ 一次 human 物种 7 阶段完整怀孕跑完后，前端能看到一张 30-45 节点 / 60-85 边的实时生成图。
- ✅ `hormone_cortisol → organ_heart` 至少 3 条多重边（S2/S4/S6），在前端自动以曲率分散呈现。
- ✅ `hormone_cortisol → organ_brain`、`hormone_thyroid → organ_brain`、`nutrient_folate → organ_brain` 等多对节点表现出多重边。
- ✅ 图中**不存在** `stage_1`...`stage_7` 这样的 Stage 节点；时间信息全部在边的 `stage_index` 属性上。
- ✅ 每个 continuant 实体（cortisol、folate、alcohol、heart、brain 等）在整个图中**仅一个节点**。
- ✅ SSE 流式推送：每个业务事件（激素计算、营养采样、命运掷骰、毒素暴露、缺陷获得）到达后，前端图能在 100ms 内出现对应节点/边，用户可视觉感知"生长"。
- ✅ 归因链可追溯：点击 `defect_heart_murmur` 节点能沿 `AFFECTS → baby` ← `RESULTS_IN ← event_defect_roll` ← `CAUSED_BY ← nutrient_folate / teratogen_alcohol` 四跳路径找到全部原因。
- ✅ 业务代码加新字段（新激素 / 新毒素）零 reducer 改动：只在对应业务函数 `compute_*` 里添加 `emit_*` 调用。
- ✅ 前端 `LifeGraph.jsx` 对无 `graph_delta` 的旧 SSE 事件保持兼容（不 crash，空图渲染 empty state）。
- ✅ 流产场景（mid-pregnancy `roll_miscarriage` 命中）：SSE emit `remove_edges` / 特殊终止节点，前端正确处理（后续阶段节点不再增长，事件节点显著标记）。

## 风险与缓解

| 风险 | 等级 | 缓解 |
|------|------|------|
| 业务代码里嵌图语义，业务/图耦合增加 | 中 | 所有图相关代码集中在 `graph_emit.py` 帮手函数中，业务函数只调用 `emit_*()`，不直接写 dict。图 schema 变更只改一个文件。 |
| 多重边的 `uuid` 碰撞导致前端去重丢边 | 低 | `uuid = "e_" + md5(source\|target\|type\|stage_index\|description)[:10]`，content-hash 方案对正文唯一。`graph_emit.py` 通过纯函数生成 uuid 消除手写错误。uuid 不承载语义。 |
| 前端合并 delta 的 reducer 性能问题（大图 update_nodes 深合并） | 低 | 预估 7 阶段最多 ~80 边 / 45 节点，数量级远低于 D3 force simulation 性能瓶颈（通常 1000 节点内流畅）。若未来流式 LLM 叙事 delta 频繁，则在 hook 内加 100ms throttle。 |
| `useWombGraph` 与现有 Cradle SSE 订阅冲突 | 低 | `useWombGraph` 只添加 `graph_delta` 事件监听，不干扰现有 `stage_in_progress` / `conception_complete` 等事件的业务逻辑。 |
| LifeGraph 组件的 `adaptEdges` uuid 构造规则变更破坏现存功能 | 低 | `adaptEdges` 优先用后端提供的 `e.uuid`，缺失时 fallback 到原 `${source}->${target}:${type}` 构造——旧数据走 fallback 分支，行为不变。 |
| 流产/中止场景下未来阶段节点已被 emit，需要撤回 | 中 | `graph_delta` 支持 `remove_nodes` / `remove_edges` 原子操作；流产事件 emit 时除了加 Event 节点，同步 `remove` 本不该存在的未来阶段相关节点。具体策略：流产前不预 emit 未来阶段节点，流产触发即 emit 最终 `TerminatedBy` 边 + baby 节点状态 update。 |
| LLM 叙事 SSE 事件字段 `graph_delta` 被 LLM 误污染 | 低 | 首期 LLM 不参与 graph_delta 构造（全部业务代码确定性产出）。LLM graph_fragment 延后到下一期，届时加严格校验（白名单节点 id + 白名单边类型 + weight 下限）。 |

## 技术路径概览

### 数据流

```
用户点"受精" → POST /api/conceive
       │
       ↓
backend/womb/conceive() 编排
       │
       ├─ 调用 heredity/environment/fate/stages 等业务函数
       │         │
       │         └─ 每个函数顺手返回 graph_delta
       │
       ↓
api/conceive.py SSE 事件
  { stage, hormones, vitals, ..., graph_delta }
       │
       ↓
frontend/src/hooks/useWombGraph
  监听 SSE → 调用 mergeGraph(state, delta)
       │
       ↓
LifeGraph.jsx 渲染 {nodes, edges}
  实时增量显示生命树生长
```

### graph_delta 四种原子操作

```typescript
type GraphDelta = {
  add_nodes?: Node[]       // 新实体出现
  add_edges?: Edge[]       // 新关系发生
  update_nodes?: Partial<Node>[]   // 实体属性变化（如 track 数组追加）
  update_edges?: Partial<Edge>[]   // 边属性变化
  remove_nodes?: string[]  // 按 id 移除（流产等场景）
  remove_edges?: string[]  // 按 uuid 移除
}
```

### 节点 / 边的 schema 契约

见 `specs/womb-graph/spec.md` 的 Requirement: 节点契约 / 边契约。

### 最终样本的形态

`frontend/src/data/womb-conception-sample.json` 作为"设计参考实现"（design-as-code），后端 emit 逻辑以它为输出契约。样本已按本提案原则写成 v3。

## 向后兼容 / 迁移

- 前端 `LifeGraph.jsx` 组件对外契约 `{ nodes, edges }` 不变，内部 `adaptEdges` **优先使用后端提供的 `e.uuid`**（本期后端产出的边一律携带 content-hash uuid）；仅在 uuid 缺失时 fallback 到原有的 `${source}->${target}:${type}` 构造规则作为兜底。**旧数据不受影响**。
- 后端 SSE 事件新增 `graph_delta` 字段，旧客户端忽略该字段不报错（JSON 字段增量扩展本身即兼容）。
- 本期不涉及持久化，无需数据迁移脚本。
