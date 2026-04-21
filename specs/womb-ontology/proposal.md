# 子宫图谱本体论对称方案（Draft v0.1）

> 状态：**待多方评审**
> 作者：lifulin + Claude
> 日期：2026-04-17
> 对应已落地：`specs/cradle-dev-ontology/review-synthesis.md`

## 一、背景与问题

### 1.1 现状（实测 `AC-20260417-34518`）

| 指标 | 数值 | 摇篮对比（迁移后） |
|------|------|-------------------|
| 节点数 | 61 | 98 |
| 边数 | 105 | 247 |
| 连通分量 | **5** | 1 |
| 孤立单点 | **4** | 0 |
| SCHEMA_VERSION | 2 | 2 |
| 校验器 | **无** | `cradle/validate.py` |
| 本体论文件 | **无** | `cradle/ontology.py` |
| 迁移脚本 | **无** | `scripts/migrate_cradle_graph_v1_to_v2.py` |

### 1.2 关键差异：子宫 ≠ 摇篮

**摇篮**：多维并列（motor / language / cognitive …）× 时间阶段 → 摇篮引入 `Dimension` 轴 + `Phase` 时间桶 + 两条归属边（BELONGS_TO / OCCURS_IN）。

**子宫**：六层生物学因果链（基因 → 表观 → 通路 → 细胞 → 器官 → 功能 → 性状）→ **本身就是垂直 hierarchy**，没有"并列维度"的概念。**不能把摇篮的 Dimension/Phase 强套过来。**

### 1.3 具体问题

- **4 个孤立节点**：`epigenetic:BDNF:methylation`、`epigenetic:IGF2_H19:methylation`、`epigenetic:NR3C1:methylation`、`maternal_fn:physical_adaptation`——它们本应 triggers 下游 pathway / organ，但下游节点未被创建或边未生成
- **L4 cell_type 层缺失**：实测图谱里一个 cell_type 节点都没有，直接从 L3 pathway 跳到 L5 organ
- **跨层边稀疏**：`signal_transduction` 只有 5 条，`triggers` 里真正跨层的不到一半
- **边语义混乱**：现有 `bridge` 边 1 条、`environmental_impact` 14 条，但没有一条显式的"层级归属"声明——层级靠 `node.layer` 字段间接推断

## 二、现有资产（复用原则）

### 2.1 层级常量已定（`backend/constants/womb_constants.py`）

```python
WOMB_LAYER_MAP = {
    "gene": 1, "origin": 1,
    "epigenetic": 2,
    "pathway": 3,
    "cell_type": 4,
    "organ": 5, "milestone": 5,
    "function": 6, "trait": 6,
    # 横切（layer=0）：environment, maternal_fn, placenta, event, attribute, bridge
}
```

### 2.2 现有边类型（6 种，对应真实生物学语义）

| 边类型 | 层级方向 | 语义 | 现有用量 |
|--------|---------|------|----------|
| `genetic_expression` | L1 → L3 | 基因 → 通路 | 33 |
| `triggers` | L2 → L3 或 L1 → L2 | 表观调控 → 下游 | 45 |
| `signal_transduction` | L3 → L5 | 通路激活 → 器官 | 5 |
| `crosstalk` | L3 ↔ L3 | 通路间横向 | 7 |
| `environmental_impact` | env → anything | 环境输入 | 14 |
| `bridge` | womb → cradle | 阶段桥接 | 1 |

**关键判断**：现有边类型**已经覆盖全部子宫因果语义**，对齐分子生物学教科书（基因表达 / 信号传导 / 互作网络）。**不要引入 `BELONGS_TO`、`OCCURS_IN` 等抽象边**——那是摇篮的需求，不是子宫的需求。

## 三、提议本体（Ontology）

### 3.1 层级保持现状

```
L0  横切（environment / maternal_fn / placenta / event / decision）
L1  基因 + 出生身份            gene, origin
L2  表观遗传                    epigenetic
L3  信号通路                    pathway
L4  细胞分化                    cell_type      ← 当前缺失，需补齐
L5  器官 + 里程碑               organ, milestone
L6  功能 + 性状                 function, trait
```

### 3.2 节点字段增强

```jsonc
{
  "node_id": "epigenetic:BDNF:methylation",
  "category": "epigenetic",
  "layer": 2,
  "plasticity": 0.7,
  "plasticity_type": "sustained",
  "parental_origin": "maternal" | "paternal" | null,
  "evidence_sources": [],

  // v3 新增
  "upstream_gene": "BDNF",           // L2 专用：追溯到 L1 源
  "downstream_targets": ["neural_density", "memory_formation"],  // 预期下游
}
```

## 四、META-RULE（一条压顶，与摇篮对称但不同）

摇篮 META-RULE：**非 L0 节点必须有 BELONGS_TO 或 OCCURS_IN 出边**。

子宫 META-RULE：**每个 layer ≥ 2 的节点，必须至少有一条"入边"（edge.target = 自己）来自 layer 严格小于当前层的节点。**

语义：**因果链不断头**——任何节点都能追溯到至少一个更上游的原因。

### 4.1 补充规则

| ID | 规则 | 级别 |
|----|------|------|
| `R-layer-monotone` | `edge.source.layer ≤ edge.target.layer`，逆向跨层只允许 `feedback_loop` 或 `crosstalk` | ERROR |
| `R-cross-layer-dense` | L1→L2 边至少覆盖 90% 的 L2 节点；L2→L3 同理；**防止层级断层** | WARNING |
| `R-dag` | 排除 `crosstalk` / `feedback_loop` 后，主干是 DAG | ERROR |
| `R-cover` | 任一 `origin` 节点连通分量 ≥ 90% | WARNING |
| `R-layer-field` | 节点 `layer` 字段必须与 `WOMB_LAYER_MAP[category]` 一致 | ERROR |

### 4.2 约束不同于摇篮的 3 点

1. **子宫不需要 BELONGS_TO 边**：`node.layer` + `WOMB_LAYER_MAP` 已表达归属，再造一条归属边是分形同构的冗余
2. **子宫不需要 OCCURS_IN 边**：子宫**没有阶段节点**（没有 phase 概念），有的是 fetal_stage 但那是时间戳不是节点
3. **子宫允许 L6 → L1 的 feedback_loop**：Thelen 式技能退行在摇篮被禁（R-dag 错误），子宫反馈回路是生物学真相（激素 feedback、epigenetic drift）

## 五、核心修复：孤立节点回填

### 5.1 4 个孤立节点的真实病因

| 孤立节点 | 当前问题 | 应补边 |
|---------|---------|--------|
| `epigenetic:BDNF:methylation` | 无 trigger 下游 | `triggers → pathway:neural_development` + `triggers → function:neural_plasticity` |
| `epigenetic:IGF2_H19:methylation` | 无 trigger 下游 | `triggers → pathway:IGF` + `triggers → organ:placenta_vascular` |
| `epigenetic:NR3C1:methylation` | 无 trigger 下游 | `triggers → pathway:HPA_axis` + `triggers → function:stress_regulation` |
| `maternal_fn:physical_adaptation` | 无下游 | `triggers → placenta:aggregate` + `triggers → organ:maternal_vascular` |

### 5.2 新增常量：`EPIGENETIC_TO_DOWNSTREAM`

```python
# backend/womb/ontology.py
EPIGENETIC_TO_DOWNSTREAM = {
    "BDNF": {
        "pathways": ["neural_development", "synaptic_plasticity"],
        "functions": ["neural_plasticity", "memory_formation"],
    },
    "IGF2_H19": {
        "pathways": ["IGF", "growth_signaling"],
        "organs": ["placenta_vascular"],
    },
    "NR3C1": {
        "pathways": ["HPA_axis", "stress_response"],
        "functions": ["stress_regulation", "cortisol_sensitivity"],
    },
    # … 扩充至所有标准 DOHaD 基因
}

MATERNAL_FN_TO_TARGETS = {
    "physical_adaptation": {"organs": ["maternal_vascular"], "placenta": ["aggregate"]},
    "immune_adaptation": {"organs": ["immune_system"], "placenta": ["aggregate"]},
    "metabolic_adaptation": {"pathways": ["glucose_metabolism"]},
    "endocrine_adaptation": {"pathways": ["HPA_axis"]},
    "neural_adaptation": {"organs": ["brain_maturation"]},
}
```

这两张表是**硬编码的分子生物学常识**，与摇篮的 `CAPABILITY_TO_DIMENSION` 同级——不是方案创新，是落地所需常量。

## 六、迁移路径（MVP 2 天）

### Step 1（0.5 天）· `backend/womb/ontology.py`
- 层级常量 + `EPIGENETIC_TO_DOWNSTREAM` + `MATERNAL_FN_TO_TARGETS`
- 辅助函数：`expected_downstream(node)` / `validate_layer(node)`

### Step 2（0.5 天）· `backend/womb/validate.py`
- `ValidationError` + `validate_graph()`
- 实现 META-RULE + R-layer-monotone + R-dag + R-cover + R-layer-field
- MVP 阶段调用方 `logger.warning` 不 raise（对齐摇篮策略）

### Step 3（0.5 天）· 生成器修补 `causal_graph_store.py`
- `_add_epigenetic_nodes` 在 emit 节点时，查 `EPIGENETIC_TO_DOWNSTREAM` 并预先创建下游 pathway 节点 + triggers 边
- `_add_maternal_system` 同理按 `MATERNAL_FN_TO_TARGETS` 补 triggers
- `_save` 末尾调用 `validate_graph` warn

### Step 4（0.5 天）· 迁移脚本 `migrate_womb_graph_v2_to_v3.py`
- `.v2.bak` 备份
- 遍历现有 epigenetic / maternal_fn 节点，按映射表补齐下游节点 + triggers 边
- SCHEMA_VERSION = 3
- 对 2 个 baby 存档执行并打印连通分量前后对比

### 不做
- 不引入新的前端组件改动（子宫图谱**已经用同一个 `LifeGraph.jsx`** 渲染，schema 不改结构，只补节点/边）
- 不补 L4 cell_type 层（属于下一轮，需要引入新概念）
- 不改 6 种现有边类型的命名/语义（向后兼容铁律）

## 七、开放问题（待评审回答）

1. **L4 cell_type 真的要保留在 schema 里吗？** 如果迁移脚本不补 cell_type 节点，是否违反"六层完整性"？
2. **`EPIGENETIC_TO_DOWNSTREAM` 映射哪里来？** 硬编码表（我的提议）vs LLM 在 conceive.py 里实时生成？硬编码保证确定性但难以扩展新基因
3. **`crosstalk` 是 DAG 破坏者**：R-dag 排除 crosstalk 后主干应该是 DAG，但如果 crosstalk 造成主干"虚假闭环"（两条 pathway 都有 signal_transduction 出边形成闭环）怎么办？
4. **反馈回路 feedback_loop 边**：当前 edge_type 里没有这个类型（只有 is_feedback_loop 字段在 signal_transduction 里），是否需要升格为独立 edge_type？
5. **`attribute` category 归属**：实测有 attribute 节点但 `WOMB_LAYER_MAP` 未定义它，目前 layer=0 横切。保持还是归到 L6？
6. **SCHEMA_VERSION 跳号**：摇篮是 v1→v2，子宫已经 v2 了，本次是 v2→v3 还是停留 v2（只做补数据）？
7. **与摇篮的桥接边**：`bridge` 边当前只 1 条，是否属于这次方案范围？还是留到"跨阶段 ontology"独立方案？

## 八、风险清单

| 风险 | 等级 | 缓解 |
|------|------|------|
| 补齐 L4 cell_type 需要大量生物学常量 | 高 | 本期 defer，后续专项 |
| `EPIGENETIC_TO_DOWNSTREAM` 错漏导致假边 | 中 | 从 OMIM / KEGG 对齐；evidence=`theoretical` 标记 |
| v2 存档迁移不幂等 | 中 | `.v2.bak` 备份 + 迁移前 validate 记录基线 |
| `_add_epigenetic_nodes` 注入 LLM 驱动的 event，补下游可能造成重复 | 中 | 以 `triggers` 边的 (source, target) 二元组去重 |
| 前端 MiroFish 风格已稳定，本次改动不影响前端 | 低 | 只改后端 + 数据 |

## 九、与摇篮方案的对称性验证

| 维度 | 摇篮 v2 | 子宫 v3 | 对称点 |
|------|---------|---------|--------|
| 本体论文件 | `cradle/ontology.py` | `womb/ontology.py` | ✓ 路径对称 |
| 校验器 | `cradle/validate.py` | `womb/validate.py` | ✓ 路径对称 |
| 迁移脚本 | `migrate_cradle_graph_v1_to_v2.py` | `migrate_womb_graph_v2_to_v3.py` | ✓ 命名对称 |
| META-RULE 本质 | 结构归属不断链 | 因果链不断头 | ✓ 都是"不能孤立" |
| 边类型哲学 | 5 种核心 + alias | 6 种领域边 + 不变 | ✗ 故意不对称（子宫不需抽象化） |
| 新 Category | `dimension` | 无新增 | ✗ 故意不对称 |
| 时间轴 | `emerged_at_day` | `fetal_day`（已有） | ✓ 已对齐 |

**核心判断**：子宫方案**不强行对称于摇篮**。生物学因果链本身就是 hierarchy，引入 Dimension/OCCURS_IN 会是过度抽象；摇篮需要这些抽象是因为"能力"在多维度并列展开。尊重领域差异，只复用架构骨架（ontology/validate/migrate 三文件 + META-RULE 形式）。
