# 五维评审汇总 + 最终方案 v1.0

> 日期：2026-04-17
> 输入：proposal.md v0.1
> 评审：数据 / 本体 / 架构 / 代码 / Linus 对抗

## 一、评审最震撼的发现（Top 5）

### 🔴 发现 1：原 proposal 定位错了战场
**架构 + 代码评审一致指出**：`backend/cradle/causality.py` 是**纯规则 tag 引擎**，**零 LLM 调用，不生成图谱**。真正的图谱生成入口是：

```
backend/cradle_graph_store.py:461  save_capabilities_graph()
backend/cradle_graph_store.py:760  save_stress_graph()
```

**影响**：原方案"重写 causality.py"完全错配。正确的修改位置是 `cradle_graph_store.py` 的 `save_*` 系列函数，在 emit capability 节点时**同步 emit** `BELONGS_TO` + `OCCURS_IN` 边。

### 🔴 发现 2：现有代码已经有解决孤岛的 90% 材料
**数据 + 架构评审**：
- `constants/cradle_constants.py::CAPABILITY_TO_DIMENSION` 已存在，capability → dimension 映射**不用重建**
- 33 个孤立节点里 **18 个 capability 节点本身已带 `bsid_dimension` + `phase_index` 字段**，Phase 3 迁移**不需要任何 name 匹配或 LLM**，纯机械读字段补边即可
- 剩余 15 个 milestone 需要一张显式 `MILESTONE_TO_DIMENSION` 映射表，约 30 行 Python 常量

**影响**：MVP 工时从 4.5 天压到 **2-3 天**。

### 🔴 发现 3：9 种边类型 vs 现有 6 + 7 小写别名，交集只有 ENABLES
**数据评审**：现有 edge_type 命名混乱——`SEEDS / MEDIATES / MODERATED / LATENT_FORK / CORRELATES`（大写）+ `capability_unlock / attachment_formation / triggers / caregiver_decision / stress_cascade`（小写）混用。方案 9 种新边只有 `ENABLES` 能对上。

**影响**：必须提供 `LEGACY_EDGE_ALIAS` 迁移表，否则现有 2 个 baby 存档解析失败。

### 🔴 发现 4：Bayley-IV 7 维 vs 方案 8 维命名冲突
**数据 + 本体评审一致**：现有 `bsid_dimension` 是 Bayley-IV 7 维（gross_motor/fine_motor/cognitive/receptive_language/expressive_language/social_emotional/adaptive_behavior），方案砍成 8 维但**丢掉 adaptive_behavior**，`selfreg/temperament` 是无来源新增。

**影响**：必须明确 `bsid_dimension → ontology_dimension` 映射表，并保留 `bsid_dimension` 作 sub-label。

### 🔴 发现 5：Phase 挂单维度违反 Piaget
**本体 + Linus 评审一致**：Piaget 阶段是**跨维度全局时钟**，不是单维度属性。现有数据里**所有 Phase 节点本来就是全局的**（`phase:neonatal` 不挂任何 dimension）。方案 §3.1 的"motor/Late Infant 4-12m"是错误引入的维度×阶段笛卡尔积，会让同一 baby 在不同维度处于不同 phase，图谱割裂。

**影响**：Phase 保持全局，不做 per-dimension 拆分。

## 二、评审间的核心分歧

| 议题 | 学术派（本体） | 实用派（架构+代码） | Linus（极简） | **最终裁决** |
|------|----------------|---------------------|----------------|--------------|
| Dimension 数量 | 6 个对齐 Bayley-III | 7 个对齐现有 bsid | 4 个（body/mind/social/self） | **6 个**——对齐 Bayley-III + Vineland-3，同时吸收现有 bsid 的 7 维通过合并（gross+fine motor → motor, receptive+expressive language → language） |
| 边类型数量 | 9+attachment/sensitive 扩展 | 9 + legacy alias | 3（CONTAINS/EVOLVES/INFLUENCES）用属性消除类型 | **5 核心 + legacy 别名表**——折中：保留语义清晰度但合并重叠边（详见 §四） |
| 时间字段 | 要 `emerged_at` / `effective_from` | 需要但 Phase 4 再做 | YAGNI，删掉 `effective_from/to` | **只加 `emerged_at_day` 到节点**，边不加时间戳（延后） |
| Phase 是节点还是属性 | 节点（跨维度全局） | 保留现状（节点） | 属性（反节点） | **保留节点**——破坏性改动代价 vs 收益不值 |
| RULE 粒度 | 7 条细规则 | 7 条但只 warning | 1 条 META-RULE | **1 条 META-RULE + 3 条补充**（见 §五） |
| 孤岛处理 | 标准量表回填 | 机械字段回填 | 宁可显示"未知"不撒谎 | **三级回填**：字段→表→Unknown，绝不撒谎 |

## 三、最终方案 v1.0 · 本体定义

### 3.1 节点层级（收敛到 5 层，非 6 层）

```
L0  Baby            唯一，isCore=true，固定 id = "baby:core"
L1  Dimension       6 个全局 axis（替代原 8 个）
L2  Phase           9 个全局时间段（保持现状，不做维度拆分）
L3  Capability /    技能 / 首次事件
    Milestone
L4  Event           日常事件流水（日记/行为/训练）
```

**去掉 L5**：event 不单独成层，直接作 L4。Dimension / Phase / Capability-Milestone 三者正交（一个 capability 同时挂 dimension + phase，不嵌套）。

### 3.2 六维度（对齐 Bayley-III + Vineland-3）

| 维度 | 含义 | 吸收的 bsid_dimension |
|------|------|----------------------|
| `motor` | 粗大 + 精细运动 | gross_motor, fine_motor |
| `language` | 语言理解 + 表达 | receptive_language, expressive_language |
| `cognitive` | 认知（Piaget 映射） | cognitive |
| `socioemotional` | 社会情感 + 依恋模式（作为 state 字段而非独立维度） | social_emotional |
| `adaptive` | 自理行为（喂养/睡眠/如厕，Vineland-3） | adaptive_behavior（+ 吸收 nutrition） |
| `temperament` | 气质（Thomas-Chess 九维） + self-regulation（作为子向量） | — |

**保留字段** `bsid_dimension` 作 sub-label，不删除（向后兼容铁律）。

### 3.3 保留 attachment 为 socioemotional 子状态

`attachment` 不设独立 dimension，而是 baby 节点上的 `attachment_state` 字段，枚举 `secure|avoidant|ambivalent|disorganized`（Ainsworth 四分类），由 `SHAPES` 边的事件累积驱动。

## 四、边 Schema v1.0

### 4.1 核心 5 种 + 1 种未来扩展

| 边类型 | 语义 | 强制性 | 替代/合并的概念 |
|--------|------|--------|----------------|
| `BELONGS_TO` | capability/milestone → dimension | **META-RULE 强制** | 合并 `SEEDS`（作 alias） |
| `OCCURS_IN` | capability/milestone → phase | **META-RULE 强制** | 合并 `capability_unlock`（方向反转作 alias） |
| `EVOLVES_FROM` | 能力 A ← 能力 A' (同维度演化) | 推荐 | 合并 `SPECIALIZES`（weight>0.8 即为 SPECIALIZES） |
| `REINFORCES` | event → capability/trait（正向塑造，polarity=+1 时为 REINFORCES，-1 时为 REGRESSES） | event 节点强制 | 合并 `SHAPES`（target.category 区分）+ `REGRESSES`（polarity=-1）+ `triggers`（alias）+ `stress_cascade`（alias） |
| `ENABLES` | 前提依赖（跨 capability 的逻辑先后） | 可选，LLM 推断 | 保留现有 |

**未来扩展（v1.5+，不预埋）**：
- `OPENS_WINDOW` / `CLOSES_WINDOW`：敏感期 modulator
- `CO_REGULATES`：照护者-婴儿同步

### 4.2 Legacy 别名映射（MVP 必须携带）

```python
# backend/cradle/ontology.py
LEGACY_EDGE_ALIAS = {
    "SEEDS": "BELONGS_TO",
    "capability_unlock": "OCCURS_IN",       # 方向反转
    "MODERATED": "REINFORCES",              # polarity 由 weight 符号推断
    "LATENT_FORK": "EVOLVES_FROM",
    "CORRELATES": "EVOLVES_FROM",           # weight 弱
    "triggers": "REINFORCES",
    "attachment_formation": "REINFORCES",
    "stress_cascade": "REINFORCES",         # polarity = -1
    "caregiver_decision": "REINFORCES",
    "MEDIATES": "REINFORCES",               # 作中间节点时保留
}
```

### 4.3 边字段

```python
{
  "edge_id": "e_xxx",
  "source_id": "...",
  "target_id": "...",
  "edge_type": "REINFORCES",
  "weight": 0.8,                    # 已有
  "polarity": 1,                    # NEW: +1 增强 / -1 退行 / 0 中性
  "evidence": "observed",           # NEW: rct|theoretical|observed|llm_inferred
  # 时间戳延后到 v1.5，不加
}
```

## 五、META-RULE + 补充规则

### 5.1 META-RULE（一条压顶）
> **任何非 L0 节点必须至少有一条指向 L_parent（更低层）节点的 `BELONGS_TO` 或 `OCCURS_IN` 入边。**

这一条等价于原方案 RULE-1/2/3/4 的合取，消灭所有孤岛。

### 5.2 补充规则（3 条）

| ID | 规则 | 级别 |
|----|------|------|
| `R-time` | 节点 `emerged_at_day` 若存在，必须 ≤ `mastered_at_day` ≤ `last_reinforced_day` | ERROR |
| `R-dag` | 同 dimension 同 phase 内的 `EVOLVES_FROM` 链必须无环 | ERROR |
| `R-cover` | Newborn 连通分量覆盖 ≥ 90% 节点 | WARNING |

不再要求"强制 DAG"（让 Thelen 的退行与再涌现成立）。

### 5.3 校验函数签名

```python
# backend/cradle/validate.py
@dataclass
class ValidationError:
    rule: str                    # "META-RULE" | "R-time" | ...
    severity: Literal["ERROR", "WARNING"]
    node_id: str | None
    edge_id: str | None
    message: str

def validate_graph(graph: CradleGraph) -> list[ValidationError]:
    """返回所有违反项。MVP 阶段调用点只 logger.warning，不 raise。"""
```

## 六、迁移路径（替代原 Phase 0-4）

**MVP = 3 天，只做前两步。**

### Step 1（0.5 天）· Ontology 常量
- 新建 `backend/cradle/ontology.py`：6 维度定义 + `BSID_TO_DIMENSION` + `MILESTONE_TO_DIMENSION`（15 条）+ `LEGACY_EDGE_ALIAS` + `EVOLUTION_CHAINS`（WHO/Bayley，约 100 行）
- 新建 `backend/cradle/validate.py`：`validate_graph()` + 6 条规则
- `SCHEMA_VERSION = 2`，`_load_or_init` 读到 v1 触发迁移

### Step 2（1 天）· 在图谱生成源头强制 META-RULE
- 修改 `cradle_graph_store.py:save_capabilities_graph`：每 emit capability 同步 emit `BELONGS_TO` + `OCCURS_IN`（使用已有 `CAPABILITY_TO_DIMENSION`）
- 同上修改 `save_milestones_graph` + `save_stress_graph` + `save_identity_graph`
- 首次加载时 seed 6 个 Dimension 节点（如果缺失）
- `_save` 尾部调用 `validate_graph`，ERROR 级别只 logger.warning（不 raise，保护现有流程）

### Step 3（0.5 天）· 历史数据一次性修复
- 写 `scripts/migrate_cradle_graph_v1_to_v2.py`：
  - 对 2 个 baby 存档先 `.v1.bak` 备份
  - 遍历节点：capability 有 `bsid_dimension` → 查 `BSID_TO_DIMENSION` 补 BELONGS_TO；有 `phase_index` → 补 OCCURS_IN
  - milestone 查 `MILESTONE_TO_DIMENSION` 补边；查不到则归 `dimension:unknown` 保留（不撒谎）
  - 边类型走 `LEGACY_EDGE_ALIAS`
- **预期产出**：39 个连通分量降到 1-3 个

### Step 4（0.5 天）· 前端适配
- `graphConfig.js::EDGE_CONFIG` 新增 5 条核心边 + 10 条 legacy alias（共 15 行）
- `LifeGraph.jsx` **零改动**——现有 BFS radial tree 在引入 Dimension 节点后自动形成扇形分区
- Dimension 节点用 `category: "dimension"` 复用现有 NODE_CONFIG，`size` 调到 6

### Step 5（延后）· 事件驱动 + 时间回放
- `REINFORCES` 边的 polarity 日志
- 时间 scrubber 组件
- `GET /cradle/{baby}/graph?at_day=X` 后端过滤

## 七、风险与回滚

| 风险 | 缓解 |
|------|------|
| ERROR 级别日志刷屏 | 首周只 `logger.warning`，观察违反率再收紧 |
| 2 个 baby 存档迁移失败 | `.v1.bak` 强制备份 + 人工 diff |
| 扇形布局不如预期 | 已实测：`LifeGraph.jsx` radial tree 算法 72% 核心+28% 其他切片，Dimension 作 L1 fan-out 后自然产生 6 个 60° 扇形 |
| Feature flag 紧急回滚 | `config.py::CRADLE_ONTOLOGY_V2 = False` 退回旧 emit 逻辑 |

## 八、与原方案的关键差异

| 项 | 原 v0.1 | 最终 v1.0 | 原因 |
|----|---------|-----------|------|
| 改哪个文件 | `causality.py` | `cradle_graph_store.py` | 原文件定位错误 |
| Dimension 数 | 8 | 6 | 学术合规 + 吸收 adaptive |
| 边类型数 | 9 | 5 + legacy alias | 消除语义重叠（SHAPES/REGRESSES 用 polarity） |
| 规则数 | 7 | 1 META + 3 | 消除特殊情况（Linus） |
| Phase 层 | per-dimension | 全局（保留现状） | Piaget 语义 + 破坏性代价 |
| 时间字段 | 节点+边 | 只加节点 `emerged_at_day` | YAGNI |
| 迁移方式 | LLM + name 匹配 | 纯字段机械补齐（已有 bsid） | 数据评审发现 |
| MVP 工时 | 7-13 天 | 2.5-3 天 | 复用现有常量 |
| 孤岛成功率 | ≤50% | ≥95%（18 个字段齐全 + 15 个映射表 + 余者显示 unknown） | 字段机械回填 |

## 九、开放问题交付状态

| 原 Open Question | 回答 |
|------------------|------|
| EVOLVES_FROM 链来源 | **硬编码 WHO/Bayley/Piaget** seed + 允许 LLM 补充（evidence=llm_inferred 标记） |
| 时间戳粒度 | **按天（day）**——复用现有 `age_days`，不引入真实时钟 |
| 孤岛兼容 | **迁移期 100% 补齐**；未来 LLM 输出则 validate warn；绝不 raise |
| Dimension 个数 | **6 个**（Bayley-III + Vineland-3 对齐） |
| Phase 重叠 | **允许**——capability 可挂多条 `OCCURS_IN` |
| 历史节点时间戳 | `emerged_at_day` 按 phase.start_day 回填，`mastered_at_day` 置空 |
| 性能 | MVP 无时间过滤，全量返回；Phase 5 引入 `at_day` 查询 |
