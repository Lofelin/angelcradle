# 任务清单：refactor-cradle-graph-phase-axis

## 1. 本体论扩展（Phase A）

- [x] 1.1 在 `backend/cradle/ontology.py` 新增 `DIMENSION_PHASES` 静态表（6 维 × 4-5 phase，按 design.md §2 规约）
- [x] 1.2 新增 `phase_for(dim, age_days) -> str` 路由函数
- [x] 1.3 新增 `all_phase_ids() -> list[str]` 枚举函数
- [x] 1.4 更新 `cradle/ontology.py` 文件头 L3 注释（[OUTPUT] 增项 + [PROTOCOL] 提示）

## 2. 图谱写入路径改造（Phase B）

- [x] 2.1 在 `backend/cradle_graph_store.py` 新增 `_ensure_phase_node(g, dim, stage)`：自动建 `phase:{dim}:{key}` + `BELONGS_TO → dimension:{dim}` 边
- [x] 2.2 新增 `_ensure_progression_node(g, phase_index, name, display)`：建 `progression:{name}` + 链到 `baby:core` 与前一 progression
- [x] 2.3 新增 `_route_capability_to_phase(g, cap_name, age_days) -> str | None` + `_route_milestone_to_phase`：按维度 + age_days 找 per-dim phase id
- [x] 2.4 重写 `save_phase_graph`：内部 phase 节点改为 progression（不再 `phase:{phase_name}`）
- [x] 2.5 重写 `save_capabilities_graph`：每个 capability 的 OCCURS_IN 改指 per-dim phase（通过 2.3 路由）
- [x] 2.6 重写 `save_milestones_graph`：milestone 同样按 dimension + age_days 路由 OCCURS_IN
- [x] 2.7 重写 `save_psychosocial_graph` / `save_caregiver_graph` / `save_scene_graph` / `save_stress_graph` / `save_critical_graph`：所有 `pid = f"phase:{phase_name}"` 改为 progression id；事件类节点链到 progression（叙事时间线），非 phase
- [x] 2.8 在所有 `save_*_graph` 入口处确保 `_ensure_dimension_nodes` + per-dim phase 节点已播种（幂等）
- [x] 2.9 更新 `cradle_graph_store.py` 文件头 L3 注释 + SCHEMA_VERSION = 3 + LAYER_PROGRESSION + CATEGORY_LAYER 增 progression
- [x] 2.10 `_ensure_occurs_in` 增加守卫：拒绝指向非 phase 节点（progression 等）的 OCCURS_IN

## 3. 校验扩展（Phase C）

- [x] 3.1 在 `backend/cradle/validate.py` 增加 `META-RULE-PHASE`：phase 节点必须有 `BELONGS_TO` 出边（ERROR 级）
- [x] 3.2 增加 `META-RULE-OCCURS-TARGET`：capability/milestone 的 OCCURS_IN 边目标 category 必须为 `phase`，不可为 `progression`（ERROR 级）
- [x] 3.3 更新 `validate.py` 文件头 L3 注释

## 4. 数据迁移脚本（Phase D）

- [x] 4.1 新建 `backend/scripts/migrate_cradle_graph_v2_to_v3.py`，复用 `migrate_v1_to_v2.py` 的备份/idempotent 模式
- [x] 4.2 实现步骤 1-2：备份 + 旧 phase 节点重分类为 progression（含边重写）
- [x] 4.3 实现步骤 3：播种全部 per-dim phase 节点 + BELONGS_TO 边
- [x] 4.4 实现步骤 4：capability/milestone OCCURS_IN 重指（含 no_route 兜底清理 progression 旧边）
- [x] 4.5 实现步骤 5-6：写 SCHEMA_VERSION=3 + 跑 validate 输出对比
- [x] 4.6 支持 `--dry-run` 标志
- [x] 4.7 在 `archive/AC-20260417-38883/` 上跑一次实测：迁移前 9 ERROR → 迁移后 0 ERROR
- [x] 4.8 把现有所有 baby 全量迁移：3 个 baby（38883/25815/26930）全部 0 ERROR
- [x] 4.9 顺手补 `MILESTONE_TO_DIMENSION` 中漏掉的 `first_crawl` / `first_point` 映射（迁移诊断发现）

## 5. 测试与验证

- [x] 5.1 新建 `backend/tests/test_phase_dimension_routing.py`：22 项覆盖 `phase_for` 各维度边界 + `_ensure_phase_node` + capability/milestone 路由
- [x] 5.2 新建 `backend/tests/test_validate_phase_belongs_to.py`：7 项覆盖新 META-RULE + 真实迁移图谱断言
- [x] 5.3 端到端冒烟：手动构造 BabyState + 调 init/save_capabilities/save_milestones/save_phase_graph，校验 0 ERROR、3 个 per-dim phase、3 个 progression 都正确
- [x] 5.4 迁移脚本幂等性测试：在已迁移 v3 数据上重跑，`重分类 0 / 播种 0 / 新增 0 / 删除 0`
- [ ] 5.5 前端冒烟：本地启动 `frontend/`，打开任意 baby 的图谱视图，确认 progression + phase 节点都正常渲染（**待用户手动验证**——LifeGraph.jsx 通用 category 染色，理论上无需改动）

## 6. 文档同步（DocOps 回环）

- [x] 6.1 更新 `backend/cradle/CLAUDE.md`（L2）：新增"图谱概念两分（v3）"段落 + 表格
- [ ] 6.2 ~~更新 `backend/CLAUDE.md`（L1）~~：backend 级 L1 文档不存在，跳过
- [x] 6.3 在 `specs/cradle-dev-ontology/proposal.md` 末尾追加 §9"已实现状态"段落，标注本变更归档号
