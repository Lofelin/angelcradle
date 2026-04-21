# Delta for cradle-graph

## ADDED Requirements

### Requirement: per-dimension Phase 节点
图谱中的 `phase` 节点 SHALL 是按 6 个发育维度（motor / language / cognitive / socioemotional / adaptive / temperament）独立展开的发育期节点。每个 phase 节点的 `node_id` MUST 形如 `phase:{dim}:{stage_key}`，且 MUST 拥有 `dimension` 字段记录所属维度。

#### Scenario: 解锁 motor 维度的 toddler 期能力
- GIVEN baby 当前 age_days = 500，新解锁能力 `walking`（CAPABILITY_TO_DIMENSION = `gross_motor` → BSID_TO_DIMENSION = `motor`）
- WHEN 调用 `save_capabilities_graph(baby_id, phase_index, phase_name, ["walking"], state)`
- THEN 图谱中 MUST 存在节点 `phase:motor:toddler`，且其 `category` = `phase`、`dimension` = `motor`
- AND `capability:walking` MUST 有出边 `OCCURS_IN → phase:motor:toddler`

#### Scenario: 同时跨多个维度
- GIVEN baby 当前 age_days = 600，新解锁能力 `[walking, first_words]`
- WHEN 调用 `save_capabilities_graph(...)`
- THEN 图谱 MUST 同时存在 `phase:motor:toddler` 和 `phase:language:first_words` 两个节点
- AND `capability:walking` OCCURS_IN `phase:motor:toddler`，`capability:first_words` OCCURS_IN `phase:language:first_words`

### Requirement: phase 节点强制 BELONGS_TO 维度
任何 `category=="phase"` 节点 MUST 至少有一条 `BELONGS_TO` 出边指向对应的 `dimension:{dim}` 节点。校验器 SHALL 对违反此规则的节点产出 ERROR 级 `META-RULE-PHASE` 违反。

#### Scenario: 创建 phase 节点
- GIVEN 调用 `_ensure_phase_node(g, "motor", {"key": "toddler", ...})`
- WHEN 函数返回
- THEN 图谱 MUST 包含节点 `phase:motor:toddler`
- AND MUST 包含节点 `dimension:motor`
- AND MUST 包含边 `phase:motor:toddler -> dimension:motor`，edge_type=`BELONGS_TO`

#### Scenario: 校验孤岛 phase 节点
- GIVEN 图谱中存在节点 `phase:motor:toddler` 但没有任何 `BELONGS_TO` 出边
- WHEN 调用 `validate_graph(graph)`
- THEN 返回的错误列表 MUST 包含一条 `rule="META-RULE-PHASE"`、`severity="ERROR"`、`node_id="phase:motor:toddler"` 的违反

### Requirement: progression 节点（引擎调度游标）
原 `cradle.phases.PHASES` 的 12 个全局推进步 MUST 在图谱中表示为 `category="progression"` 节点，`node_id` 形如 `progression:{phase_name}`（其中 `phase_name` 来自 `Phase.name`）。progression 节点 SHALL NOT 持有 `BELONGS_TO → dimension` 边，且 SHALL NOT 作为 capability/milestone 的 `OCCURS_IN` 边目标。

#### Scenario: complete_phase 触发 progression 写入
- GIVEN baby 完成 phase_index=0 的 `neonatal` 阶段
- WHEN 调用 `save_phase_graph(baby_id, 0, "neonatal", "Neonatal", state)`
- THEN 图谱 MUST 包含节点 `progression:neonatal`，`category` = `progression`，`phase_index` = 0
- AND MUST 包含边 `baby:core -> progression:neonatal`
- AND MUST NOT 创建任何 `BELONGS_TO` 边以 progression 为源

#### Scenario: progression 步骤间链接
- GIVEN 已存在 `progression:neonatal`，baby 完成 phase_index=1
- WHEN 调用 `save_phase_graph(baby_id, 1, "sensory_awakening", "Sensory Awakening", state)`
- THEN 图谱 MUST 新增节点 `progression:sensory_awakening`
- AND MUST 包含边 `progression:neonatal -> progression:sensory_awakening`，edge_type=`EVOLVES_FROM`

### Requirement: capability/milestone OCCURS_IN 目标约束
任何 `capability` 或 `milestone` 节点的 `OCCURS_IN` 出边目标 MUST 是 `category=="phase"` 节点，SHALL NOT 是 `category=="progression"` 节点。校验器 SHALL 对违反此规则的边产出 ERROR 级 `META-RULE-OCCURS-TARGET` 违反。

#### Scenario: 旧数据自动迁移
- GIVEN v2 图谱中 `capability:walking -> phase:Locomotion`，edge_type=`OCCURS_IN`
- WHEN 运行 `migrate_cradle_graph_v2_to_v3.py`
- THEN 该边 MUST 被删除
- AND 新增边 `capability:walking -> phase:motor:toddler`，edge_type=`OCCURS_IN`
- AND 节点 `phase:Locomotion` 被重命名为 `progression:locomotion`，category 改为 `progression`

### Requirement: phase_for 路由函数
`cradle.ontology` MUST 暴露 `phase_for(dim: str, age_days: int) -> str` 函数，按 `DIMENSION_PHASES[dim]` 表中各 stage 的 `age_days` 区间（左闭右开），返回对应 `phase:{dim}:{key}` id；当 age_days 超出全表上界时返回该维度最后一个 stage。

#### Scenario: 区间边界
- GIVEN `DIMENSION_PHASES["motor"]` 中 `late_infant.age_days = (180, 365)`
- WHEN 调用 `phase_for("motor", 180)`
- THEN 返回 `"phase:motor:late_infant"`
- AND 调用 `phase_for("motor", 365)` 返回 `"phase:motor:toddler"`（不含右端点）

#### Scenario: 越界兜底
- GIVEN `DIMENSION_PHASES["motor"]` 末期 `preschool.age_days = (1095, 2555)`
- WHEN 调用 `phase_for("motor", 9999)`
- THEN 返回 `"phase:motor:preschool"`

### Requirement: v2→v3 迁移脚本幂等性
`scripts/migrate_cradle_graph_v2_to_v3.py` MUST 在已迁移到 v3 的图谱上重复运行时不产生节点/边的重复或修改，且 MUST 在迁移前创建 `.v2.bak` 备份。

#### Scenario: 重复运行
- GIVEN 已运行迁移脚本一次，图谱 SCHEMA_VERSION=3
- WHEN 再次运行迁移脚本
- THEN 图谱 nodes/edges MUST 与运行前完全一致（diff 为空）
- AND `.v2.bak` 文件 MUST 保持不变（不覆盖原备份）

## MODIFIED Requirements

### Requirement: META-RULE 反孤岛约束
任何 `category` 为 `capability` 或 `milestone` 的节点 MUST 至少有一条 `BELONGS_TO` 或 `OCCURS_IN` 出边。新增：当存在 `OCCURS_IN` 出边时，目标节点 MUST 为 `category=="phase"`（per-dimension Phase）。校验器 SHALL 对孤岛节点产出 ERROR 级 `META-RULE` 违反，对 OCCURS_IN 目标错误产出 ERROR 级 `META-RULE-OCCURS-TARGET` 违反。

#### Scenario: capability 仅有 OCCURS_IN 指向 progression（错误）
- GIVEN 图谱中 `capability:walking` 仅有一条出边 `walking -> progression:locomotion`，edge_type=`OCCURS_IN`
- WHEN 调用 `validate_graph(graph)`
- THEN 返回的错误列表 MUST 包含一条 `rule="META-RULE-OCCURS-TARGET"`、`severity="ERROR"`、`node_id="capability:walking"` 的违反

#### Scenario: capability 有合法 OCCURS_IN
- GIVEN 图谱中 `capability:walking` 有 `walking -> phase:motor:toddler`，edge_type=`OCCURS_IN`，且 `phase:motor:toddler` 有 `BELONGS_TO → dimension:motor`
- WHEN 调用 `validate_graph(graph)`
- THEN 错误列表中 MUST NOT 包含针对 `capability:walking` 的 META-RULE / META-RULE-OCCURS-TARGET 违反

## REMOVED Requirements

### Requirement: 全局 phase 节点直接来自 cradle.phases
**移除原因**：原规则要求 `save_phase_graph` 用 `pid = f"phase:{phase_name}"` 形式（其中 `phase_name` 来自 `cradle.phases.PHASES[i].name`）创建 L2 phase 节点。本变更将该角色拆分为 `progression`（引擎调度）+ `phase:{dim}:{stage}`（per-dimension 发育期）两类节点；原全局 phase 节点形式不再被任何写入路径产出。
