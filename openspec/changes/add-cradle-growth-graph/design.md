# 技术设计：摇篮成长实时图谱

## 0. 与 womb 图的关系

本设计严格沿用 `openspec/changes/add-womb-conception-graph/design.md` 的全部基础范式：

- **UUIDv5 + 同一 namespace**：`_UUID_NAMESPACE = UUID("6ba7b810-9dad-11d1-80b4-00c04fd430c8")`，与 `backend/womb/graph_emit.py` 一致
- **业务即图（Business-as-Graph）**：不存在独立 reducer / graph_store 模块
- **实体稳定（Continuant Stability）**：每个 continuant 仅一个节点
- **时间在边上（Time on Edges）**：禁止时间节点
- **多重边天然浮现（Multi-edge by Nature）**：uuid 纳入 phase_index / description
- **GraphDelta 四种原子操作**：add / update / remove × {nodes, edges}
- **前端 `LifeGraph.jsx` 零改动**：复用 `adaptEdges` 优先 uuid 策略

本文档**只记录摇篮相对于 womb 的增量与差异**。已在 womb design.md 写清的通用原则（§1-§5 合并语义、UUIDv5 规则等）不再重述。

## 1. 摇篮特有的本体论决定

### 1.1 概念两分（承接 refactor-cradle-graph-phase-axis v3）

| 概念 | 性质 | id 约定 | group / category | 来源 | 角色 |
|------|------|---------|------------------|------|------|
| **progression** | 引擎调度游标（运行时） | `progression:{phase_name}` | `progression` | `cradle.phases.PHASES` 12 步 | 挂在 `baby_this` 下的叙事时间线节点 |
| **phase** | 发育期（领域知识） | `phase:{dim}:{stage}` | `phase` | `cradle.ontology.DIMENSION_PHASES`（新增）6 维 × 4-5 stage | L2 节点，**MUST** 带 `BELONGS_TO → dimension:{dim}` |
| **dimension** | 发育维度 | `dimension:{dim}` | `dimension` | motor / cognitive / language / social / emotional / physical | phase 归属根 |

**铁律**（校验器强制）：
- capability / milestone 的 `OCCURS_IN` 目标 **MUST** 为 per-dim `phase:*`，**MUST NOT** 为 `progression:*`
- phase 节点 **MUST** 带 `BELONGS_TO → dimension:*` 出边
- progression **MUST NOT** 带 `BELONGS_TO → dimension`（它不属于任何维度）
- progression 之间 **MAY** 用 `NEXT` / `PRECEDES` 连接成时间线（本期 `NEXT` 一种即可）

### 1.2 主角多于 self

womb 图的主角单一（胚胎 `baby_this`）。摇篮图的主角谱系扩展：

| 主角类型 | 节点类型 | 数量 | 备注 |
|---------|---------|------|------|
| Baby（自我） | `baby_this` | 1 | 与 womb 图**同一 UUID**（跨图延续） |
| 照护者（他者） | `caregiver_{id}` | 1-4 | 母 / 父 / 祖 / 保姆，`metadata.role ∈ {mother, father, grandparent, nanny}` |
| 群聊中其他 baby（同龄他者） | `baby_other:{id}` | 0-N | 仅 conversation 群聊时出现，继承 womb 图 `baby_*` id，本期只做 placeholder |

不同于 womb "所有边终指向 baby_this" 的单中心，摇篮图**有照护者次级中心**，caregiver 节点的入度 + 出度应为全图次高（baby_this 仍最高）。

### 1.3 时间三元组

| 字段 | 类型 | 含义 | 必填场景 |
|------|------|------|---------|
| `phase_index` | int 0-11 | 对应 `cradle.phases.PHASES` 索引 | 所有带时间的因果边 |
| `day_index` | int, optional | 阶段内日序（从 phase_start 起算） | 日常 track 采样 / day_tick 事件 |
| `sim_time` | float, optional | sim_time 时间戳（BabyState.sim_time） | 精细回放场景（本期可选） |

**禁止**把时间元组拼进节点 id（如 `capability_walk_p4_d12`）——时间**只进边 / 只进 metadata.track 数组元素**。

## 2. 节点类型清单

### 2.1 身份层（identity）

| 节点类型 | id 构造 | 数量 | 关键 metadata | 备注 |
|---------|---------|------|--------------|------|
| Baby | `baby_this` | 1 | `baby_id, sex, status`（alive/deceased/world_ready） | **与 womb 图 UUID 一致** |
| Caregiver | `caregiver_{id}` | 1-4 | `role, identity_traits, attachment_state_with_baby, status` | 新生命主角 |
| SpeciesBlueprint | `species_{code}` | 1 | `code` | 从 womb 图继承引用，本期不强制复现 |

### 2.2 调度时间线（progression）

| 节点类型 | id 构造 | 数量 | 关键 metadata |
|---------|---------|------|--------------|
| Progression | `progression:{phase_name}` | 12 | `phase_index, display_name, expression_mode, days_spent` |

12 个节点：`neonatal / sensory_awakening / body_discovery / object_permanence / locomotion / first_word / language_explosion / why_phase / social_budding / rule_understanding / abstract_beginning / independence`

### 2.3 发育维度与发育期（dimension / phase）

| 节点类型 | id 构造 | 数量 | 关键 metadata |
|---------|---------|------|--------------|
| Dimension | `dimension:{dim}` | 6 | `dim_name_en, dim_name_zh, order` |
| Phase (per-dim) | `phase:{dim}:{stage}` | 6 × 4-5 ≈ 28 | `dim, stage_name, age_range_months, bsid_reference?` |

6 维：`motor / cognitive / language / social / emotional / physical`

示例 per-dim phase（详见 `backend/cradle/ontology.py` 静态表）：
- motor: `neonatal / early_infant / late_infant / toddler / preschool`
- cognitive: `sensorimotor_reflex / primary_circular / coordination / symbolic / preoperational`
- language: `cry / cooing / babble / first_words / sentence / narrative`
- social: `imprint / recognize / attachment / parallel_play / cooperative / moral`
- emotional: `reflex_affect / primary_emotions / self_awareness / empathy / regulation`
- physical: `neonate / early_infant / toddler_body / preschool_body`

### 2.4 能力与里程碑层（capability / milestone）

| 节点类型 | id 构造 | 数量 | 关键 metadata |
|---------|---------|------|--------------|
| Capability | `capability_{cap_key}` | 20-40 | `dim, unlocked_at_phase, regression_history[], strength` |
| Milestone | `milestone_{slug}` | 6-15 | `kind, achieved_at_phase, tags` |

cap_key 示例：`walk / babble / object_permanence / self_recognition / pretend_play / rule_following / abstract_reasoning`
milestone kind 示例：`first_word / first_steps / naming / capability_unlock / capability_recovered / separation_success`

### 2.5 心理与偏好层（trait）

| 节点类型 | id 构造 | 数量 | 关键 metadata |
|---------|---------|------|--------------|
| Preference | `preference_{tag}` | 0-10 | `category, strength, acquired_at_phase` |
| Fear | `fear_{tag}` | 0-5 | `severity, acquired_at_phase` |
| ComfortSource | `comfort_{tag}` | 0-5 | `kind`（object / caregiver / routine）, `acquired_at_phase` |
| Attachment | （边上承载，不做节点，见 §3） | - | - |
| Temperament | `temperament` | 1 | `dimensions{openness, neuroticism, ...}, defined_at_phase`（从 womb 图气质节点继承） |

### 2.6 需求与场景层（need / scene）

| 节点类型 | id 构造 | 数量 | 关键 metadata |
|---------|---------|------|--------------|
| NeedType | `need:{trigger}` | ≤ 19 | `urgency ∈ {physiological, emotional, social}, timeout_min`（作为 continuant；每次触发用 event 节点承载，不按触发次数拆分） |
| SceneArchetype | `scene_archetype:{trigger}:{slug}` | 可选 | 首次出现的场景模板，后续同 id 场景以 track 累加；本期**保守不做场景原型节点**，仅做 event |

### 2.7 事件层（event / narrative）

| 节点类型 | id 构造 | 数量 | 关键 metadata |
|---------|---------|------|--------------|
| Event（通用事件） | `event:{type}:{phase_index}:{seq}` | 视实际掷骰 | `event_type, phase_index, day_index, result, trigger_cause` |
| CriticalEvent | `critical:{phase_index}:{seq}` | 0-12 | `status ∈ {pending, resolved}, pending_since, resolved_by, resolution` |
| Regression | `event_regression:{cap}:{phase_index}` | 0-N | `capability_lost, stress_level_at` |
| Recovery | `event_recovery:{cap}:{phase_index}` | 0-N | `capability_regained, strengthened, care_from` |
| Conversation | `conv:{conv_id}` | 0-N | `kind`（dm / group）, `participants, message_count`（随 update 累加） |
| Narrative | `narrative:phase_{idx}` | 0-12 | `phase_index, length_chars, summary` |

### 2.8 从 womb 图继承但本期不强制复现的节点

为避免 cradle 图过大，**默认不把 womb 图所有节点搬进 cradle 图**。只保留：
- `baby_this`（必须，跨图延续基础）
- `temperament`（继承，S6 已定型，后续可能因事件微调）
- 关键 `defect_*`（若存在，影响摇篮期能力约束）
- 关键 `caregiver_mother/father`（若 womb 图已创建照护者身份档案）

其余 womb 节点（hormone / nutrient / teratogen / organ / vital）**不进 cradle 图**，前端若需展示可切换视图分别加载。

## 3. 边类型清单

### 3.1 结构性边（无 phase_index 或单次发生）

| 边类型 | source → target | uuid 载荷 | 多重？ |
|--------|----------------|----------|-------|
| `BELONGS_TO` | Phase → Dimension | `phase\|dim\|BELONGS_TO\|\|` | 否 |
| `DESCENDS_FROM` | Baby → womb 线索节点（如 genome）| 本期可选 | 否 |
| `NEXT` | Progression_i → Progression_{i+1} | 否 | 否 |

### 3.2 发育承担边（以 baby 为中心的时序事件）

| 边类型 | source → target | 典型 metadata | 多重？ |
|--------|----------------|--------------|-------|
| `OCCURS_IN` | Capability/Milestone → Phase(per-dim) | `phase_index` | 否（每 capability 唯一归属） |
| `UNLOCKS` | Event → Capability | `phase_index, day_index, trigger_cause` | 否（每 capability 解锁一次；重建走 RECOVERS） |
| `ACHIEVES` | Baby → Milestone | `phase_index, day_index` | 否 |
| `REGRESSES` | Event(regression) → Capability | `phase_index, stress_level_at` | **是**（同能力可多次回退） |
| `RECOVERS` | Event(recovery) → Capability | `phase_index, strengthened, care_from` | **是** |
| `DRIVEN_BY` | Capability(new) → Capability(prerequisite) | `weight` | 否（预置依赖关系） |

### 3.3 照护关系边（以 caregiver 为中心）

| 边类型 | source → target | 典型 metadata | 多重？ |
|--------|----------------|--------------|-------|
| `CARED_BY` | Caregiver → Baby | `phase_index, day_index, quality, event_ref` | **是**（跨阶段多次） |
| `ATTACHES_TO` | Baby → Caregiver | `phase_index, state ∈ {secure, anxious, avoidant}, since_day` | **是**（状态切换时 emit 新边，不 update 旧边） |
| `NAMED_BY` | Caregiver → Baby | `day_index, name_given` | 否 |
| `SOOTHES` | Caregiver/ComfortSource → Baby | `phase_index, stress_delta` | **是** |
| `STRESSES` | Caregiver/Event → Baby | `phase_index, stress_delta, reason` | **是** |

### 3.4 经验与塑形边

| 边类型 | source → target | 典型 metadata | 多重？ |
|--------|----------------|--------------|-------|
| `TRIGGERED_BY` | Event → NeedType | `phase_index, day_index, resolution` | **是**（同 NeedType 可多次触发） |
| `EXPERIENCES` | Baby → Event/Scene | `phase_index, day_index` | **是** |
| `EXPOSED_TO` | Baby → Event(environmental) | `phase_index, day_index, tag` | **是** |
| `ACQUIRES` | Baby → Preference/Fear/ComfortSource | `phase_index, day_index, source_event_ref` | 否（首次获得，后续强化走 update_nodes） |
| `SPEAKS_TO` | Baby → Conversation | `phase_index, msg_seq` | **是** |
| `CAUSED_BY` | Event → Event/Trait | `phase_index, weight, description` | **是** |

### 3.5 归因与叙事边

| 边类型 | source → target | 典型 metadata | 多重？ |
|--------|----------------|--------------|-------|
| `RESOLVES` | Caregiver → CriticalEvent | `phase_index, day_index, action, tag_effects[]` | 否（每关键事件一次决议） |
| `DESCRIBES` | Narrative → Baby | `phase_index` | 否（每 phase 一条） |
| `TerminatedBy` | Event → Baby | `phase_index, cause ∈ {deceased, world_ready, cradle_incomplete}` | 否 |

## 4. UUID 规则（与 womb 一致）

```python
# backend/cradle/graph_emit.py
from backend.womb.graph_emit import make_edge_uuid, make_node_uuid, _UUID_NAMESPACE
# 直接复用，不另立 namespace
```

**关键**：
- `make_node_uuid("baby_this")` 在 womb 和 cradle 产出**字节相同**的 UUID
- 若业务需要按具体 baby_id 隔离（如 `baby:AC-2026-0421-ABCD`），在 womb 和 cradle 都使用**同一 raw_id 拼写约定**，由常量 `BABY_RAW_ID` 统一
- 本期约定：raw_id = `baby_this`（单胎场景）；多胎 `baby_f1` / `baby_f2`，由 `make_node_uuid(f"baby_f{idx}")` 产出

## 5. emit 策略：何时 add / 何时 update

摇篮图爆量风险远高于 womb（90-120 天 × 12 阶段）。**emit 策略**是核心守门：

### 5.1 add_nodes 触发条件（保守）

只在以下场景 add：
- continuant 首次出现（capability 首次解锁 / fear 首次获得 / caregiver 首次进入）
- 事件型节点（critical / regression / recovery / narrative）每个 phase/day 触发一次

### 5.2 update_nodes 的高频场景（日常采样）

- stress level 每日采样 → `update_nodes({id: "baby_this", metadata: {track_append: {phase, day, stress}}})`
- attachment_per_caregiver 每日或每周采样 → `update_nodes` 追加到 caregiver metadata.track
- capability strength 渐进 → capability 节点 metadata.strength 覆盖写
- preference strength / fear severity 渐进 → metadata 浅合并

### 5.3 禁用反模式

| 反模式 | 表现 | 对策 |
|--------|------|------|
| 每 day_tick add 新节点记录当日指标 | 90 天 × 多指标 = 几百冗余节点 | 走 track_append |
| 把"阶段 N 的压力水平"做成独立节点 | 时间实体化 | 数值在 track，时间是边属性 |
| 每次照护互动 add 一个节点 | 爆量 | 累积到 caregiver.metadata.interaction_count + 只在 quality 阶跃时 emit CARED_BY 边 |
| 场景库每触发一次 emit 一个 scene 节点 | 603 场景 × 多次 = 爆量 | 本期**不做 scene 节点**，只做 event_need 事件节点 |

### 5.4 上限校验（落库前兜底）

`save_cradle_graph` 调用前校验：
- 节点数 ≤ 200，超则 log warning 并降级到只保留 `metadata.critical_nodes_only=true` 的关键节点（capability / milestone / caregiver / baby / progression / phase / dimension）
- 边数 ≤ 400，超则保留权重 top 400

（本期软限制，只 warn 不 reject）

## 6. emit 流程示例

### 6.1 phase_start

```python
# scheduler/handlers.py on_phase_start
from cradle.graph_emit import emit as g
phase_idx = event.payload["phase_index"]
phase_name = PHASES[phase_idx].name

delta = g.merge(
    g.delta_add(nodes=[g.node_progression(phase_name, phase_idx)]),
    g.delta_add(edges=[g.edge_next(prev_phase_name, phase_name)]) if phase_idx > 0 else {},
    g.delta_update(nodes=[{
        "id": g.id_baby(),
        "metadata": {"track_append": {"kind": "phase_start", "phase_index": phase_idx, "sim_time": sim_time}}
    }]),
)
event.payload["graph_delta"] = delta
```

### 6.2 capability 解锁

```python
# cradle/nanny.py complete_phase
for cap_key in newly_unlocked:
    dim = ontology.capability_dimension(cap_key)
    phase_dim_stage = ontology.current_phase_for(dim, phase_idx)
    event_id = f"event:unlock:{cap_key}:{phase_idx}"

    delta = g.merge(
        g.delta_add(nodes=[
            g.node_capability(cap_key, dim, unlocked_at_phase=phase_idx),
            g.node_event("capability_unlock", phase_idx, result=cap_key),
        ]),
        g.delta_add(edges=[
            g.edge_occurs_in(cap_key, dim, phase_dim_stage),          # capability → phase:{dim}:{stage}
            g.edge_unlocks(event_id, cap_key, phase_idx),             # event → capability
            g.edge_achieves(g.id_baby(), f"milestone:{cap_key}", phase_idx),  # 可选
        ]),
    )
    yield delta
```

### 6.3 压力回退

```python
# cradle/nanny.py _check_stress_regression
if regressed:
    event_id = f"event:regression:{cap}:{phase_idx}"
    delta = g.delta_add(
        nodes=[g.node_event_regression(cap, phase_idx, stress_level_at=state.stress.level)],
        edges=[g.edge_regresses(event_id, cap, phase_idx, stress_level_at=...)],
    )
```

### 6.4 critical_event 的两阶段 emit

```python
# 触发时
delta1 = g.delta_add(
    nodes=[g.node_critical(phase_idx, seq, status="pending", reason=...)],
    edges=[g.edge_experiences(baby, critical_id, phase_idx)],
)

# resolve 时（同一 critical_id）
delta2 = g.merge(
    g.delta_update(nodes=[{"id": critical_id, "metadata": {"status": "resolved", "resolved_by": caregiver_id}}]),
    g.delta_add(edges=[g.edge_resolves(caregiver_id, critical_id, phase_idx, action=...)]),
)
```

## 7. 前端架构

### 7.1 hook 复用

```
frontend/src/utils/mergeGraph.js  (新建，从 useWombGraph.js 提炼)
  └─ mergeGraph(state, delta) 纯函数

frontend/src/hooks/useWombGraph.js  (改造)
  └─ import { mergeGraph } from '../utils/mergeGraph'

frontend/src/hooks/useCradleGraph.js  (新建)
  └─ import { mergeGraph } from '../utils/mergeGraph'
  └─ loadSnapshot + applyEvent + reset
```

### 7.2 lifeline SSE 多订阅

`useLifeline.js` 原接口保留，扩展 `onEvent(callback)` 订阅：

```js
const { applyEvent: applyCradleGraphEvent, nodes, edges } = useCradleGraph()
useLifeline(babyId, { onEvent: applyCradleGraphEvent })
```

EventSource 单实例，多订阅者共享，避免 /lifeline 被两次订阅。

### 7.3 渲染路径

```
Cradle.jsx
  └─ useCradleGraph(babyId)
     └─ (可选) useEffect: fetch /baby/{id}/cradle-graph → loadSnapshot 作为历史重播起点
     └─ useLifeline(babyId, { onEvent: applyEvent })
  └─ <LifeGraph nodes={nodes} edges={edges} onNodeClick={...} />
```

## 8. 落库设计

### 8.1 后端累积图状态

```python
# scheduler/handlers.py 或 cradle/nanny.py 的 session 层
_cradle_graph_state = {"nodes": {}, "edges": {}}

def apply_delta_to_state(state, delta):
    for n in delta.get("add_nodes", []):
        state["nodes"][n["id"]] = n
    # ... 同 frontend mergeGraph
```

### 8.2 落库触发点

- `phase_complete` 事件（每阶段存一次快照，作为增量保护）
- `born` → 不触发（摇篮启动，不是终局）
- `cradle_complete` / `world_ready` / `deceased` → 最终落库

### 8.3 文件格式

`archive/{baby_id}/cradle_graph.json`：

```json
{
  "baby_id": "AC-...",
  "species": "human",
  "sex": "female",
  "schema": "v3-business-as-graph",
  "status": "world_ready",
  "saved_at": "2026-04-22T10:00:00Z",
  "phases_completed": 12,
  "nodes": [...],
  "edges": [...],
  "stats": {
    "node_count": 118,
    "edge_count": 241,
    "by_group": { "identity": 3, "progression": 12, "dimension": 6, "phase": 28, ... },
    "multi_edges": { "caregiver_mother->baby_this:CARED_BY": 5 }
  }
}
```

### 8.4 查询端点

```
GET /baby/{baby_id}/cradle-graph
  200: 完整 JSON 快照
  404: {detail: "Cradle graph not found for baby '{id}'"}
```

`/cradle/{baby_id}/graph` 旧 stub 端点保留**一期**（返回 `{nodes:[], links:[]}`），文档标注 deprecated，下期删除。

## 9. 风险与应对（摇篮特有）

### 9.1 baby_this UUID 跨图不一致

**最高风险**。缓解：
- 定义**单一常量**：`BABY_SELF_RAW_ID = "baby_this"`，由 womb 与 cradle 共同引用（放在共享模块如 `backend/common/graph_ids.py`，或由 cradle 直接 import womb）
- 单元测试强制：`assert make_node_uuid_womb("baby_this") == make_node_uuid_cradle("baby_this")`
- 落库时 `cradle_graph.json` 包含 `baby_this_uuid` 字段冗余记录，前端合并时按字节对齐检查

### 9.2 多照护者图复杂化

缓解：
- 本期 `metadata.role` 枚举严格限死：`mother / father / grandparent / nanny`
- 照护者档案变更（如父母离婚、保姆换人）通过 `update_nodes.metadata.status: inactive` 表达，不删节点
- `ATTACHES_TO` 状态切换走新边（multi-edge），旧状态边不 update 也不 remove，保留完整依附史

### 9.3 critical_event 悬挂态

pending 的 critical_event 节点若永不 resolve（家长 AFK），图谱一致性如何？
- pending 状态在 `metadata.status` 字段可见，前端可视觉区分（如边框虚线）
- baby 进入下一阶段仍 pending 的，emit 额外 `event:critical_unresolved` 归因边指向原 critical 节点
- 落库时保留 pending 状态，不强制 resolve

## 10. 本体论对比表（womb vs cradle）

| 维度 | womb 图 | cradle 图 |
|------|---------|-----------|
| 图中心 | baby_this（单） | baby_this（主）+ caregiver_*（次） |
| 时间坐标 | `stage_index` ∈ 1-7 | `phase_index` ∈ 0-11 + 可选 `day_index` |
| 主要事件驱动 | stages.express_stream 编排 | DES scheduler 事件循环 |
| 落库触发 | `born` 事件 | `phase_complete` × N + 终局事件 |
| 多重边主力 | hormone→organ / nutrient→organ | caregiver→baby CARED_BY / baby→caregiver ATTACHES_TO |
| 跨图 continuant | — | baby_this UUID 与 womb 图字节一致 |
| 反模式防护 | 禁 `stage_N` 节点 | 禁 `stage_N` / `day_N` / `phase_x_day_y` 节点 |
| 节点规模 | 30-45 | 80-150 |
| 边规模 | 60-85 | 180-320 |

## 11. 命名决策

- 节点组 `group` 枚举：`identity | progression | dimension | phase | capability_milestone | trait | need | event | narrative | caregiver`（10 类，前端配色表对齐）
- 边类型大写下划线（`BELONGS_TO` / `ATTACHES_TO` / `SPEAKS_TO`）：与 womb 一致
- `progression` 节点 id 用 `:` 分隔（`progression:neonatal`），与 phase 保持视觉同构
- 新建 `backend/cradle/ontology.py` 存放 `DIMENSION_PHASES` 静态表（per-dim phase 清单）与 `CAPABILITY_DIMENSION_MAP`（capability → dim 路由表），供 `graph_emit.py` 和未来 `validate.py` 共享

## 12. 开放问题（本期不解决）

1. **LLM 参与 graph_fragment**：阶段总结 LLM 吐补充因果边
2. **womb ↔ cradle 联合视图**：前端 UI 层跨图展示
3. **世界阶段延续**：cradle_complete → 进入 world，下一阶段图谱是否继承（工作 / 伴侣 / 子代）
4. **回放滑块**：按 phase_index 过滤边，实现阶段回放
5. **跨 baby 对比视图**：同家族多 baby 图并列渲染
6. **断线重连后的增量续传**：本期只做 snapshot 重载，实时续传延后
