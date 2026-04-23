# Delta for Womb Graph

## ADDED Requirements

### Requirement: 图谱数据产出方式

后端 SHALL 采用"业务即图"模式产出图谱数据：图谱更新作为业务函数的副产品随 SSE 事件 `graph_delta` 字段流出，不存在独立的图谱生成器模块（如 `graphify.py` / `reducer.py`）。

#### Scenario: 激素计算函数产出图 delta
- GIVEN 子宫编排流程调用 `hormones.compute_hormones(env, stage_index, baby_id)`
- WHEN 函数计算完皮质醇/甲状腺/性激素/hCG 数值
- THEN 返回的字典 MUST 包含 `graph_delta` 字段
- AND `graph_delta` MUST 按本变更定义的 schema 构造
- AND `graph_delta` MUST 通过 `graph_emit.py` 提供的纯函数帮手生成（业务函数不得手写节点/边 dict）

#### Scenario: 编排层聚合多个业务 delta
- GIVEN `stages.express_stream` 在一个阶段内调用了激素/营养/毒素/体征/命运等多个子系统
- WHEN 各子系统各自返回了 `graph_delta`
- THEN 编排层 MUST 使用 `graph_emit.merge_deltas(*deltas)` 把多个 delta 合并为一个大 delta
- AND 最终 SSE 事件中的 `graph_delta` MUST 是合并后的单个 delta 对象

#### Scenario: 业务函数新增字段
- GIVEN 子宫业务增加一种新激素（如 adrenaline）或新营养素（如 vitamin_d）
- WHEN 对应业务函数修改以计算新字段
- THEN 开发者 SHALL 只需在业务函数内调用 `emit_*` 帮手函数产出相关节点/边
- AND 不得修改任何 reducer / schema 注册表 / 前端组件

### Requirement: 实体稳定原则（Continuant Stability）

图中每个 continuant 实体（激素、营养素、毒素、器官、体征、反射、气质、缺陷、胎盘等）在整个怀孕过程中 SHALL 仅表示为单个节点，不得按阶段拆分成多个节点。

#### Scenario: 皮质醇跨阶段采样
- GIVEN 同一次怀孕的 S2、S4、S6 阶段均对皮质醇做了采样
- WHEN 后端产出完整图谱
- THEN 图中 MUST 仅存在一个 id 为 `hormone_cortisol` 的节点
- AND 图中 MUST NOT 存在任何形如 `cortisol_s2`、`cortisol_s4`、`cortisol_s6` 的节点
- AND 三次采样的时间序列数据 SHALL 存储在 `hormone_cortisol.metadata.track` 数组中

#### Scenario: 器官发育从形成到成熟
- GIVEN 心脏在 S2 开始形成、S3 成熟
- WHEN 后端产出完整图谱
- THEN 图中 MUST 仅存在一个 id 为 `organ_heart` 的节点
- AND 该节点 MUST 携带 `metadata.formation_stage = 2` 和 `metadata.maturation_stage = 3`

### Requirement: 时间坐标禁止实体化（No Stage Nodes）

图中 MUST NOT 存在形如 `stage_1`、`stage_2`、`stage_zygote` 等表达"时间段"本身的节点。时间坐标 SHALL 仅作为边的 `stage_index` 属性或节点 metadata 中 `track` 数组元素的字段存在。

#### Scenario: 完整怀孕图谱的节点审查
- GIVEN 一次 human 物种完整怀孕的最终图谱
- WHEN 遍历所有节点
- THEN 不存在任何 id 以 `stage_` 开头的节点
- AND 不存在任何 `group === "stage"` 或 `kind === "stage"` 的节点

#### Scenario: 时间信息的正确承载位置
- GIVEN 皮质醇在 S4 影响了大脑发育
- WHEN 后端产出对应的边
- THEN 该边的 `source` MUST 为 `hormone_cortisol`，`target` MUST 为 `organ_brain`
- AND 该边 MUST 携带 `stage_index: 4` 属性
- AND 该边的 `target` MUST NOT 为任何 stage 类型节点

### Requirement: 多重边自然浮现

同一对节点之间（source 和 target 相同）MAY 存在多条边，每条边代表不同时间或不同语义下的独立关系发生。边的 `uuid` 构造规则 MUST 保证这些多重边不被前端按 key 去重。

#### Scenario: 皮质醇跨三阶段调控心脏
- GIVEN S2、S4、S6 皮质醇分别以 weight=0.4 / 0.6 / 0.3 调控心脏
- WHEN 后端 emit 对应的 MODULATES 边
- THEN 图中 MUST 存在恰好 3 条 `hormone_cortisol → organ_heart MODULATES` 边
- AND 每条边的 `uuid` MUST 唯一（通过在 uuid 中纳入 `stage_index` 实现）
- AND 每条边 MUST 独立携带自己的 `stage_index` / `weight` / `level_at` / `description` 属性

#### Scenario: 前端渲染多重边的视觉分散
- GIVEN 图中存在上述 3 条 MODULATES 多重边
- WHEN 前端 `LifeGraph.jsx` 渲染
- THEN `buildSimEdges` MUST 识别这 3 条边为同一对节点间的 3 条独立边
- AND 自动根据 `edgePairCount` 计算曲率分散
- AND 视觉上呈现为从 cortisol 到 heart 的 3 条曲率不同的曲线

### Requirement: uuid 构造规则（UUIDv5 content-hash，无语义）

所有**节点 id** 和**边 uuid** SHALL 使用 UUIDv5（RFC4122 标准）+ 固定命名空间的 content-hash 方式构造：

```python
import uuid as _uuid
_NS = _uuid.UUID("6ba7b810-9dad-11d1-80b4-00c04fd430c8")

# 边 uuid
uuid = str(_uuid.uuid5(_NS, f"E|{source}|{target}|{type}|{stage_index or ''}|{description}"))

# 节点 uuid (raw 可读 id 只保留在 metadata.raw_id)
id = str(_uuid.uuid5(_NS, f"N|{raw_id}"))
```

节点 id 和边 uuid 都 MUST 仅承担技术标识功能，MUST NOT 包含任何人类可读的语义片段。语义必须通过独立字段（节点 `label` / `continuant_id` / `metadata.raw_id`、边 `type` / `stage_index` / `description`）承载。

#### Scenario: UUID 形式约束
- GIVEN 任意一个节点或边
- WHEN 构造其 id / uuid
- THEN id / uuid MUST 匹配标准 RFC4122 格式正则 `^[0-9a-f]{8}-[0-9a-f]{4}-5[0-9a-f]{3}-[0-9a-f]{4}-[0-9a-f]{12}$`
- AND MUST NOT 包含 `->` / `:` / `MODULATES` / `EXPOSED` / `FEEDS` / `s{N}` / 原始 raw id 等语义片段

#### Scenario: 同内容 uuid 一致性（幂等）
- GIVEN 同一个会话内同一条边 `hormone_cortisol → organ_heart MODULATES (stage_index=2, description="X")` 被 emit 两次
- WHEN 后端两次调用 `make_edge_uuid(...)`
- THEN 两次返回的 uuid MUST 完全相同
- AND 前端 mergeGraph 后图中该边只存在一份

#### Scenario: 多重边 uuid 唯一性
- GIVEN `hormone_cortisol → organ_heart MODULATES` 在 stage_index=2/4/6 有三条边，描述不同
- WHEN 分别构造 uuid
- THEN 三条边的 uuid MUST 两两不同
- AND 前端 `buildSimEdges` 按 uuid 独立识别，自动以曲率分散呈现扇形

#### Scenario: 节点 raw id 保留在 metadata
- GIVEN 一个 `hormone_cortisol` 激素节点被构造
- WHEN 节点进入图谱
- THEN `node.id` MUST 为符合 UUIDv5 格式的标准 UUID 字符串
- AND `node.metadata.raw_id` MUST 等于 `"hormone_cortisol"`（便于后端日志、调试反查）

### Requirement: 节点契约

图中每个节点 MUST 符合以下 schema：

```typescript
{
  id: string            // 全图唯一
  label: string         // 展示名
  group: "identity" | "maternal_stage" | "embodiment" | "neural_behavior" | "fate_birth"
  narrative?: {
    primary?: { zh_CN?: string, en?: string },      // 双语: zh_CN 中文 + en 英文
    scientific?: { zh_CN?: string, en?: string },
  }
  metadata?: {
    kind?: "baby" | "species" | "parent" | "epigenetics" | "birthplace"
         | "hormone" | "nutrient" | "teratogen" | "vital"
         | "event" | "defect" | "narrative" | "reflex" | "temperament" | "organ"
    stage_index?: number
    track?: Array<{ stage_index: number, [key: string]: any }>
    [key: string]: any
  }
  continuant_id?: string
  stage_span?: number[]
}
```

#### Scenario: 节点类型完整性
- GIVEN 后端产出任何节点
- WHEN 节点进入 `graph_delta.add_nodes`
- THEN 节点 MUST 至少包含 `id`、`label`、`group` 三个字段
- AND `group` 字段 MUST 为上述五个枚举值之一

#### Scenario: 激素节点携带 track 数组
- GIVEN 皮质醇在 S1/S2/S4/S6 均有采样
- WHEN 首次 emit 或后续 update
- THEN `hormone_cortisol.metadata.track` MUST 按阶段顺序累积采样数据
- AND 每个 track 元素 MUST 包含 `stage_index` 和对应的数值字段（如 `level`）

### Requirement: 边契约

图中每条边 MUST 符合以下 schema：

```typescript
{
  uuid: string          // 按规则构造，全图唯一
  source: string        // 必须是图中存在或即将出现的节点 id
  target: string
  type: string          // 大写下划线命名（如 MODULATES / CAUSED_BY）
  weight?: number       // 0.0 ~ 1.0，影响视觉粗细
  stage_index?: number  // 发生时的阶段，多重边必须携带
  description?: string  // 那一刻的具体语义
  [key: string]: any
}
```

#### Scenario: 边类型白名单
- GIVEN 后端产出任何边
- WHEN 边进入 `graph_delta.add_edges`
- THEN 边的 `type` MUST 属于本变更定义的有效边类型集合：
  `EXPRESSES_AS | INHERITS_FROM | CONTRIBUTES_TO | EPIGENETIC_OF | BORN_AT`（结构性）
  `MODULATES | FEEDS | DAMAGES | CAUSES | AFFECTS | DETERMINES`（因果调控）
  `EXPOSED | INTAKE | MEASURED | DEVELOPS | ACQUIRES | CRYSTALLIZES`（胚胎承担）
  `OBSERVES`（体征观测）
  `CAUSED_BY | RESULTS_IN | EMERGES_IN | DESCRIBES | TerminatedBy`（归因叙事）

### Requirement: GraphDelta 四种原子操作

`graph_delta` 对象 MUST 支持六个可选字段，代表四种原子操作：

```typescript
{
  add_nodes?: Node[]
  add_edges?: Edge[]
  update_nodes?: Partial<Node>[]     // 必须带 id
  update_edges?: Partial<Edge>[]     // 必须带 uuid
  remove_nodes?: string[]            // 按 id 移除
  remove_edges?: string[]            // 按 uuid 移除
}
```

#### Scenario: add 的幂等性
- GIVEN 同一次怀孕中多次 emit 同一个 `hormone_cortisol` 节点
- WHEN 前端执行 `mergeGraph`
- THEN 图中该节点数量保持为 1（后 add 覆盖先 add）
- AND 不产生重复节点

#### Scenario: update_nodes 的 metadata 深合并
- GIVEN 首次 emit `hormone_cortisol` 时 metadata = { baseline: 1.0 }
- WHEN 后续 update_nodes emit { id: "hormone_cortisol", metadata: { track: [...] } }
- THEN 合并后节点 metadata MUST 同时包含 `baseline: 1.0` 和 `track: [...]`
- AND 非 metadata 字段采用浅合并（后写覆盖）

#### Scenario: remove_nodes 级联删边
- GIVEN 图中存在节点 X 以及若干以 X 为端点的边
- WHEN `graph_delta.remove_nodes = ["X"]` 被合并
- THEN 节点 X 被移除
- AND 所有以 X 为 source 或 target 的边同步被移除

### Requirement: 前端实时增量渲染

前端 SHALL 通过 `useWombGraph(sessionId)` hook 订阅 SSE 流，对每个含 `graph_delta` 的事件执行 `mergeGraph` 操作，将结果传给 `LifeGraph.jsx` 渲染。

#### Scenario: SSE 事件到达时图的生长
- GIVEN 一次怀孕正在进行
- WHEN 后端发出 `stage_in_progress` 事件携带 `graph_delta`（含 2 节点 + 5 边）
- THEN 前端 MUST 在 100ms 内完成 mergeGraph 和 rerender
- AND 用户 MUST 在视觉上看到对应的新节点和边出现
- AND 已有节点的位置、样式、选中状态 MUST 保持稳定（不全图重排）

#### Scenario: 缺失 graph_delta 字段的容错
- GIVEN 后端发出一个 SSE 事件但未包含 `graph_delta` 字段（旧客户端兼容或错误格式）
- WHEN `useWombGraph` 处理该事件
- THEN 前端 MUST 不 crash，静默跳过此事件
- AND 已渲染的图保持不变

### Requirement: LifeGraph.jsx 最小侵入

`frontend/src/components/LifeGraph.jsx` 的核心渲染逻辑（`buildSimEdges` / `getLinkPath` / `getLinkMidpoint` / `renderGraph`）MUST 保持不变。本变更对该组件的唯一修改 SHALL 是 `adaptEdges` 中 uuid 获取策略的调整：**优先使用后端提供的 `e.uuid`，缺失时 fallback 到原 `${source}->${target}:${type}` 自构造规则**。

#### Scenario: adaptEdges 优先使用后端 uuid
- GIVEN 一条输入边带有 `uuid: "e_abc1234567"` 字段（后端产出的 content-hash）
- WHEN `adaptEdges` 处理该边
- THEN 生成的内部 `uuid` MUST 原样等于 `"e_abc1234567"`
- AND MUST NOT 对该 uuid 做任何再加工

#### Scenario: 无 uuid 字段时向后兼容
- GIVEN 一条输入边不含 `uuid` 字段（旧数据或手写 fixture）
- WHEN `adaptEdges` 处理该边
- THEN 生成的 `uuid` MUST 回退到 `${source}->${target}:${type}`（原规则）
- AND 旧数据渲染行为不变

#### Scenario: 多重边曲率分散不变
- GIVEN 图中存在 3 条 `hormone_cortisol → organ_heart` 的多重边（各自带不同的 content-hash uuid）
- WHEN `LifeGraph.jsx` 渲染
- THEN 现有 `buildSimEdges` 的 `edgePairCount` 逻辑 MUST 自动识别并分散曲率
- AND 组件内 D3 force simulation 不受影响

### Requirement: 流产与异常终止

当业务触发流产、死产、早期终止等异常路径时，图谱 SHALL 通过 update + 终止事件边正确表达，而非粗暴删除已有节点。

#### Scenario: S3 流产
- GIVEN S3 阶段 `roll_miscarriage` 命中
- WHEN fate.py emit 对应 graph_delta
- THEN delta MUST 包含：
  - `add_nodes`: [event_miscarriage_s3 节点]
  - `add_edges`: [event_miscarriage_s3 → baby_this TerminatedBy 边，stage_index=3]
  - `update_nodes`: [{id: "baby_this", metadata: {status: "miscarried", terminated_at_stage: 3}}]
- AND 编排层 `express_stream` MUST 提前退出循环，不再调用 S4-S7 的业务函数
- AND 图中 MUST NOT 出现 S4 及之后的激素/营养/体征相关节点和边

### Requirement: 图谱按 baby_id 落库

每次孕育完成（含正常出生、流产、发育失败）后端 MUST 把累积的完整图快照保存到 `backend/archive/{baby_id}/womb_graph.json`，便于事后按 baby_id 回看整次孕育过程。

#### Scenario: 正常出生落库
- GIVEN 一次完整 human 孕育跑完 7 阶段
- WHEN `born` 事件触发
- THEN 后端 MUST 把累积图状态写入 `archive/{baby_id}/womb_graph.json`
- AND 文件内容 MUST 包含 `{baby_id, species, sex, born_at, nodes[], edges[], stats}` 字段
- AND `nodes` 长度 ≥ 30，`edges` 长度 ≥ 60

#### Scenario: 流产/发育失败也落库
- GIVEN 一次孕育在 S3 流产
- WHEN SSE 流结束
- THEN 后端仍 MUST 落库 `archive/{baby_id}/womb_graph.json`，标记 `status: "failed"`
- AND 前端事后按 baby_id 可查看"失败的生命树"

### Requirement: 图谱查询 API

后端 MUST 提供 `GET /baby/{baby_id}/womb-graph` 端点，返回已落库的图谱快照。

#### Scenario: 成功查询
- GIVEN 数据库中存在 baby_id 对应的 `womb_graph.json`
- WHEN 客户端 GET `/baby/{baby_id}/womb-graph`
- THEN 响应 MUST 为 200，body 为 `{baby_id, species, sex, born_at, nodes[], edges[], stats}`
- AND 前端可将此快照直接传给 `useWombGraph.loadSnapshot(data)` 还原图

#### Scenario: 查询不存在的 baby_id
- GIVEN 数据库中无对应记录
- WHEN 客户端 GET 该端点
- THEN 响应 MUST 为 404，body 包含错误消息 `Womb graph not found for baby '{id}'`

### Requirement: 节点 narrative 双语支持

节点的 `narrative.primary` 和 `narrative.scientific` 字段 MUST 支持 `zh_CN` + `en` 双语并存。前端 SHALL 按当前 UI 语言渲染对应版本，缺失时 fallback 到另一语言。

#### Scenario: 激素节点双语 narrative
- GIVEN 一个 `hormone_cortisol` 节点
- WHEN 节点被产出
- THEN `node.narrative.primary` MUST 同时包含 `zh_CN` 和 `en` 字段
- AND 英文为 `"Cortisol: stress hormone, affects heart and brain across stages"` 或等价表述

#### Scenario: 前端按语言选择
- GIVEN 用户在英文模式下
- WHEN 点击节点打开详情面板
- THEN Summary 区块 MUST 显示 `narrative.primary.en`
- AND 当英文缺失时自动 fallback 到 `zh_CN`（反之亦然），不出现空 Summary

### Requirement: 成功标准对标

一次完整 human 物种怀孕产出的图谱 SHALL 在规模、结构、多重边丰度上满足下述可量化指标，作为本变更落地完成的判定依据。

#### Scenario: 单次 human 怀孕图的规模
- GIVEN 一次完整 human 物种怀孕（未流产）
- WHEN 整个 SSE 流结束
- THEN 最终图谱节点数 SHALL 在 30-45 区间
- AND 最终图谱边数 SHALL 在 60-85 区间
- AND Baby 节点的入度 + 出度 SHALL 是全图最高（≥ 20）

#### Scenario: 关键多重边 demo
- GIVEN 一次完整 human 怀孕
- WHEN 整个 SSE 流结束
- THEN 图中 MUST 满足：
  - `hormone_cortisol → organ_heart` 多重边数 ≥ 3
  - `hormone_cortisol → organ_brain` 多重边数 ≥ 3
  - `hormone_thyroid → organ_brain` 多重边数 ≥ 2
  - `nutrient_folate → organ_brain` 多重边数 ≥ 2
