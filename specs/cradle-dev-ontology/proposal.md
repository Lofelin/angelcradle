# 摇篮发育图谱本体论重构方案（Draft v0.1）

> 状态：**待多方评审**
> 作者：lifulin + Claude
> 日期：2026-04-17

## 1. 背景与问题

### 1.1 现状
当前摇篮（cradle）图谱基于 `backend/cradle/causality.py` 生成。以 baby `AC-20260417-14297` 为例：

| 指标 | 数值 | 理想值 |
|------|------|--------|
| 节点数 | 91 | - |
| 边数 | 84 | ≥ 节点数-1 |
| 连通分量数 | **39** | **1** |
| 孤立单点数（度数=0） | **33 (36%)** | 0 |
| 与 Newborn 不连通的节点 | **53 (58%)** | 0 |

### 1.2 用户视觉症状
- 图谱散成 N 个孤岛，没有层级
- "Sitting / Walking / Running" 之间看不出进化链条
- "擅长跑步" 这种经验塑造的特化能力无处安放
- 时间轴缺失：无法看到"6 个月时的图谱"vs"12 个月时的图谱"

### 1.3 根因
**边的语义不完整**：节点被大量创建，但生成规则里没有强制约束每个能力必须挂回维度/阶段。结果就是很多 capability / milestone 节点"空降"到图谱里，没有连接。

## 2. 理论基础（已通过文献验证）

| 理论 | 出处 | 对本方案的支撑 |
|------|------|----------------|
| **Bayley / Denver II 五维评估** | 儿童发育筛查金标准 | 图谱 L1 的多维度结构 |
| **WHO 六大粗大运动里程碑** | WHO Motor Development Study | EVOLVES_FROM 硬编码链条 |
| **Piaget 认知四阶段** | 感知运动/前运算/具体运算/形式运算 | Cognitive 维度的 Phase 结构 |
| **Thelen 动力系统理论** | 技能从环境×任务×身体的交互中涌现 | REINFORCES / SPECIALIZES 边语义 |
| **纵向发育轨迹建模（Growth Curve）** | 起始值 + 变化率 + 渐近线 | 时间戳字段 + strength 属性 |
| **Cephalocaudal / Proximodistal 原则** | 头→脚、躯干→四肢 | 技能进化顺序硬编码 |
| **Thomas & Chess 气质九维** | 气质 → 大五人格投射 | 性格/气质维度建模 |

## 3. 提议本体（Ontology）

### 3.1 六层分形结构

```
L0  Baby（生命体）                    isCore = true，唯一
    │
L1  Dimension（维度，8 个并列正交的 axis）
    ├─ motor         运动（粗大 + 精细）
    ├─ language      语言（理解 + 表达）
    ├─ cognitive     认知（Piaget）
    ├─ socioemotional 社会情感
    ├─ selfreg       自我调节
    ├─ temperament   气质/性格
    ├─ physical      生理（身高/体重/睡眠）
    └─ attachment    依恋
    │
L2  Phase（阶段，per dimension）
    motor 维度 ─┬─ Neonatal 0-1m
                ├─ Early Infant 1-4m
                ├─ Late Infant 4-12m
                ├─ Toddler 1-2y
                └─ Preschool 2-5y
    │
L3  Capability（能力，位于特定 Phase）
    motor/Late Infant ─┬─ 翻身
                       ├─ 坐稳
                       ├─ 匍匐爬
                       └─ 四肢爬
    （同链条通过 EVOLVES_FROM 相连）
    │
L4  Milestone（里程碑，首次事件）
    First Step @ day 365
    First Word @ day 300
    │
L5  Event / Experience（日常事件）
    "training:running × 7 days"
    "stranger_comfort × 1"
```

### 3.2 节点字段约定

```jsonc
{
  "node_id": "capability:motor:walking",
  "category": "capability",              // baby | dimension | phase | capability | milestone | event
  "dimension": "motor",                   // L1 归属
  "phase_id": "phase:motor:toddler",     // L2 归属
  "name": "Walking",
  "display_name": "Walking",

  // 时间维度（NEW）
  "emerged_at": 365,                      // 首次出现（天数）
  "mastered_at": 410,                     // 稳定掌握
  "last_reinforced": 500,
  "strength": 0.78,                       // 当前熟练度 0~1

  // 可选
  "bayley_code": "GM-W",                 // 对标 Bayley 量表
  "who_milestone": "walking_alone"       // 对标 WHO 标准
}
```

## 4. 边 Schema（关键改进）

### 4.1 9 种边类型

| 边类型 | 语义 | 必须性 |
|--------|------|--------|
| `BELONGS_TO` | capability/milestone → dimension | **强制**（解决孤岛） |
| `OCCURS_IN` | capability/milestone → phase | **强制**（解决孤岛） |
| `EVOLVES_FROM` | 能力 A ← 能力 A'（新能力从旧能力进化） | 同维度同链条必须 |
| `ENABLES` | 前提依赖（坐稳 ENABLES 爬） | 可选 |
| `EMERGES_AT` | milestone → 时间戳节点 | milestone 强制 |
| `REINFORCES` | event → capability（经验增强） | 事件驱动 |
| `SHAPES` | event → trait/preference | 性格塑造 |
| `SPECIALIZES` | capability → capability（"擅长跑步"） | 可选 |
| `REGRESSES` | capability 退行（生病后） | 临时 |

### 4.2 边字段

```jsonc
{
  "edge_id": "e_xxx",
  "source_id": "capability:motor:walking",
  "target_id": "capability:motor:running",
  "edge_type": "EVOLVES_FROM",
  "effective_from": 410,
  "effective_to": null,                   // null = 仍有效
  "weight": 0.9,                           // 边强度
  "evidence": "rct|theoretical|observed"
}
```

## 5. 约束规则（关键）

### 5.1 反孤岛约束
- **RULE-1**：任何 `capability` 节点**必须**同时有 `BELONGS_TO` 边指向一个 `dimension` 节点
- **RULE-2**：任何 `capability` 节点**必须**有 `OCCURS_IN` 边指向一个 `phase` 节点
- **RULE-3**：任何 `milestone` 节点必须有 `OCCURS_IN` 边
- **RULE-4**：任何 `event` 节点必须至少有一条 `REINFORCES` 或 `SHAPES` 边

### 5.2 进化链约束
- **RULE-5**：同维度同阶段内的多个 capability 应通过 `EVOLVES_FROM` 链接成 DAG

### 5.3 时间约束
- **RULE-6**：`emerged_at ≤ mastered_at ≤ last_reinforced`
- **RULE-7**：边的 `effective_from ≥ source 和 target 的 emerged_at`

## 6. 迁移路径

### Phase 0：基础设施（1-2 天）
- [ ] 定义 `backend/cradle/ontology.py`：节点/边/约束常量
- [ ] 预置 WHO/Bayley/Piaget 标准序列为 `SEEDS` 数据
- [ ] 加 `validate_graph(graph)` 函数检查 RULE-1~7

### Phase 1：后端边生成规则重写（2-3 天）
- [ ] 重构 `backend/cradle/causality.py` 中节点生成，每次 emit capability 必须同时 emit BELONGS_TO + OCCURS_IN
- [ ] 加 EVOLVES_FROM 链自动生成（按 WHO 序列）
- [ ] 加 event → capability 的 REINFORCES 边

### Phase 2：前端适配（1-2 天）
- [ ] `LifeGraph.jsx` 识别新的 edge_type，渲染分色
- [ ] `graphConfig.js` 补全 EDGE_CONFIG
- [ ] 时间轴 scrubber（可选）：按 `effective_from` 过滤

### Phase 3：历史数据回填（1 天）
- [ ] 对现有 babies 运行 `repair_graph.py` 脚本，自动补 BELONGS_TO / OCCURS_IN
- [ ] 孤立节点按 name 匹配预置 WHO/Bayley 标签补齐

### Phase 4：时间回放（可选，3-5 天）
- [ ] 前端时间轴组件
- [ ] 按 `effective_from/to` 过滤的图谱快照查询

## 7. 开放问题（待评审回答）

1. **EVOLVES_FROM 链来源**：硬编码 WHO/Bayley 序列 vs LLM 推断？
2. **时间戳粒度**：按天（实时模拟）vs 按里程碑事件？
3. **孤岛兼容**：过渡期允许 capability 无 BELONGS_TO 但标记 `__orphan: true`，还是强制拒绝？
4. **Dimension 个数**：8 个够吗？是否考虑合并（如 selfreg 并入 cognitive）？
5. **Phase 重叠**：一个 capability 能跨两个 phase 吗（如 Walking 从 Late Infant 持续到 Toddler）？
6. **历史节点的时间戳回填**：无时间戳的老数据怎么处理？
7. **性能**：引入时间过滤会让前端渲染从"全部节点"变成"当前时刻可见节点"，是否需要后端查询预过滤？

## 8. 风险清单

| 风险 | 等级 | 缓解 |
|------|------|------|
| 破坏现有 91 节点图谱 | 高 | Phase 3 回填 + 允许老节点渐进迁移 |
| Schema 频繁变更 | 中 | 先冻结 v1 schema 再实现 |
| LLM 生成边时命中率低 | 中 | 硬编码 WHO/Bayley seed 兜底 |
| 时间维度引入前端复杂度 | 中 | Phase 4 可延后 |
| 图谱变得过于密集难看 | 低 | 节点可按 dimension 过滤 |

## 9. 已实现状态

- **2026-04-20**：第 3 节 L2 per-dimension Phase 已通过 OpenSpec 变更 `refactor-cradle-graph-phase-axis` 落地到 v3 cradle 图谱。
  - 新增 `cradle.ontology.DIMENSION_PHASES`（6 维 × 4-5 stage = 22 个 per-dim phase）
  - `cradle_graph_store.py` 全部 `save_*_graph` 重写：phase 节点改为 `phase:{dim}:{stage}` 形式，强制 `BELONGS_TO → dimension`
  - 原 12 个全局推进步降级为 `progression:{name}`（独立 category，叙事时间线）
  - `cradle.validate` 增加 `META-RULE-PHASE` + `META-RULE-OCCURS-TARGET`
  - `scripts/migrate_cradle_graph_v2_to_v3.py` 完成现有 baby 数据无损升级
- 第 4 节时间维度（emerged_at/mastered_at/strength）+ 第 6 节 Phase 4 时间回放 仍为待办。
