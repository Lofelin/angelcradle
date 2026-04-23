# 任务清单：add-womb-conception-graph

## 1. 设计契约固化（Phase A）

- [ ] 1.1 冻结 `frontend/src/data/womb-conception-sample.json` v3 为"设计参考实现"（design-as-code），作为后端 emit 输出契约。
- [ ] 1.2 在 `openspec/changes/add-womb-conception-graph/design.md` 写出完整节点类型清单 + 边类型清单 + uuid 构造规则 + 多重边判定规则。
- [ ] 1.3 在 `specs/womb-graph/spec.md` 中以 SHALL / MUST 形式固化上述契约。

## 2. 后端 graph_emit 帮手库（Phase B）

- [ ] 2.1 新建 `backend/womb/graph_emit.py`，文件头 L3 注释齐全（INPUT/OUTPUT/POS/PROTOCOL）。
- [ ] 2.2 实现节点构造器（纯函数，无状态）：
  - `node_baby(baby_id, **meta)` / `node_species(code)` / `node_parent(side, genome)` / `node_methylation(profile)` / `node_birthplace(region)`
  - `node_hormone(name)` / `node_nutrient(name)` / `node_teratogen(name)`
  - `node_organ(name, formation_stage, maturation_stage?)` / `node_vital(name, unit)`
  - `node_reflex(name, emerges_stage)` / `node_temperament(dimension, score, defined_stage)`
  - `node_event(event_type, stage_index, result, **meta)`
  - `node_defect(defect_type, severity)`
  - `node_narrative(stage_index, text)`
- [ ] 2.3 实现边构造器（纯函数）：
  - `edge_inherits(source_parent, baby_id)` / `edge_expresses_as(species, baby_id)` / `edge_epigenetic_of(methylation, baby_id)` / `edge_born_at(birthplace, baby_id)`
  - `edge_modulates(hormone, organ, stage_index, weight, level_at, description, polarity?)`
  - `edge_feeds(nutrient, target, stage_index, weight, level_at?, description)`
  - `edge_damages(teratogen, organ, stage_index, weight, description)`
  - `edge_exposed(teratogen, baby_id, stage_index, exposure, description)`
  - `edge_intake(nutrient, baby_id, stage_index, level, status?)`
  - `edge_causes(source, target, stage_index, weight, description)` (teratogen→hormone 等)
  - `edge_observes(vital, organ)` / `edge_measured(vital, baby_id, stage_index, v, unit)`
  - `edge_develops(baby_id, organ, stage_index, phase='FORMS'|'MATURES', weight)`
  - `edge_acquires(baby_id, reflex, stage_index)` / `edge_characterizes(temperament, baby_id)`
  - `edge_caused_by(cause, event, stage_index, weight, description)` / `edge_results_in(event, defect)` / `edge_affects(defect, baby_id, weight)`
  - `edge_emerges_in(reflex, organ, stage_index, description)`
  - `edge_describes(narrative, baby_id, stage_index)`
- [x] 2.4 实现 uuid 构造规则（UUIDv5 + 固定 namespace，标准 RFC4122 格式）：`str(uuid.uuid5(_NS, f"E|{source}|{target}|{etype}|{stage_index or ''}|{description}"))`。节点同样用 `str(uuid.uuid5(_NS, f"N|{raw_id}"))`，raw 可读 id 保留在 `metadata.raw_id`。payload 纳入 stage_index + description 保证跨阶段同类型同方向边的 uuid 唯一。匹配标准 UUID 正则 `^[0-9a-f]{8}-[0-9a-f]{4}-5[0-9a-f]{3}-[0-9a-f]{4}-[0-9a-f]{12}$`。
- [ ] 2.5 实现 delta 工具：
  - `delta_add(nodes=None, edges=None) -> dict`
  - `delta_update(nodes=None, edges=None) -> dict`
  - `delta_remove(node_ids=None, edge_uuids=None) -> dict`
  - `merge_deltas(*deltas) -> dict`：把多个 delta 合并成一个大 delta（业务代码内部聚合用）。
- [ ] 2.6 单元测试 `backend/tests/test_graph_emit.py`：构造器返回 dict 符合 schema；uuid 唯一性；merge_deltas 幂等。

## 3. 业务函数接入 emit（Phase C）

- [ ] 3.1 `backend/womb/hormones.py`：`compute_hormones` 返回值新增 `graph_delta`，包含：
  - 首次调用时 emit 4 个 hormone 节点（cortisol/thyroid/sex/hcg）
  - 每阶段 emit `hormone → organ` 多重边（按 `get_hormone_effects` 的 level 计算 weight）
  - 每阶段 emit `hormone → baby AFFECTS` 边（level 作为 metadata）
- [ ] 3.2 `backend/womb/nutrients.py`：`get_overall_nutrient_risk_effects` 分析时 emit：
  - 首次调用时 emit 5 个 nutrient 节点（folate/iodine/iron/dha/calcium）
  - 每阶段 emit `nutrient → baby INTAKE` 边
  - 关键阶段 emit `nutrient → organ FEEDS` 边（叶酸→脑 S1/S3、碘→甲状腺 S3、DHA→脑 S5、钙→心/骨 S6）
- [ ] 3.3 `backend/womb/teratogen.py`：`get_overall_teratogen_risk` 时 emit：
  - 首次调用时 emit teratogen 节点（按实际暴露项创建，可选集合：alcohol/pm25/stress/smoke/radiation/drug）
  - 每阶段暴露时 emit `teratogen → baby EXPOSED` 边
  - 敏感窗口 emit `teratogen → organ DAMAGES` 边（基于 `TERATOGEN_SENSITIVITY_MATRIX`）
- [ ] 3.4 `backend/womb/vitals.py`：`compute_vitals` emit：
  - 首次调用时 emit 7 个 vital 节点（hr/weight/length/amniotic/movement/bp/oxygen）
  - 每阶段可观测时 emit `vital → baby MEASURED` 边
  - 固定关系 emit `vital → organ OBSERVES` 边（hr→heart、movement→brain、oxygen→lung）
- [ ] 3.5 `backend/womb/fate.py`：`roll_miscarriage` / `roll_multiples` / `roll_congenital_defects` / `roll_preterm` / `roll_stillbirth` emit：
  - 每次掷骰 emit 对应 event 节点（`event_{type}_s{stage}`）
  - 命中时 emit `RESULTS_IN → defect` + `defect → baby AFFECTS`
  - emit `CAUSED_BY` 归因边（从 nutrient/teratogen/hormone 指向 event，带各自的 stage_index + weight）
  - 流产特殊处理：emit `TerminatedBy` 边 + baby 节点 status update
- [ ] 3.6 `backend/womb/dynamic_env.py`：`roll_env_change` 触发时 emit event 节点 + 对应关系边（如 stress→cortisol CAUSES）
- [ ] 3.7 `backend/womb/stages.py` 中 `express_stream`：
  - S1 开始时 emit 结构性初始化 delta：baby / species / father_genome / mother_genome / methylation / birthplace 节点 + 各自连到 baby 的边
  - 每阶段器官"形成"/"成熟"时 emit `baby → organ DEVELOPS(stage, 'FORMS'|'MATURES')` 边
  - 每阶段反射获得 emit `baby → reflex ACQUIRES(stage)` + `reflex → organ EMERGES_IN(stage)` 边
  - S6 气质定型 emit `baby → temperament CRYSTALLIZES`
  - 每阶段 LLM 叙事完成 emit narrative 节点 + `narrative → baby DESCRIBES(stage)` 边
  - 每阶段结束时调用 `merge_deltas(...)` 聚合所有子系统的 delta，塞进 SSE 事件的 `graph_delta` 字段
- [ ] 3.8 `backend/womb/heredity.py` / `epigenetics.py` / `birthplace.py`：遗传 / 表观遗传 / 出生地相关节点的 emit 在 S1 开始时由 stages.py 统一触发（这些模块不直接 emit，由编排层调用其数据 + graph_emit.py 构造）。

## 4. API 层扩展（Phase D）

- [ ] 4.1 `backend/api/conceive.py` SSE 事件结构扩展：所有 `stage_in_progress` / `stage_complete` / `conception_complete` 事件支持 `graph_delta` 字段透传。
- [ ] 4.2 SSE 粒度可选优化：在 `stage_in_progress` 内部拆子事件（`hormone_computed` / `vitals_computed` / `fate_rolled` / `narrative_streamed`），每个携带自己的 `graph_delta`，让前端看到节点"涌现时机"更精细。本期可选，若时间不够保持整合在 `stage_in_progress` 里。
- [ ] 4.3 `backend/api/conceive.py` 文件头 L3 注释更新（[OUTPUT] 增项 graph_delta）。
- [ ] 4.4 `backend/api/conceive.py` 对 `graph_delta` 字段做 JSON 可序列化校验（`json.dumps` 不抛异常）。

## 5. 前端 hook + 组件扩展（Phase E）

- [ ] 5.1 新建 `frontend/src/hooks/useWombGraph.js`：
  - 接受 `sessionId` 参数
  - 内部订阅对应 SSE
  - 维护 `{nodes: Map, edges: Map}` 本地状态
  - 实现 `mergeGraph(state, delta)` 纯函数（支持 add/update/remove 四种操作，metadata 深合并，其他字段浅合并）
  - 返回 `{ nodes: Array, edges: Array }`（即时快照）
  - 文件头 L3 注释齐全
- [ ] 5.2 修改 `frontend/src/components/LifeGraph.jsx` 的 `adaptEdges`：**优先使用后端提供的 `e.uuid`**（content-hash 格式 `e_xxxxxxxxxx`），仅在缺失时 fallback 到原 `${source}->${target}:${type}` 自构造规则。后端 uuid 不再被前端重新包装。
- [ ] 5.3 修改 `frontend/src/components/LifeGraph.jsx` 的 `buildSimEdges`：确认 `uuid` 唯一即可保留多重边（当前逻辑本就是按 uuid 唯一分散曲率，不改）。
- [ ] 5.4 `frontend/src/Cradle.jsx` 或 conceive 会话详情页面接入：`const { nodes, edges } = useWombGraph(sessionId); <LifeGraph nodes={nodes} edges={edges} />`。
- [ ] 5.5 前端空态处理：`useWombGraph` 返回空数组时 `LifeGraph.jsx` 显示 empty state（已支持，验证不破坏）。
- [ ] 5.6 前端 SSE 事件容错：`graph_delta` 字段缺失 / 非法 JSON 时不 crash，静默 skip。

## 6. 样本数据校对（Phase F）

- [ ] 6.1 回头复审 `frontend/src/data/womb-conception-sample.json` v3，删除所有 Stage 节点（stage_1..stage_7），迁移时间坐标信息到边的 `stage_index` 属性。
- [ ] 6.2 确认样本中 `hormone_cortisol → organ_heart` 至少 3 条多重边（s2/s4/s6），`hormone_cortisol → organ_brain` 至少 3 条，`hormone_thyroid → organ_brain` 至少 2 条，`nutrient_folate → organ_brain` 至少 2 条。
- [ ] 6.3 删除所有 `RECORDED_AT` / `SAMPLED_AT` / `MEASURED_AT` / `TRIGGERED_IN` / `DEVELOPS_THROUGH` / `PRECEDES` 到 Stage 节点的边。
- [ ] 6.4 迁移 `FORMS` / `MATURES` 从 `stage_N → organ` 改为 `baby → organ DEVELOPS(phase=FORMS|MATURES, stage_index=N)`。
- [ ] 6.5 `EXPOSED_AT` 改为 `teratogen → baby EXPOSED(stage_index=N, exposure=...)`。
- [ ] 6.6 `SAMPLED_AT`（营养）改为 `nutrient → baby INTAKE(stage_index=N, level=...)`。
- [ ] 6.7 `MEASURED_AT`（体征）改为 `vital → baby MEASURED(stage_index=N, v=...)`。
- [ ] 6.8 `RECORDED_AT`（激素）移动到 `hormone_*.metadata.track` 数组，删除对应边。
- [ ] 6.9 最终节点数 ≤ 40，边数 ≤ 85，符合成功标准规模。

## 7. 测试与验证（Phase G — 四道验证关）

- [ ] 7.1 **Gate 1 · pytest 通过**：`graph_emit.py` 单元测试全部绿。
- [ ] 7.2 **Gate 2 · 单元语义对**：跑一次 human 怀孕，断言：
  - 无 Stage 节点（`assert not any(n["id"].startswith("stage_") for n in nodes)`）
  - cortisol/thyroid/sex/hcg 各 1 个节点（反向断言："`cortisol_s2` 不存在"）
  - `hormone_cortisol → organ_heart` 多重边 ≥ 3 条
  - `nutrient_folate → organ_brain` 多重边 ≥ 2 条
  - 所有边带 `stage_index` 字段或明确是结构性边（`INHERITS_FROM` / `EXPRESSES_AS` 等）
- [ ] 7.3 **Gate 3 · 整体形状对**：
  - 打印节点度数分布：baby_this 的 in-degree + out-degree 应为全图最高（≥20）
  - 对照样本 JSON 的节点总数、边总数、组分布，±15% 范围内
  - **启动前端，打开浏览器实际看图**，截图归档
- [ ] 7.4 **Gate 4 · 用户视角对**：
  - "受精卵期（S1）图上会出现胎动节点吗？" → 不会（胎动 S4 才 emit）
  - "流产后会继续 emit 未来阶段的激素边吗？" → 不会（流产触发 remove 未来阶段节点）
  - "同一激素 cortisol 会被拆成多个节点吗？" → 不会（continuant 稳定）
- [ ] 7.5 前后端联调：真实跑一次 human 怀孕 SSE，观测前端图实时生长。
- [ ] 7.6 流产场景测试：mock `roll_miscarriage` 在 S3 命中，前端图在 S3 停止生长且显示 `TerminatedBy` 事件。
- [ ] 7.7 多胎场景预研（本期不实施，记录为后续 proposal 输入）：两个 baby_this 节点 + 共享 SpeciesBlueprint / Father / Mother。
- [ ] 7.8 性能 smoke test：跑 10 次怀孕，前端图渲染无明显卡顿，D3 simulation tick 率 ≥ 30fps。

## 8. 图谱落库 + 查询 API（Phase I · 新增）

- [x] 8.1 `backend/api/registry.py` 新增 `save_womb_graph(baby_id, graph)` + `load_womb_graph(baby_id)` 函数，落库到 `archive/{baby_id}/womb_graph.json`
- [x] 8.2 `backend/api/conceive.py` 在 SSE 循环内维护后端累积图状态 `_graph_state = {nodes: {}, edges: {}}`，并在每个 `graph_delta` 事件上应用 add/update/remove 四种操作
- [x] 8.3 `born` 事件触发时调用 `registry.save_womb_graph(baby_id, {...})` 保存快照（含 stats 字段）
- [x] 8.4 流产/发育失败路径也落库（status='failed'），便于事后回看
- [x] 8.5 新增端点 `GET /baby/{baby_id}/womb-graph`，200 返回完整快照，404 不存在
- [x] 8.6 前端 `useWombGraph` 新增 `loadSnapshot(graph)` 方法接受完整 `{nodes, edges}` 快照
- [x] 8.7 `App.jsx` 的 `fetchWombGraph` 改调 `/baby/{id}/womb-graph`（替代废弃的 `/causal-graph`），结果通过 `loadSnapshot` 注入图状态

## 9. 节点 narrative 双语支持（Phase J · 新增）

- [x] 9.1 `graph_emit.py` `_node()` 及所有 `node_*` 构造器接受 `narrative_en` 参数，双语写入 `narrative.primary = {zh_CN, en}`
- [x] 9.2 `graph_story.py` 所有 META 字典（ORGAN_META/VITAL_META/HORMONE_META/NUTRIENT_META/TERATOGEN_META/REFLEX_EMERGE）补 `narrative_en` 英文版本
- [x] 9.3 前端 `adaptNodes(nodes, lang)` 按当前语言选择 narrative，缺失时 fallback
- [x] 9.4 LifeGraph 组件 Summary / Scientific 区块按 lang 渲染
- [x] 9.5 前端 I18N 字典扩充 28 个 key，覆盖节点面板 / 边面板 / 自环面板所有硬编码字符串

## 10. narrative 节点 emit（Phase K · 新增）

- [x] 10.1 `graph_story.py` 新增 `build_narrative_delta(stage_num, text)` helper，独立 emit narrative 节点 + `DESCRIBES → baby` 边
- [x] 10.2 `stages.py` 每阶段 LLM `parsed` 返回后，尝试提取叙事文本（候选字段 `prose` / `narrative` / `maternal_prose` / `description` / `first_cry` / `summary`，回退取第一个长度 ≥30 的字符串值）
- [x] 10.3 提取到后 yield 一条 `phase: 'narrative'` 的额外 graph_delta 事件，保证 fate_birth 组在正常孕育里也有节点出现
- [x] 10.4 try/except 兜底：叙事提取失败不拖死 SSE 流

## 11. 文档同步（Phase H · DocOps 分形回环）

- [ ] 8.1 `backend/womb/CLAUDE.md` L2 文档更新：新增 `graph_emit.py` 到成员清单；`conceive()` 返回字段文档补充 `graph_delta`。
- [ ] 8.2 `backend/womb/graph_emit.py` L3 文件头注释完整（INPUT/OUTPUT/POS/PROTOCOL）。
- [ ] 8.3 `frontend/src/hooks/useWombGraph.js` L3 文件头注释完整。
- [ ] 8.4 `frontend/src/components/LifeGraph.jsx` L3 文件头注释的 [OUTPUT] 和 [INPUT] 字段如有变化同步更新；增加 "2026-04-21 方案A 业务即图" 扩展记录。
- [ ] 8.5 `/CLAUDE.md` L1 顶层文档如有架构性变更（womb 模块新增子模块）同步。
- [ ] 8.6 memory 更新：`project_womb_status.md` 补充"实时图谱能力上线"条目。
