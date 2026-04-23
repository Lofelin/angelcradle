# 技术设计：子宫受孕实时图谱

## 1. 设计原则

### 1.1 本体论原则（Ontology）

| 概念 | 图中角色 | 示例 |
|------|---------|------|
| **Continuant（持续体）** | 节点 | baby / cortisol / folate / heart / brain |
| **Occurrent（事件 / 关系）** | 边 或 事件节点 | cortisol→heart 的调控、defect_roll 掷骰 |
| **Temporal Coordinate（时间坐标）** | **边的属性**（`stage_index`） | 不是节点 |

**核心规则**：
- 一个实体在整个怀孕过程中**仅一个节点**，不按阶段拆分。
- 时间不是实体，不配当节点。时间作为边的 `stage_index` 属性存在。
- 事件（掷骰、流产判定）是"特定时刻发生的具体动作"，有独立身份，可以是节点。

### 1.2 业务即图原则（Business-as-Graph）

不存在独立的"图谱生成器"模块。每个业务函数在产出业务数据的同时，**顺手返回 `graph_delta`**。编排层（`stages.py` 的 `express_stream`）把多个子系统的 delta 通过 `merge_deltas()` 聚合，塞进 SSE 事件。

**关键好处**：业务代码改什么、图就改什么，永不漂移。不需要维护"如果业务加了 X 字段，reducer 要同步加 Y 条规则"这种元级联动。

### 1.3 多重边天然浮现（Multi-edge by Nature）

同一对实体（如 cortisol 和 heart）在不同阶段的不同强度调控，表达为**同一对节点间的多条边**，每条边独立存在、独立记录自己的时间与强度。前端按 uuid 唯一性识别，自动以曲率分散渲染成扇形。

这和 Zep / Graphiti 的时序知识图谱模型同构。

## 2. 节点类型清单

### 2.1 身份层（identity）

| 节点类型 | id 构造 | 数量 | 关键 metadata |
|---------|---------|------|--------------|
| Baby | `baby_this`（单胎）或 `baby_f{idx}`（多胎） | 1-N | `sex`, `baby_id`, `status: alive/miscarried/stillborn` |
| SpeciesBlueprint | `species_{code}` | 1 | `code: human/dog/cat` |
| ParentGenome | `genome_{side}` | 2 | `side: father/mother`, 10 个性状的等位基因 |
| MethylationMap | `methylation` | 1 | `twin_divergence`, `tags` |

### 2.2 母体舞台层（maternal_stage）

| 节点类型 | id 构造 | 数量 | 关键 metadata |
|---------|---------|------|--------------|
| Birthplace | `birthplace_{code}` | 1 | `name`, `coordinates`, `pollution_index` |
| Hormone | `hormone_{name}` | 4（cortisol/thyroid/sex/hcg） | `kind: hormone`, `track: [{stage_index, level, ...}]`, `baseline`, `continuant_id` |
| Nutrient | `nutrient_{name}` | 5（folate/iodine/iron/dha/calcium） | `kind: nutrient`, `track`, `continuant_id` |
| Teratogen | `teratogen_{name}` | 按实际暴露项创建（可选集合：alcohol/pm25/stress/smoke/radiation/drug/infection） | `kind: teratogen`, `continuant_id` |

### 2.3 身体构筑层（embodiment）

| 节点类型 | id 构造 | 数量 | 关键 metadata |
|---------|---------|------|--------------|
| Organ | `organ_{name}` | 7（heart/brain/lung/liver/kidney/eye/ear） | `formation_stage`, `maturation_stage`, `continuant_id` |
| Vital | `vital_{name}` | 7（hr/weight/length/amniotic/movement/bp/oxygen） | `kind: vital`, `unit`, `track`, `continuant_id` |

### 2.4 神经与行为层（neural_behavior）

| 节点类型 | id 构造 | 数量 | 关键 metadata |
|---------|---------|------|--------------|
| Reflex | `reflex_{name}` | 2（moro/sucking） | `emerges_stage`, `continuant_id` |
| Temperament | `temperament` | 1 | `defined_stage`, `dimension`, `score` |

### 2.5 命运与叙事层（fate_birth）

| 节点类型 | id 构造 | 数量 | 关键 metadata |
|---------|---------|------|--------------|
| Event | `event_{type}_s{stage}`（事件独立身份） | 按实际掷骰数 | `stage_index`, `event_type`, `result`, `probability` |
| Defect | `defect_{type}` | 按实际缺陷数 | `severity: minor/moderate/major`, `continuant_id` |
| Narrative | `narr_s{stage}` | 0-7 | `stage_index`, `length_chars` |

**注意**：brain 节点视觉上可归入 `neural_behavior` 组以符合生物学直觉（样本 v2 已这样做），也可保留在 `embodiment`。**按 group 字段配色即可，分组属于前端渲染关注点，不影响本体论**。

## 3. 边类型清单

### 3.1 结构性边（无 stage_index 或单次发生）

| 边类型 | source → target | uuid 构造 | 多重？ |
|--------|----------------|----------|-------|
| `EXPRESSES_AS` | Species → Baby | `species->baby:EXPRESSES_AS` | 否 |
| `INHERITS_FROM` | Parent → Baby | `{genome_side}->baby:INHERITS_FROM` | 否 |
| `CONTRIBUTES_TO` | Parent → Methylation | `{side}->methylation:CONTRIBUTES_TO` | 否 |
| `EPIGENETIC_OF` | Methylation → Baby | `methylation->baby:EPIGENETIC_OF` | 否 |
| `BORN_AT` | Birthplace → Baby | `{bp}->baby:BORN_AT` | 否 |
| `OBSERVES` | Vital → Organ | `{vital}->{organ}:OBSERVES` | 否 |

### 3.2 因果关系边（带 stage_index，多重边的主战场）

| 边类型 | source → target | 典型 metadata | 多重？ |
|--------|----------------|--------------|-------|
| `MODULATES` | Hormone → Organ | `weight`, `level_at`, `polarity`, `description` | **是**（跨阶段） |
| `FEEDS` | Nutrient → Organ/Hormone | `weight`, `level_at`, `description` | **是** |
| `DAMAGES` | Teratogen → Organ | `weight`, `description` | **是** |
| `CAUSES` | Teratogen → Hormone（如 stress→cortisol） | `weight`, `description` | **是** |
| `AFFECTS` | Hormone → Baby | `level`, `description` | **是** |

### 3.3 胚胎承担边（以 baby 为中心的时序事件）

| 边类型 | source → target | 典型 metadata | 多重？ |
|--------|----------------|--------------|-------|
| `EXPOSED` | Teratogen → Baby | `stage_index`, `exposure`, `description` | **是** |
| `INTAKE` | Nutrient → Baby | `stage_index`, `level`, `status` | **是** |
| `MEASURED` | Vital → Baby | `stage_index`, `v`, `unit` | **是** |
| `DEVELOPS` | Baby → Organ | `stage_index`, `phase: 'FORMS'\|'MATURES'`, `weight` | **是**（FORMS + MATURES 天然 2 条） |
| `ACQUIRES` | Baby → Reflex | `stage_index` | 否（每反射一次） |
| `CRYSTALLIZES` | Baby → Temperament | `stage_index` | 否 |

### 3.4 事件归因边（因果链）

| 边类型 | source → target | 典型 metadata | 多重？ |
|--------|----------------|--------------|-------|
| `CAUSED_BY` | Nutrient/Teratogen/Hormone → Event | `weight`, `stage_index`, `description` | 是（多源汇聚） |
| `RESULTS_IN` | Event → Defect | `weight` | 否 |
| `AFFECTS` | Defect → Baby | `weight` | 否 |
| `EMERGES_IN` | Reflex → Organ | `stage_index`, `description` | 否 |
| `DESCRIBES` | Narrative → Baby | `stage_index` | 否 |
| `TerminatedBy` | Event → Baby | `stage_index`, `cause: miscarriage/stillbirth` | 否（流产/死产专用） |

## 4. uuid 构造规则（UUIDv5 content-hash，无语义泄漏）

```python
import uuid as _uuid

_UUID_NAMESPACE = _uuid.UUID("6ba7b810-9dad-11d1-80b4-00c04fd430c8")  # RFC4122 DNS ns

def make_edge_uuid(source: str, target: str, etype: str,
                   stage_index: int | None = None,
                   description: str = "") -> str:
    payload = f"E|{source}|{target}|{etype}|{stage_index or ''}|{description}"
    return str(_uuid.uuid5(_UUID_NAMESPACE, payload))
    # → "fd20993f-2668-5f49-a758-bb114df8e7a2"

def make_node_uuid(raw_id: str) -> str:
    """节点同样使用 UUIDv5, raw 可读 id 只保留在 metadata.raw_id 做调试反查"""
    return str(_uuid.uuid5(_UUID_NAMESPACE, f"N|{raw_id}"))
    # → "6fb6e424-8968-5d41-9729-c2a35b656209"
```

**核心原则**（content-hash 纯技术标识）：
- **uuid 是纯技术标识，不承载任何语义**。不出现 `:s2`、`MODULATES` 等人类可读后缀。
- **语义信息全部在独立字段**：`type` 是关系动词，`stage_index` 是时间坐标，`description` 是具体事实。
- **确定性 hash**：相同 (source, target, type, stage_index, description) 生成相同 uuid，SSE 多次 emit 同一条边天然幂等。
- **多重边的唯一性靠 `stage_index` 和/或 `description` 进入 hash 载荷**实现，而非暴露在 uuid 字面。

### 为什么不用随机 UUID？

随机 UUID 也能工作，但要求后端维护"会话 → 边 uuid 注册表"来保证同一条边重复 emit 不产生两条。content-hash 让前后端都**无状态**即可幂等，实现最简。

### 为什么不用递增编号（`e001` / `e002`）？

递增编号需要全局计数器，并发 emit / 多 fetus 场景复杂度上升。content-hash 天然可并行。

### 边字段示例

```json
{
  "uuid":        "fd20993f-2668-5f49-a758-bb114df8e7a2",
  "source":      "a0e8497d-5854-5ecd-b5d6-01f7def5be53",
  "target":      "c140ba079e-...-...-...-...",
  "type":        "MODULATES",
  "stage_index": 2,
  "weight":      0.40,
  "level_at":    1.3,
  "polarity":    "negative",
  "description": "皮质醇轻度抑制心肌分化"
}
```

节点 / 边 id 人类不可读（这是刻意的），打开 JSON 立即看到的语义来自 type + stage_index + description。raw 可读 id（如 `hormone_cortisol`）保留在**节点的 `metadata.raw_id`** 字段供调试反查。

## 5. GraphDelta 合并语义

```typescript
type GraphDelta = {
  add_nodes?: Node[]
  add_edges?: Edge[]
  update_nodes?: Partial<Node>[]       // 必须带 id
  update_edges?: Partial<Edge>[]       // 必须带 uuid
  remove_nodes?: string[]              // 按 id
  remove_edges?: string[]              // 按 uuid
}
```

### 合并规则

```js
function mergeGraph(state, delta) {
  const nodes = new Map(state.nodes.map(n => [n.id, n]))
  const edges = new Map(state.edges.map(e => [e.uuid, e]))

  delta.add_nodes?.forEach(n => nodes.set(n.id, n))          // 如 id 已存在直接覆盖（add 幂等）
  delta.add_edges?.forEach(e => edges.set(e.uuid, e))

  delta.update_nodes?.forEach(patch => {
    const cur = nodes.get(patch.id)
    if (!cur) return                                          // update 不创建新节点（保守）
    nodes.set(patch.id, {
      ...cur,
      ...patch,
      metadata: { ...(cur.metadata || {}), ...(patch.metadata || {}) }  // metadata 深合并
    })
  })
  delta.update_edges?.forEach(patch => {
    const cur = edges.get(patch.uuid)
    if (!cur) return
    edges.set(patch.uuid, { ...cur, ...patch })
  })

  delta.remove_nodes?.forEach(id => {
    nodes.delete(id)
    // 级联：同时移除所有以该节点为端点的边
    for (const [u, e] of edges) {
      if (e.source === id || e.target === id) edges.delete(u)
    }
  })
  delta.remove_edges?.forEach(u => edges.delete(u))

  return { nodes: [...nodes.values()], edges: [...edges.values()] }
}
```

### `merge_deltas` 后端聚合（多个 delta → 一个大 delta）

```python
def merge_deltas(*deltas: dict) -> dict:
    out = {"add_nodes": [], "add_edges": [],
           "update_nodes": [], "update_edges": [],
           "remove_nodes": [], "remove_edges": []}
    for d in deltas:
        for k in out:
            out[k].extend(d.get(k, []))
    # 去掉空列表保持事件轻量
    return {k: v for k, v in out.items() if v}
```

## 6. 业务函数 emit 示例

### 6.1 激素计算（每阶段）

```python
def compute_hormones(env: dict, stage_index: int, baby_id: str) -> dict:
    cortisol_level = _calc_cortisol(env)
    thyroid_level = _calc_thyroid(env)
    sex_level = _calc_sex_hormone(env, stage_index)
    hcg_level = _calc_hcg(env, stage_index)

    effects = _get_hormone_effects(cortisol_level, thyroid_level, stage_index)

    nodes = []
    if stage_index == 1:  # 首次出现，只创建一次
        nodes = [
            node_hormone("cortisol"),
            node_hormone("thyroid"),
            node_hormone("sex"),
            node_hormone("hcg"),
        ]
    else:
        # 已存在节点，用 update_nodes 追加 track 采样
        pass

    edges = []
    # cortisol → heart 调控
    if effects.get("heart_impact", 0) > 0.05:
        edges.append(edge_modulates(
            hormone="cortisol", organ="heart", stage_index=stage_index,
            weight=effects["heart_impact"], level_at=cortisol_level,
            description=effects.get("heart_desc", ""),
        ))
    # cortisol → brain
    if effects.get("brain_impact", 0) > 0.05:
        edges.append(edge_modulates(
            hormone="cortisol", organ="brain", stage_index=stage_index,
            weight=effects["brain_impact"], level_at=cortisol_level,
            description=effects.get("brain_desc", ""),
        ))
    # thyroid → brain
    # sex → baby DETERMINES (S4)
    # hcg → baby AFFECTS (S1)

    # track 数组通过 update_nodes 追加
    update_nodes = [
        {"id": "hormone_cortisol", "metadata": {
            "track_append": {"stage_index": stage_index, "level": cortisol_level}
        }}
        # ... 其他激素同理
    ]

    delta = merge_deltas(
        delta_add(nodes=nodes, edges=edges),
        delta_update(nodes=update_nodes),
    )
    return {
        "cortisol": cortisol_level,
        "thyroid": thyroid_level,
        "sex": sex_level,
        "hcg": hcg_level,
        "effects": effects,
        "graph_delta": delta,
    }
```

**`track_append` 特殊处理**：前端 mergeGraph 识别 metadata 里的 `track_append` 字段，把其加到 `metadata.track` 数组末尾，实现"时间序列连续增长"。

### 6.2 命运掷骰

```python
def roll_congenital_defects(env, nutrient_risk, teratogen_risk, stage_index, baby_id) -> dict:
    base_prob = 0.03
    modified = base_prob * env["defect_risk_modifier"]
    got_defect = random.random() < modified

    event_id = f"event_defect_roll_s{stage_index}"
    nodes = [node_event(
        event_type="defect_roll", stage_index=stage_index,
        result="heart_murmur" if got_defect else "pass",
        probability=modified,
    )]
    edges = []

    if got_defect:
        defect_id = "defect_heart_murmur"
        nodes.append(node_defect("heart_murmur", severity="minor"))
        edges.append(edge_results_in(event_id, defect_id))
        edges.append(edge_affects(defect_id, baby_id, weight=0.3))

        # 归因链：寻找当前低水平营养 / 高水平毒素作为 cause
        if nutrient_risk.get("folate", 0) > 0.5:
            edges.append(edge_caused_by(
                cause="nutrient_folate", event=event_id,
                stage_index=1, weight=0.5, description="叶酸不足",
            ))
        if teratogen_risk.get("alcohol", 0) > 0.1:
            edges.append(edge_caused_by(
                cause="teratogen_alcohol", event=event_id,
                stage_index=stage_index, weight=0.4, description="酒精暴露",
            ))

    return {
        "defect": defect_id if got_defect else None,
        "graph_delta": delta_add(nodes=nodes, edges=edges),
    }
```

### 6.3 流产

```python
def roll_miscarriage(env, stage_index, baby_id) -> dict:
    prob = _miscarriage_prob(env, stage_index)
    triggered = random.random() < prob

    if not triggered:
        return {"miscarried": False, "graph_delta": {}}

    event_id = f"event_miscarriage_s{stage_index}"
    # 流产：删除未来阶段相关边（若已预 emit），更新 baby 状态
    delta = merge_deltas(
        delta_add(
            nodes=[node_event("miscarriage", stage_index, result="triggered")],
            edges=[edge_terminated_by(event_id, baby_id, stage_index, cause="miscarriage")],
        ),
        delta_update(nodes=[
            {"id": baby_id, "metadata": {"status": "miscarried", "terminated_at_stage": stage_index}}
        ]),
    )
    return {"miscarried": True, "graph_delta": delta}
```

## 7. 前端渲染架构

### 7.1 组件结构（无变动）

```
Cradle.jsx  (或 conceive 会话详情页)
  └─ useWombGraph(sessionId) → {nodes, edges}
  └─ <LifeGraph nodes={nodes} edges={edges} onNodeClick={...} />
        └─ 现有 adaptNodes / adaptEdges / buildSimEdges / renderGraph
```

### 7.2 LifeGraph.jsx 的最小修改

**唯一修改点**：`adaptEdges` 的 uuid 构造规则：

```js
// 之前
uuid: `${e.source}->${e.target}:${e.type}`

// 之后
function makeEdgeUuid(e) {
  const base = `${e.source}->${e.target}:${e.type}`
  return e.stage_index != null ? `${base}:s${e.stage_index}` : base
}
// ... uuid: makeEdgeUuid(e)
```

`buildSimEdges` 现有的 `edgePairCount` / 曲率分散逻辑**完全不动**——它本来就是按 `source + target` 对计数，按 uuid 唯一分散曲率。只要 uuid 不碰撞，多重边视觉自动出来。

### 7.3 useWombGraph.js 伪代码

```js
export function useWombGraph(sessionId) {
  const [state, setState] = useState({ nodes: [], edges: [] })

  useEffect(() => {
    if (!sessionId) return
    const es = new EventSource(`/api/conceive/${sessionId}/stream`)
    const onMessage = (raw) => {
      try {
        const data = JSON.parse(raw.data)
        if (data.graph_delta) {
          setState(prev => mergeGraph(prev, data.graph_delta))
        }
      } catch (e) { /* silent skip */ }
    }
    es.addEventListener('message', onMessage)
    es.addEventListener('stage_in_progress', onMessage)
    es.addEventListener('conception_complete', onMessage)
    return () => es.close()
  }, [sessionId])

  return state
}
```

## 8. 关键风险与应对

### 8.1 多胎（双胞胎 / 三胎）

`node_baby` 支持 `baby_f1` / `baby_f2` 等 id。所有业务函数 emit 时需要按当前胚胎 id 路由边的 target。**本期先做单胎**，多胎场景下的 `baby_id` 参数在 emit 函数签名上预留，但路由逻辑下期实现。

### 8.2 流产后图的一致性

流产触发时：
- 立刻 `update` baby 节点 status
- emit 终止事件 + `TerminatedBy` 边
- `stages.py` 的 `express_stream` 检测到流产后**提前退出循环**，不再调用后续阶段的 `compute_*`，自然不会 emit 未来阶段的 delta
- 前端看到：图停止生长，baby 节点状态标记改变

**不需要 remove_nodes 粗暴删除**——不再 emit 就是最干净的做法。

### 8.3 增量更新的幂等性

- `add_nodes` 对已存在 id 执行覆盖（如首次 emit hormone_cortisol，后续阶段只 update 不 add）
- `merge_deltas` 对多个子系统 delta 做幂等聚合
- SSE 重连时：后端重发全量 delta（若实现），或前端保持已收集状态（不清空）

本期简化：不处理 SSE 重连的图恢复，会话断开就从头再来（一次怀孕 2 分钟，用户可接受）。

### 8.4 LLM 叙事 stream 的 update 粒度

LLM 叙事是流式吐 token 的。首期策略：**等一整段叙事完成后一次 emit narrative 节点**，避免每个 token 都 update（性能 + 视觉闪烁）。未来可优化为"先 emit 占位节点 + 每 200 tokens update 一次 length_chars"。

## 9. 性能预估

| 指标 | 预估 |
|------|------|
| 单次怀孕节点总数 | 30-40 |
| 单次怀孕边总数 | 60-85 |
| 每阶段 delta 大小 | 3-12 nodes + 8-20 edges |
| 前端 D3 simulation 节点数上限 | 1000（本图远低于瓶颈） |
| SSE graph_delta JSON 增量大小 | 1-5 KB / 阶段 |
| 端到端延迟（业务计算 → 前端节点出现） | < 100 ms |

## 10. 本体论对比表（新旧设计）

| 维度 | v1/v2（已废弃） | **本提案 v3** |
|------|----------------|--------------|
| cortisol 节点数 | 3（s2/s4/s6 各一） | **1**（整个怀孕） |
| Stage 节点数 | 7（stage_1..stage_7） | **0**（完全删除） |
| 时间坐标位置 | 节点 id 后缀 | **边的 stage_index 属性** |
| 多重边来源 | 按 stage 拆节点后人工凑 | **同实体跨阶段多次关系的天然结果** |
| 图的中心 | Stage 主干 + Baby 旁支 | **Baby 中心辐射** |
| 图谱与业务的耦合 | 独立 reducer 模块 | **业务函数返回 graph_delta 副产品** |
| 新增字段成本 | 改 reducer + schema + 前端 | **业务函数加 3 行 emit** |
| 与 Zep 模型对齐 | 错位（Zep 也把时间放边上） | **对齐** |

## 11. 命名决策

- 边类型大写 + 下划线（`MODULATES`、`CAUSED_BY`、`BORN_AT`）：与 Neo4j / Cypher 惯例一致，便于未来可能的图数据库接入。
- 节点 id 小写 + 下划线（`hormone_cortisol`、`organ_heart`）：前端 JS 变量友好。
- uuid 使用 UUIDv5（RFC4122 标准格式）：纯技术标识，不承载语义。
- `continuant_id` 字段：实体的跨时间身份标识（用于未来"折叠视图"和跨图打通）。

## 12. 开放问题（本期不解决）

1. **LLM 参与边生成**：在阶段 prompt 里让 LLM 吐 `graph_fragment` 补因果边。下期独立 proposal。
2. **cradle-womb 打通**：受孕完成时把 womb 图与 cradle 图通过 `baby.continuant_id` 串联。下期独立 proposal。
3. **持久化**：会话完成后把最终图序列化到 `archive/AC-*/womb_graph.json`（只读）。可在本期追加，不必单独提案。
4. **时间轴回放滑块**：前端按 `stage_index` 过滤边实现"回放"。下期前端体验优化。
5. **跨怀孕对比视图**：并列渲染多次怀孕图（同父母不同环境）。远期产品功能。
