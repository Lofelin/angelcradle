# 五维评审汇总 + 子宫本体论最终方案 v1.0

> 日期：2026-04-17
> 输入：proposal.md v0.1
> 评审：数据 / 生物学 / 架构 / 代码 / Linus 对抗

## 一、评审最震撼的 6 个发现

### 🔴 发现 1：原方案的节点 ID 写错
数据评审亲自跑数：`epigenetic:IGF2_H19:methylation` 其实是 **`epigenetic:IGF2_H19:imprinting`**（来自 `_KEY_EPI_CHAINS` 第 2 条 `mod="imprinting"`）。迁移脚本若按原 ID 匹配会直接**跳过该孤立节点**。

### 🔴 发现 2：epigenetic 节点根本不是 LLM 生成的
代码评审追溯到源头：epigenetic 节点由 `backend/womb/epigenetics.py` 的 `METHYLATION_SENSITIVITY` 硬编码 10 个基因 + `_KEY_EPI_CHAINS` 3 条链生成，**完全是 Python 逻辑，零 LLM 调用**。这意味着：
- Linus 的"让 LLM 生成 downstream"建议**站不住脚** —— 节点域完全封闭可穷举
- `EPIGENETIC_TO_DOWNSTREAM` 硬编码是**正确且可维护的**（全空间 13 个 key）

### 🔴 发现 3：SSE 并发写会覆盖迁移脚本
架构评审最硬核：`causal_graph_store._save` 是无锁 `write_text`，conceive SSE 后台线程每帧触发 save。若迁移脚本与活跃 conceive 同时运行在同一 baby，**后写者完全覆盖前者**——conceive 流中途事件全丢。原方案对此**零提及**，必须加 `conception_sessions.active_for(baby_id)` 检查。

### 🔴 发现 4：原方案 43/61 节点会被 R-layer-field 炸成 ERROR
`WOMB_LAYER_MAP` 只覆盖 7 个 category，实测图谱有 **11 个**——`event/attribute/environment/maternal_fn/placenta/bridge` 未定义。加上 `_add_node(..., "trait", ..., layer=1)` 写死（第 402 行）的基因型表征冲突，R-layer-field 会对 **43/61 (70%) 节点直接报 ERROR**——方案宣称"复用现状"名存实亡。

### 🔴 发现 5：R-layer-monotone 违反分子生物学
生物学评审引 Davidson 2006 *The Regulatory Genome*：GRN 中 **L6 → L1 反向边占 30%+**（TP53→BAX 转录反馈、代谢→DNMT/TET 修饰等），把反向边标 ERROR 会生成大量假阳性，**理论上不可辩护**。

### 🔴 发现 6：L4 cell_type 是零用例僵尸层
实测 0 个 cell_type 节点，Linus/数据评审一致要求处置。保留但 defer = 坏品味，违反 YAGNI。

## 二、评审间核心分歧

| 议题 | 数据+代码 | 生物学 | 架构 | Linus | **最终裁决** |
|------|----------|--------|------|-------|--------------|
| 是否新建 ontology.py/validate.py | 保留（复用摇篮~150 行） | 无异议 | 保留（Feature Flag） | 删光（直接嵌 `_save`） | **保留但精简**（ontology ~120 行，validate ~150 行） |
| EPIGENETIC_TO_DOWNSTREAM 数据源 | 硬编码全空间 13 基因 | 补到 DOHaD 经典 17 基因 | — | LLM 生成 | **硬编码**（节点非 LLM 产物，Linus 理据错误） |
| 规则数量 | 5 条 | +时间窗口字段 | — | 1 条足矣 | **3 条**（META-RULE + R-dag + R-cover），砍 R-layer-field / R-layer-monotone / R-cross-layer-dense |
| L4 cell_type | 补齐 defer | 坚决保留（Waddington） | — | 删除或塌缩 | **塌缩到 L5**（与 organ 合并；Waddington 层在子宫模型内暂时不需独立建模） |
| 迁移方式 | 独立脚本 | — | 懒升级 + 锁 | 一次性 notebook，不入库 | **懒升级**（`_load_or_init` 冷启动自修复，有 Feature Flag） |
| SCHEMA_VERSION | v2→v3 | — | 必升 | 不升 | **v2→v3**（新增 downstream_targets 字段属结构变化） |
| METU-RULE 命名 | 沿用 | — | — | 改描述性名 | **`no_orphan_downstream`**（Linus 对） |

## 三、最终方案 v1.0

### 3.1 本体（保持现有六层）

```
L0  横切：environment, maternal_fn, placenta, event, attribute, bridge, decision
L1  gene + origin
L2  epigenetic
L3  pathway
L5  organ + milestone + cell_type（塌缩吸收 L4）
L6  function + trait
```

**关键改动**：L4 cell_type 塌缩到 L5。`WOMB_LAYER_MAP[cell_type] = 5`。生物学评审反对但 YAGNI 赢——零用例的层不配独立存在。未来真有 cell_type 节点涌现时再拆。

### 3.2 节点字段增强（v3）

```jsonc
{
  "node_id": "epigenetic:BDNF:methylation",
  "category": "epigenetic",
  "layer": 2,
  // 新增（可选，缺失时 migration 补）
  "upstream_gene": "BDNF",
  "downstream_targets": ["neural_development", "neural_plasticity"],
  "synthetic": false,  // migration 补的新节点标 true
}
```

### 3.3 边类型（不增不减，保持 6 种）

`triggers / genetic_expression / signal_transduction / crosstalk / environmental_impact / bridge`

**不引入** `feedback_loop` 独立 edge_type（生物学评审希望的）——本期用 `signal_transduction.is_feedback_loop=true` 字段表达（向后兼容铁律）。

## 四、规则（从 5 条 → 3 条）

### META-RULE（改名 `no_orphan_downstream`）
**每个 layer ≥ 2 的节点，必须至少有一条入边来自 layer 严格小于当前层的节点。**

### R-dag
排除 `crosstalk` 以及 `signal_transduction.is_feedback_loop=true` 的边后，主干无环。

### R-cover
任一 `origin` 节点的连通分量 ≥ 90%（WARNING）。

### 砍掉的 3 条（附理由）

- ❌ `R-layer-field`：Linus 正确——denormalization 反模式，应改为读取时 `layer(node) = WOMB_LAYER_MAP[node.category]` 函数动态算
- ❌ `R-layer-monotone`：生物学评审正确——违反 TF 反馈/代谢→表观的真实拓扑
- ❌ `R-cross-layer-dense`：数据评审正确——基线 0% 直接达不到 90%，WARNING 会变常驻噪音

## 五、修复孤立节点（核心价值）

### 5.1 `EPIGENETIC_TO_DOWNSTREAM` 扩到全空间 10 基因

```python
# backend/womb/ontology.py
EPIGENETIC_TO_DOWNSTREAM = {
    # 原方案 3 条（IGF2_H19 键名修正）
    "BDNF":             {"pathways": ["neural_development"], "functions": ["neural_plasticity", "memory_formation"]},
    "IGF2_H19":         {"pathways": ["IGF"], "organs": ["placenta_vascular"]},  # ← 注意 imprinting
    "NR3C1":            {"pathways": ["HPA_axis"], "functions": ["stress_regulation"]},
    # 数据评审发现的 METHYLATION_SENSITIVITY 其余 7 基因
    "metabolism_type":  {"pathways": ["glucose_metabolism"], "organs": ["liver_metabolism"]},
    "freckles":         {"pathways": ["MC1R"], "traits": ["pigmentation"]},
    "height_tendency":  {"pathways": ["IGF"], "organs": ["skeletal_growth"]},
    "hair_color":       {"pathways": ["MC1R"]},
    "hair_type":        {"pathways": ["FGF5"]},
    "eye_color":        {"pathways": ["OCA2"]},
    "skin_tone":        {"pathways": ["MC1R", "TYR"]},
}
```

### 5.2 `MATERNAL_FN_TO_TARGETS`（对齐 Steer 2017 六大系统）

```python
MATERNAL_FN_TO_TARGETS = {
    "cardiovascular_adaptation": {"organs": ["maternal_vascular"], "placenta": ["aggregate"]},
    "hematologic_adaptation":    {"organs": ["blood_volume"]},
    "renal_adaptation":          {"organs": ["renal_function"]},
    "respiratory_adaptation":    {"organs": ["respiratory_capacity"]},
    "immune_adaptation":         {"organs": ["immune_system"], "placenta": ["aggregate"]},
    "endocrine_adaptation":      {"pathways": ["HPA_axis"]},
    # legacy alias (向后兼容原 physical_adaptation)
    "physical_adaptation":       {"organs": ["maternal_vascular"], "placenta": ["aggregate"]},
    "neural_adaptation":         {"organs": ["brain_maturation"]},
    "metabolic_adaptation":      {"pathways": ["glucose_metabolism"]},
}
```

### 5.3 新节点 `synthetic` 标记

migration 创建的下游节点（比如 `pathway:neural_development`）缺省：
```python
{
  "plasticity": 0.6,
  "plasticity_type": "sustained",
  "evidence_sources": ["migration_inferred"],
  "synthetic": True,     # 审计痕迹
}
```

## 六、执行路径（MVP 2.5 天，已压缩）

### Step 1（0.5 天）· `backend/womb/ontology.py`（~120 行）
- 两张映射表（EPIGENETIC_TO_DOWNSTREAM / MATERNAL_FN_TO_TARGETS）
- 辅助函数 `expected_downstream(node)` / `infer_layer(node)`
- **复用** 摇篮 `ontology.py` 的 `infer_*` 风格

### Step 2（0.5 天）· `backend/womb/validate.py`（~150 行）
- `ValidationError` + `validate_graph()`（**直接 copy 摇篮 `validate.py` 的 `_has_cycle` / `format_errors` / `summarize`**）
- 3 条规则实现

### Step 3（0.5 天）· `causal_graph_store.py` 修补（~60 行）
- 加 `from config import WOMB_ONTOLOGY_V3` Feature Flag
- `_add_epigenetic_nodes` / `_add_maternal_system` 内 flag 判分支：
  - flag on → 查表补下游节点 + triggers 边
  - flag off → 保持 v2 行为
- `_save` **只在终态帧**（event='complete' 或 'born'）调用 validate，中间帧 skip（性能关键）
- 边 id 统一带后缀：`f"{src}->{tgt}:triggers"`（幂等性修复）

### Step 4（0.5 天）· 懒升级（替代独立迁移脚本）
- `_load_or_init` 读到 `schema_version < 3` 时：
  - `fcntl.flock` 文件锁（架构评审要求）
  - 创建 `.v2.bak` 备份
  - 调用 `repair_graph(graph)` 内联函数执行回填
  - 写入 `schema_version=3`
- 首帧请求触发一次性自动迁移，**无需手动跑脚本**
- **不新建** `scripts/migrate_womb_graph_v2_to_v3.py`——Linus 在这点对了

### Step 5（0.5 天）· 测试 + 实测 baseline
- 12 条测试用例（代码评审的 15 条砍掉 R-layer-field/R-cross-layer-dense 相关 3 条）
- 对 `AC-20260417-34518` 做前后对比，预期：5 分量→1、4 孤立→0

## 七、Feature Flag 强制要求

`config.py`：
```python
WOMB_ONTOLOGY_V3 = os.getenv("WOMB_ONTOLOGY_V3", "0") == "1"
```

所有新代码路径（下游补边、validate、自迁移）都包进 flag。**默认 off，上线灰度开启**。一键回滚 = `unset WOMB_ONTOLOGY_V3`。

## 八、与原方案 v0.1 的关键差异

| 项 | 原 v0.1 | 最终 v1.0 | 理由 |
|----|---------|-----------|------|
| 新建文件数 | 3（ontology+validate+migrate 脚本） | **2**（删 migrate 脚本） | 懒升级替代 |
| 规则数 | 5 条 | **3 条** | 删 R-layer-field / R-layer-monotone / R-cross-layer-dense |
| IGF2_H19 节点 ID | `:methylation` | **`:imprinting`** | 数据评审修正事实错误 |
| EPIGENETIC 映射表 | 3 基因 | **10 基因**（全空间穷举） | 代码评审：METHYLATION_SENSITIVITY 闭域 |
| MATERNAL_FN 映射 | 5 条（physical…） | **8 条**（对齐 Steer 2017 + legacy alias） | 生物学评审 |
| L4 cell_type | 保留 defer | **塌缩到 L5** | Linus + YAGNI |
| Feature Flag | 未提 | **强制** `WOMB_ONTOLOGY_V3` | 架构评审 |
| 并发锁 | 未提 | **`fcntl.flock` + active session 检测** | 架构评审 |
| validate 调用点 | 每帧 | **只终态** | 架构性能评审 |
| 边 id 格式 | `{src}->{tgt}` | **`{src}->{tgt}:triggers`** | 代码评审幂等性 |
| 工时 | 2 天 | **2.5 天**（加锁+flag+修正） | — |

## 九、开放问题交付状态

| Q | 最终答复 |
|---|----------|
| Q1 L4 cell_type | **塌缩 L5**（YAGNI，零用例） |
| Q2 EPIGENETIC 映射来源 | **硬编码 10 基因**（METHYLATION_SENSITIVITY 闭域） |
| Q3 crosstalk DAG 闭环 | **crosstalk 完全豁免** R-dag（生物学事实） |
| Q4 feedback_loop edge_type | **不新增**（保留字段方式，向后兼容） |
| Q5 attribute category | **归 L0 横切**，WOMB_LAYER_MAP 显式补 |
| Q6 SCHEMA_VERSION | **v2→v3**（新增 downstream_targets 字段） |
| Q7 bridge 跨阶段 | **defer 独立方案**（§9 对称表标 ✗） |

## 十、本期不做（明确 defer）

- 补齐 L4 cell_type 层（需要 Cell Ontology 引入）
- omics 层字段（transcriptome/proteome/metabolome）
- 关键窗口 `expression_window_days`（需要 Carnegie stage 对齐工作量大）
- `feedback_loop` 独立 edge_type
- GxE moderation 边
- 跨阶段 bridge 本体（需要和摇篮桥接）

所有 defer 项都在 `specs/womb-ontology/future.md` 归档追踪（本方案落地后创建）。
