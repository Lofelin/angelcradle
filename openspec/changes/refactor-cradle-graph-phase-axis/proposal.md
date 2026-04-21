# 变更提案：摇篮图谱 phase 节点架构修正（per-dimension Phase + progression 两分）

## 动机

当前摇篮因果图谱（`cradle_graph_store.py`）把 `cradle.phases.PHASES` 中的 12 个**全局推进步**直接作为 L2 `phase` 节点写入图谱（`pid = f"phase:{phase_name}"`），形成 `phase:Neonatal` / `phase:Sensory Awakening` / ... 等节点。**这与 `specs/cradle-dev-ontology/proposal.md` 定稿的本体论冲突**：

1. **违反 per-dimension 正交**（cradle-dev-ontology proposal.md:58）
   定稿要求 L2 Phase 是 **per dimension** 的（如 motor 维度的 Neonatal/Early Infant/Late Infant/Toddler/Preschool；cognitive 维度按 Piaget 划分）。一个 baby 在 motor 维度可能进入 Toddler，在 language 维度仍在 Late Infant——不应被全局阶段强制对齐。当前实现把 12 个全局阶段当作所有维度共享的"时间轴"，把高维状态降成一维游标。

2. **违反 RULE-1 / RULE-2 反孤岛约束**（cradle-dev-ontology proposal.md:138-139）
   现有 `phase` 节点既无 `dimension` 字段也无 `BELONGS_TO → dimension` 边，是孤岛。下游 `capability OCCURS_IN → phase:Neonatal` 形式上满足 RULE-2，但目标 phase 不归属任何 dimension，丢失了维度分层信息。

3. **运行时编排污染领域知识**
   `cradle.phases.PHASES` 是引擎的 state machine cursor（驱动 nanny 模拟、scheduler 调度、世界就绪判定），它的"阶段"是**调度/运行时**概念。Bayley-III / Vineland-3 / WHO MGRS / Piaget 意义上的**发育期**是**领域知识**概念。两者被合一后：图谱节点既要表达"baby 当前调度到第几步"又要表达"哪个能力归属哪个发育期"，语义混乱。

## 目标

- **G1 概念两分**：图谱中明确区分 `progression`（引擎调度游标，全局唯一时间轴）与 `phase`（per-dimension 发育期，按 6 维各自展开）。
- **G2 per-dimension Phase 落地**：phase 节点改为 `phase:{dim}:{stage}` 形式，每个 phase 节点必须挂 `BELONGS_TO → dimension:{dim}`。
- **G3 OCCURS_IN 重指**：`capability` / `milestone` 的 OCCURS_IN 边目标改为对应维度的 phase（依 capability 的 `bsid_dimension` 路由），消灭"全局孤岛 phase"。
- **G4 progression 显式化**：将原 12 个 cradle 阶段改名为 `progression:{name}`（category=`progression`，layer 独立），仅承担"引擎在第几步"的叙事角色，不参与 OCCURS_IN 链。
- **G5 数据不丢失**：v2 → v3 迁移脚本无损升级现有 `archive/AC-*/cradle_graph.json`，原 `phase:Neonatal` 节点拆分为对应 progression + 多个 per-dim phase 副本。
- **G6 校验前移**：`validate.py` 增加对 phase 节点 `BELONGS_TO → dimension` 强制约束（ERROR 级），杜绝再次孤岛化。

## 范围

### 包含

- `backend/cradle_graph_store.py` 全部 `save_*_graph` 写入函数的 phase 路由改造
- `backend/cradle/ontology.py` 新增：per-dimension Phase 静态表 + capability→phase 路由函数
- `backend/cradle/validate.py` META-RULE 扩展（phase 必须 BELONGS_TO）
- `backend/scripts/migrate_cradle_graph_v2_to_v3.py` 数据迁移脚本（机械、零 LLM）
- `backend/cradle/CLAUDE.md` L2 文档更新（图谱章节）
- 单元测试：`backend/tests/test_phase_dimension_routing.py`、`backend/tests/test_validate_phase_belongs_to.py`

### 不包含

- 前端可视化样式（`LifeGraph.jsx`）：通用按 category 染色，新 category `progression` 只需追加配色即可，**不重写组件**
- `cradle.phases.PHASES` 引擎数据本身：12 个全局推进步**保留不动**，它们是 nanny/scheduler/heartbeat 的运行时数据源，仅在图谱表达层重命名
- 时间维度（emerged_at/mastered_at/strength）—— cradle-dev-ontology proposal 中的 Phase 4 不在本变更范围
- `EVOLUTION_CHAINS` 改造（已 per-dimension 组织，不需动）

## 成功标准

- ✅ `validate_graph(load_or_init(any_baby))` 对所有现存 baby 返回 0 条 ERROR
- ✅ 任一 capability 节点：`OCCURS_IN` 边目标节点 category=`phase` 且形如 `phase:{dim}:{stage}`，且该 phase 节点有 `BELONGS_TO → dimension:{dim}` 出边
- ✅ 原 9 个 `phase:Neonatal` 等全局节点全部从 category `phase` 迁出，新 category 为 `progression`，layer 独立
- ✅ 迁移脚本 idempotent：重复运行不产生重复节点/重复边
- ✅ 现有前端 `LifeGraph.jsx` 渲染不报错（新 category 落入 `colorMap` 自动分配色板）
- ✅ `nanny.complete_phase` → `simulate_phase` → `resolve_critical_event` 全链路跑一个完整 phase 后图谱通过校验

## 风险与缓解

| 风险 | 等级 | 缓解 |
|------|------|------|
| 下游消费者（前端/scheduler/handlers）硬编码 `phase:{name}` 形式 | 低 | grep 已确认前端无硬编码；scheduler/handlers 通过 `PHASES[idx].name` 间接访问，配合本变更同步重构 |
| 迁移脚本误删原 v2 数据 | 中 | 强制 `.v2.bak` 备份；`_save` 在迁移完成后才覆盖；提供 `--dry-run` |
| per-dimension Phase 静态表设计错误（划分粒度不对） | 中 | 静态表对齐 cradle-dev-ontology proposal.md:58-69 的 motor 示例 + Bayley/Piaget/Vineland 标准；首版采用保守 4-5 个 phase/dim |
| `_ensure_occurs_in` 旧调用方传入 `phase:Neonatal` 字符串 | 低 | 旧函数签名保留向后兼容（接受 progression_name），内部派发到正确 per-dim phase |
